"""Independent verification of the arithmetic a learner actually READS.

The authored proof records (`verification.json`) say what the author intends. This module ignores them: it finds every
arithmetic statement in the displayed text, parses it into an exact value, and decides whether it is TRUE. A displayed
`36 × 10 = 3600` or `4 501 ÷ 10 = 450` is therefore a finding no matter what any proof record says.

Only complete statements are interpreted: a run that begins or ends with an operator, or that sits next to a unit of
measure, is left alone (this is a stated limitation, not a verification).

Supported statement language (anything else is simply prose and is not interpreted):

    statement  := expr (REL expr)+            REL is one of  =  ≠  <  >  ≤  ≥
    expr       := term (("+" | "−") term)*
    term       := factor (("×" | "÷") factor)*
    factor     := NUMBER | "(" expr ")"
    NUMBER     := digits, optionally grouped in threes with a no-break space ("12 480")

Arithmetic is exact: integers and `fractions.Fraction`, never floats. `÷` is EXACT division, so `4 501 ÷ 10 = 450` is
false. Euclidean division is a separate, explicit form: `a ÷ b = q, reste r` (or `rès r` in Creole) is true when
`a = b × q + r` and `0 ≤ r < b`. Division by zero is reported. The size of numbers, expressions and statements is bounded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

NBSP = " "
MAX_DIGITS = 18  # numbers longer than this are not interpreted (and are reported, not computed)
MAX_TOKENS = 80  # per statement
MAX_STATEMENTS = 400  # per text

_TOKEN = re.compile(rf"(?P<num>\d+(?:{NBSP}\d{{3}})*)|(?P<op>[+−×÷=≠<>≤≥()])|(?P<space>[ {NBSP}]+)|(?P<other>.)", re.S)
_REL = {"=", "≠", "<", ">", "≤", "≥"}
_UNIT_AFTER = re.compile(r"^\s*(?:km|cm|mm|kg|g|m|l|dl|cl)\b", re.I)
_UNIT_BEFORE = re.compile(r"\b(?:km|cm|mm|kg|g|m|l|dl|cl)\s*$", re.I)
_REMAINDER = re.compile(r"^\s*[,;]?\s*(?:reste|rès)\s+(\d+)(?!\d)", re.I)


class MathError(ValueError):
    """A statement that cannot be evaluated (division by zero, number too large, unbalanced parentheses...)."""


@dataclass(frozen=True)
class Statement:
    text: str
    holds: bool
    detail: str = ""


def _tokens(text: str) -> list[tuple[str, str, int, int]]:
    out = []
    for m in _TOKEN.finditer(text):
        kind = m.lastgroup or "other"
        if kind != "space":
            out.append((kind, m.group(), m.start(), m.end()))
    return out


class _Parser:
    def __init__(self, toks: list[tuple[str, str]]) -> None:
        self.toks, self.i = toks, 0

    def peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> tuple[str, str]:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expr(self, depth: int = 0) -> Fraction:
        if depth > 12:
            raise MathError("parentheses nested too deeply")
        value = self.term(depth)
        while (t := self.peek()) and t[1] in "+−":
            self.take()
            rhs = self.term(depth)
            value = value + rhs if t[1] == "+" else value - rhs
        return value

    def term(self, depth: int) -> Fraction:
        value = self.factor(depth)
        while (t := self.peek()) and t[1] in "×÷":
            self.take()
            rhs = self.factor(depth)
            if t[1] == "×":
                value *= rhs
            elif rhs == 0:
                raise MathError("division by zero")
            else:
                value /= rhs
        return value

    def factor(self, depth: int) -> Fraction:
        t = self.peek()
        if t is None:
            raise MathError("expression ends where a number was expected")
        if t[0] == "num":
            self.take()
            digits = t[1].replace(NBSP, "")
            if len(digits) > MAX_DIGITS:
                raise MathError(f"number with more than {MAX_DIGITS} digits")
            return Fraction(int(digits))
        if t[1] == "(":
            self.take()
            value = self.expr(depth + 1)
            if not (c := self.peek()) or c[1] != ")":
                raise MathError("missing closing parenthesis")
            self.take()
            return value
        raise MathError(f"unexpected {t[1]!r}")


def _split_relations(toks: list[tuple[str, str]]) -> list[list[tuple[str, str]] | str]:
    """[side, REL, side, REL, side ...] with each side a token list."""
    parts: list[list[tuple[str, str]] | str] = [[]]
    for t in toks:
        if t[1] in _REL:
            parts += [t[1], []]
        else:
            parts[-1].append(t)  # type: ignore[union-attr]
    return parts


def _holds(rel: str, a: Fraction, b: Fraction) -> bool:
    return {"=": a == b, "≠": a != b, "<": a < b, ">": a > b, "≤": a <= b, "≥": a >= b}[rel]


def _euclid(sides: list[list[tuple[str, str]] | str], remainder: int) -> bool | None:
    """`a ÷ b = q, reste r`: the only supported inexact division. None when the statement has another shape."""
    if len(sides) != 3 or sides[1] != "=":
        return None
    lhs, rhs = sides[0], sides[2]
    if [t[1] for t in lhs][1:2] != ["÷"] or len(lhs) != 3 or len(rhs) != 1 or lhs[0][0] != "num" or lhs[2][0] != "num" or rhs[0][0] != "num":
        return None
    a, b, q = (int(t[1].replace(NBSP, "")) for t in (lhs[0], lhs[2], rhs[0]))
    return b != 0 and a == b * q + remainder and 0 <= remainder < b


def statements(text: str) -> tuple[list[Statement], list[str]]:
    """Every arithmetic statement in `text`, and a list of structural problems (unparseable runs).

    A run is a maximal sequence of numbers, operators and parentheses; any letter or punctuation ends it. A run
    without a relation sign is a bare expression (for example the operation a question asks for) and is only checked
    for being well formed when it contains an operator.
    """
    found: list[Statement] = []
    problems: list[str] = []
    toks = _tokens(text)
    runs: list[list[tuple[str, str, int, int]]] = []
    run: list[tuple[str, str, int, int]] = []

    def close() -> None:
        nonlocal run
        if run:
            runs.append(run)
        run = []

    def judge(index: int) -> None:
        current = runs[index]
        nxt = runs[index + 1] if index + 1 < len(runs) else None
        # "3 480 = 3 milliers + 4 centaines": a quantity followed by a word and then a continuing operator is a
        # decomposition into named units, not a numeric equality. Left alone (stated limitation).
        if nxt is not None and nxt[0][1] in "+−×÷" and text[current[-1][3] : nxt[0][2]].strip() and text[current[-1][3] : nxt[0][2]].strip() not in ",;.:":
            return
        if len(found) + len(problems) >= MAX_STATEMENTS:
            return
        shown = text[current[0][2] : current[-1][3]]
        # Not interpreted, by design: a fragment that begins or ends with an operator ("= 1 000"), and any run next to
        # a unit of measure ("8 km = 8 × 1 000 m"): converting units is not an equality of numbers.
        if current[0][1] in _REL | set("+−×÷") or current[-1][1] in _REL | set("+−×÷("):
            return
        if _UNIT_AFTER.match(text[current[-1][3] :]) or _UNIT_BEFORE.search(text[: current[0][2]]):
            return
        if len(current) > MAX_TOKENS:
            problems.append(f"{shown[:40]!r}…: statement longer than {MAX_TOKENS} tokens is not interpreted")
            return
        simple = [(k, v) for k, v, _, _ in current]
        if not any(v in _REL for _, v in simple):
            if len(simple) > 1 and any(v in "+−×÷" for _, v in simple):
                try:
                    p = _Parser(simple)
                    p.expr()
                    if p.i != len(simple):
                        raise MathError("trailing symbols")
                except (MathError, IndexError) as exc:
                    problems.append(f"{shown!r}: {exc}")
            return
        try:
            sides = _split_relations(simple)
            values: list[Fraction] = []
            for side in sides[::2]:
                p = _Parser(side)  # type: ignore[arg-type]
                values.append(p.expr())
                if p.i != len(side):
                    raise MathError("trailing symbols")
        except (MathError, IndexError) as exc:
            problems.append(f"{shown!r}: {exc}")
            return
        rels = [r for r in sides[1::2] if isinstance(r, str)]
        ok = all(_holds(r, values[i], values[i + 1]) for i, r in enumerate(rels))
        detail = ""
        if not ok:
            m = _REMAINDER.match(text[current[-1][3] :])
            if m and (verdict := _euclid(sides, int(m.group(1)))) is not None:
                ok = verdict
                detail = "euclidean division with remainder"
            else:
                detail = "values " + " , ".join(str(v) for v in values)
        found.append(Statement(shown, ok, detail))

    for tok in toks:
        if tok[0] in ("num", "op"):
            run.append(tok)
        else:
            close()
    close()
    for i in range(len(runs)):
        judge(i)
    return found, problems


def value_of(expression: str) -> Fraction:
    """Exact value of a bare expression written with the displayed symbols (used to check `prompt_math`)."""
    toks = [(k, v) for k, v, _, _ in _tokens(expression)]
    p = _Parser(toks)
    value = p.expr()
    if p.i != len(toks):
        raise MathError("trailing symbols")
    return value
