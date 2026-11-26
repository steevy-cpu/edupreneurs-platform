"""Independent verification of the arithmetic a learner actually READS.

The authored proof records (`verification.json`) say what the author intends. This module ignores them: it finds every
arithmetic statement in the displayed text, parses it into an exact value, and decides whether it is TRUE. A displayed
`36 × 10 = 3600` or `4 501 ÷ 10 = 450` is therefore a finding no matter what any proof record says.

Boundaries. A statement is judged only as a WHOLE. A maximal run of numbers, operators, parentheses and *unsupported
mathematical symbols* (`/ ^ * % √ · ² ³ ½`, a decimal comma or point, an ASCII hyphen or en dash used as a minus, a letter `x`
between numbers) is collected first. A run that holds a relation sign and any unsupported symbol is reported as unsupported
notation: it is never reduced to a "true" suffix (`1/2 = 2` is not the verified `2 = 2`). The same applies to a run that
begins or ends with an operator while a relation has operands on both sides (`2 + 2 = 5 +`), and to a run glued to letters
(`2x = 6`).

Deliberately NOT interpreted, and recorded as "skipped" so that nothing can claim it was checked:
  * a run next to a unit of measure (`8 km = 8 × 1 000 m`): converting units is not an equality of numbers;
  * a decomposition into named units (`3 480 = 3 milliers + 4 centaines`);
  * a fragment whose relation lacks an operand on one side (`= 1 000`), and literal formulas without numbers (`a = b × q + r`).
Hitting the statement limit is a reported problem, not a silent stop.

Supported statement language (anything else is simply prose and is not interpreted):

    statement  := expr (REL expr)+            REL is one of  =  ≠  <  >  ≤  ≥
    expr       := term (("+" | "−") term)*
    term       := factor (("×" | "÷") factor)*
    factor     := NUMBER | "(" expr ")"
    NUMBER     := digits, optionally grouped in threes with a no-break space ("12 480")

Arithmetic is exact: integers and `fractions.Fraction`, never floats. `÷` is EXACT division, so `4 501 ÷ 10 = 450` is
false. Euclidean division is a separate, explicit form: `a ÷ b = q, reste r` (or `rès r` in Creole) is true when
`a = b × q + r` and `0 ≤ r < b` (a positive divisor): the whole statement is recognised BEFORE any equality is evaluated,
so `12 ÷ 4 = 3, reste 1` is false even though `12 ÷ 4 = 3` is true. Division by zero is reported. The size of numbers, expressions and statements is bounded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

NBSP = " "
MAX_DIGITS = 18  # numbers longer than this are not interpreted (and are reported, not computed)
MAX_TOKENS = 80  # per statement
MAX_STATEMENTS = 400  # per text

_TOKEN = re.compile(
    rf"(?P<dec>\d+(?:{NBSP}\d{{3}})*[.,]\d+)|(?P<num>\d+(?:{NBSP}\d{{3}})*)|(?P<op>[+−×÷=≠<>≤≥()])"
    rf"|(?P<sym>[/^*%√∕⁄·²³¼½¾\u2150-\u215e])"
    r"|(?P<glue>(?<=\d)(?![mglMGL])[A-Za-z](?![A-Za-z])|(?<![A-Za-z])(?![mglMGL])[A-Za-z](?=\d))"  # `2x`, `x2`: a variable
    rf"|(?P<space>[ {NBSP}]+)|(?P<other>.)",
    re.S,
)
_REL = {"=", "≠", "<", ">", "≤", "≥"}
_UNIT_AFTER = re.compile(r"^\s*(?:km|cm|mm|kg|g|m|l|dl|cl)\b", re.I)
_UNIT_BEFORE = re.compile(r"\b(?:km|cm|mm|kg|g|m|l|dl|cl)\s*$", re.I)
_REMAINDER = re.compile(rf"^\s*[,;]?\s*(?:reste|rès)\s+(\d+(?:{NBSP}\d{{3}})*)(?!\d)", re.I)
_OPS = set("+−×÷")
_SIDE_OPEN = set("+−×÷(")
_LETTER = re.compile(r"[^\W\d_]")


class MathError(ValueError):
    """A statement that cannot be evaluated (division by zero, number too large, unbalanced parentheses...)."""


@dataclass(frozen=True)
class Statement:
    text: str
    holds: bool
    detail: str = ""


def _prev_char(text: str, pos: int) -> str:
    i = pos - 1
    while i >= 0 and text[i] in f" {NBSP}":
        i -= 1
    return text[i] if i >= 0 else ""


def _next_char(text: str, pos: int) -> str:
    i = pos
    while i < len(text) and text[i] in f" {NBSP}":
        i += 1
    return text[i] if i < len(text) else ""


def _is_math_dash(text: str, start: int, end: int) -> bool:
    """An ASCII hyphen or en dash that plays the part of a minus: next to a number or parenthesis, and not a list bullet."""
    line_start = text.rfind("\n", 0, start) + 1
    if not text[line_start:start].strip() and text[end : end + 1].isspace():
        return False  # "- item": a bullet
    return _prev_char(text, start) in tuple("0123456789)") or _next_char(text, end) in tuple("0123456789(")


def _is_times_letter(text: str, start: int, end: int) -> bool:
    """A letter x/X written between two numbers as a multiplication sign (`3 x 4`)."""
    before, after = text[start - 1 : start], text[end : end + 1]
    if (before and _LETTER.match(before)) or (after and _LETTER.match(after)):
        return False
    return _prev_char(text, start) in tuple("0123456789)") and _next_char(text, end) in tuple("0123456789(")


def _tokens(text: str) -> list[tuple[str, str, int, int]]:
    out = []
    for m in _TOKEN.finditer(text):
        kind = m.lastgroup or "other"
        if kind == "space":
            continue
        if kind == "other" and (
            (m.group() in "-–" and _is_math_dash(text, m.start(), m.end())) or (m.group() in "xX" and _is_times_letter(text, m.start(), m.end()))
        ):
            kind = "sym"
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


@dataclass(frozen=True)
class Skipped:
    """A relation the tool deliberately did not interpret (so nothing may call it "checked")."""

    kind: str  # unit | named_unit | fragment
    text: str  # the run, with a little context


@dataclass
class Analysis:
    statements: list[Statement]
    problems: list[str]
    skipped: list[Skipped]
    limit_reached: bool = False


def _int_of(v: Fraction) -> int | None:
    return v.numerator if v.denominator == 1 else None


def _euclid(sides: list[list[tuple[str, str]] | str], remainder: int) -> tuple[bool, str]:
    """`a ÷ b = q, reste r`: the only supported inexact division. Raises MathError for any other shape.

    True exactly when `a = b × q + r`, the divisor is positive and `0 ≤ r < b`. The plain equality `a ÷ b = q` is never
    consulted, so a remainder is wrong even when the division happens to be exact.
    """
    if len(sides) != 3 or sides[1] != "=":
        raise MathError("a remainder needs the form 'a ÷ b = q, reste r'")
    lhs, rhs = sides[0], sides[2]
    assert isinstance(lhs, list) and isinstance(rhs, list)
    depth, cuts = 0, []
    for i, (_, v) in enumerate(lhs):
        depth += (v == "(") - (v == ")")
        if depth == 0 and v in _OPS:
            cuts.append(i)
    if len(cuts) != 1 or lhs[cuts[0]][1] != "÷" or cuts[0] == 0 or cuts[0] == len(lhs) - 1:
        raise MathError("a remainder needs exactly one division 'a ÷ b' on the left of the equals sign")

    def whole(tokens: list[tuple[str, str]]) -> Fraction:
        p = _Parser(tokens)
        value = p.expr()
        if p.i != len(tokens):
            raise MathError("trailing symbols")
        return value

    a, b, q = whole(lhs[: cuts[0]]), whole(lhs[cuts[0] + 1 :]), whole(rhs)
    ai, bi, qi = _int_of(a), _int_of(b), _int_of(q)
    if ai is None or bi is None or qi is None:
        return False, "euclidean division needs whole numbers"
    if bi <= 0:
        return False, "the divisor must be positive"
    if not 0 <= remainder < bi:
        return False, f"the remainder {remainder} is not between 0 and {bi - 1}"
    if ai != bi * qi + remainder:
        return False, f"{ai} ≠ {bi} × {qi} + {remainder}"
    return True, "euclidean division with remainder"


def analyze(text: str) -> Analysis:
    """Every arithmetic statement in `text`, what could not be interpreted, and what was deliberately skipped.

    A run is a maximal sequence of numbers, operators, parentheses and unsupported mathematical symbols; any letter or
    punctuation ends it. A run without a relation sign is a bare expression and is only checked for being well formed
    when it contains an operator.
    """
    found: list[Statement] = []
    problems: list[str] = []
    skipped: list[Skipped] = []
    overflow = False
    toks = _tokens(text)
    runs: list[list[tuple[str, str, int, int]]] = []
    run: list[tuple[str, str, int, int]] = []

    def close() -> None:
        nonlocal run
        if run:
            runs.append(run)
        run = []

    def context(a: int, b: int) -> str:
        """The enclosing sentence (or line), so a reviewer can find the passage."""
        dot = text.rfind(". ", 0, a)
        start = max(dot + 2 if dot != -1 else 0, text.rfind("\n", 0, a) + 1)
        ends = [e for e in (text.find(". ", b), text.find("\n", b)) if e != -1]
        end = min(ends) + 1 if ends else len(text)
        sentence = " ".join(text[start:end].split())
        return sentence if len(sentence) <= 160 else sentence[:157] + "…"

    def judge(index: int) -> None:
        nonlocal overflow
        current = runs[index]
        nxt = runs[index + 1] if index + 1 < len(runs) else None
        prev_end = runs[index - 1][-1][3] if index else 0
        first, last = current[0], current[-1]
        shown = text[first[2] : last[3]]
        values_ = [v for _, v, _, _ in current]
        has_rel = any(v in _REL for v in values_)

        def skip(kind: str) -> None:
            if has_rel:
                skipped.append(Skipped(kind, context(first[2], last[3])))

        # "3 480 = 3 milliers + 4 centaines": numbers split by words around operators are a decomposition into named
        # units, not a numeric equality.
        gap_after = text[last[3] : nxt[0][2]].strip() if nxt else ""
        gap_before = text[prev_end : first[2]].strip() if index else ""
        if (nxt and nxt[0][1] in _OPS and gap_after and gap_after not in ",;.:") or (
            first[1] in _OPS and _LETTER.search(gap_before) and not _REMAINDER.match(gap_before)
        ):
            skip("named_unit")
            return
        # A run next to a unit of measure: converting units is not an equality of numbers.
        if _UNIT_AFTER.match(text[last[3] :]) or _UNIT_BEFORE.search(text[: first[2]]):
            skip("unit")
            return
        left_operand = right_operand = False
        for _, v, _, _ in current:
            if v in _REL:
                break
            left_operand = left_operand or v not in _SIDE_OPEN
        for _, v, _, _ in reversed(current):
            if v in _REL:
                break
            right_operand = right_operand or v not in _OPS | {")"}
        claim_shaped = has_rel and left_operand and right_operand
        edged = first[1] in _OPS | _REL | {")"} or last[1] in _SIDE_OPEN | _REL
        if edged:
            if claim_shaped:
                problems.append(f"{shown!r}: the expression is incomplete (it begins or ends with an operator)")
            else:
                skip("fragment")
            return
        # A letter glued to the run (`2x = 6`) is notation this tool does not read.
        glued = (text[first[2] - 1 : first[2]] and _LETTER.match(text[first[2] - 1 : first[2]])) or (
            text[last[3] : last[3] + 1] and _LETTER.match(text[last[3] : last[3] + 1])
        )
        unsupported = sorted({v for k, v, _, _ in current if k in ("sym", "dec", "glue")})
        if has_rel and (unsupported or glued):
            what = ", ".join(unsupported) if unsupported else "letters attached to a number"
            problems.append(f"{shown!r}: unsupported notation ({what}); the statement cannot be verified and is not treated as true")
            return
        if unsupported or (not has_rel and len(current) < 2):
            return  # no relation, or a lone number: there is no claim to verify
        if len(current) > MAX_TOKENS:
            problems.append(f"{shown[:40]!r}…: statement longer than {MAX_TOKENS} tokens is not interpreted")
            return
        if len(found) >= MAX_STATEMENTS:
            overflow = True
            return
        simple = [(k, v) for k, v, _, _ in current]
        if not has_rel:
            if any(v in _OPS for _, v in simple):
                try:
                    p = _Parser(simple)
                    p.expr()
                    if p.i != len(simple):
                        raise MathError("trailing symbols")
                except (MathError, IndexError) as exc:
                    problems.append(f"{shown!r}: {exc}")
            return
        sides = _split_relations(simple)
        tail = _REMAINDER.match(text[last[3] :])
        try:
            if tail:
                ok, detail = _euclid(sides, int(tail.group(1).replace(NBSP, "")))
                found.append(Statement(f"{shown}, reste {tail.group(1)}", ok, "" if ok else detail))
                return
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
        found.append(Statement(shown, ok, "" if ok else "values " + " , ".join(str(v) for v in values)))

    for tok in toks:
        if tok[0] in ("num", "dec", "op", "sym", "glue"):
            run.append(tok)
        else:
            close()
    close()
    for i in range(len(runs)):
        judge(i)
    if overflow:
        problems.append(f"more than {MAX_STATEMENTS} mathematical statements in one text: the rest was NOT checked")
    return Analysis(found, problems, skipped, overflow)


def statements(text: str) -> tuple[list[Statement], list[str]]:
    """Judged statements and structural problems (see `analyze` for what was skipped on purpose)."""
    a = analyze(text)
    return a.statements, a.problems


def value_of(expression: str) -> Fraction:
    """Exact value of a bare expression written with the displayed symbols (used to check `prompt_math`)."""
    toks = [(k, v) for k, v, _, _ in _tokens(expression)]
    p = _Parser(toks)
    value = p.expr()
    if p.i != len(toks):
        raise MathError("trailing symbols")
    return value
