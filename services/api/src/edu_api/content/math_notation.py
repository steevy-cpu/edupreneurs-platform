"""The restricted mathematical notation ``edu-math-1``.

A formula is plain text in a small, whitelisted subset of LaTeX mathematics.
It is DATA, not markup that is executed: no macros, no definitions, no
environments, no colours, no links. A phone can draw it with a small renderer
or show a pre-rendered image; in both cases the block's mandatory ``alt`` text
says the formula in words.

GRAMMAR (checked left to right; validation stops at the first error)

    formula := item+                         spaces (U+0020) between items are ignored
    item    := atom script*                  at most one '^' and one '_' per atom
    script  := ('^' | '_') (group | letter | digit | symbol-command)
    group   := '{' item+ '}'                 nesting depth at most 4
    atom    := character | group | command
    command := '\\' name args | '\\%' | '\\{' | '\\}' | '\\,'

    characters   A-Z a-z 0-9 + - * / = < > ( ) [ ] | , . ; : ! '
    symbols      (no argument)  see ZERO_ARG_COMMANDS
    \\frac{a}{b}  \\sqrt{a}  \\sqrt[n]{a}  \\overline{a}  \\vec{a}
    \\mathbb{X}   X is one of N Z D Q R
    \\text{...}   plain words; the only place where accented letters
                 (U+00C0..U+017F except the signs U+00D7 and U+00F7) are allowed

RULE CODES (stable; shared with the phone through the test vectors)

    math.syntax            stray '\\', bare '%', empty group, empty formula
    math.unknown_command   a command that is not on the whitelist
    math.missing_argument  a command without its '{...}' argument(s)
    math.unbalanced        '{', '}' or a root index '[' without its partner
    math.depth             groups nested deeper than 4
    math.script            '^' or '_' without a base, doubled, or without a valid operand
    math.text              a non-ASCII character outside \\text{...}, or a
                           character that is not allowed inside \\text{...}
"""

from __future__ import annotations

NOTATION = "edu-math-1"
MAX_SOURCE_LENGTH = 400
MAX_GROUP_DEPTH = 4

ZERO_ARG_COMMANDS: frozenset[str] = frozenset(
    {
        "times", "div", "cdot", "pm", "le", "ge", "ne", "approx", "equiv",
        "pi", "infty", "alpha", "beta", "gamma", "delta", "theta", "lambda", "mu", "Delta",
        "circ", "angle", "triangle", "parallel", "perp",
        "in", "notin", "cup", "cap", "subset", "emptyset",
        "sin", "cos", "tan", "log", "ln",
        "ldots", "to", "Rightarrow", "Leftrightarrow", "quad",
    }
)  # fmt: skip
GROUP_ARG_COMMANDS: dict[str, int] = {"frac": 2, "sqrt": 1, "overline": 1, "vec": 1}
NUMBER_SETS = "NZDQR"
_ESCAPES = "%{},"
_LITERALS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-*/=<>()[]|,.;:!'"
)
_TEXT_FORBIDDEN = frozenset("\\{^_%")
_ASCII_LETTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
_ASCII_ALNUM = _ASCII_LETTERS | frozenset("0123456789")


class _MathError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_text_char(char: str) -> bool:
    """Allowed inside ``\\text{...}``: printable ASCII (minus a few) and accented Latin letters."""
    if char in _TEXT_FORBIDDEN:
        return False
    code = ord(char)
    if 0x20 <= code <= 0x7E:
        return True
    return 0xC0 <= code <= 0x17F and code not in (0xD7, 0xF7)


class _Parser:
    def __init__(self, source: str) -> None:
        self.s = source
        self.n = len(source)
        self.pos = 0

    def parse(self) -> None:
        if self._expr(0, None) == 0:
            raise _MathError("math.syntax")

    def _expr(self, depth: int, stop: str | None) -> int:
        """Parse items until ``stop`` (not consumed) or the end. Returns the item count."""
        count = 0
        while self.pos < self.n:
            char = self.s[self.pos]
            if char == " ":
                self.pos += 1
                continue
            if char == "}":
                if stop == "}":
                    return count
                raise _MathError("math.unbalanced")
            if char == "]" and stop == "]":
                return count
            self._item(depth)
            count += 1
        if stop is not None:
            raise _MathError("math.unbalanced")
        return count

    def _item(self, depth: int) -> None:
        if self.s[self.pos] in "^_":
            raise _MathError("math.script")
        self._atom(depth)
        seen: set[str] = set()
        while self.pos < self.n and self.s[self.pos] in "^_":
            operator = self.s[self.pos]
            if operator in seen:
                raise _MathError("math.script")
            seen.add(operator)
            self.pos += 1
            self._script_operand(depth)

    def _script_operand(self, depth: int) -> None:
        if self.pos >= self.n:
            raise _MathError("math.script")
        char = self.s[self.pos]
        if char == "{":
            self._group(depth)
        elif char in _ASCII_ALNUM:
            self.pos += 1
        elif char == "\\":
            if self._command_name() not in ZERO_ARG_COMMANDS:
                raise _MathError("math.script")
        else:
            raise _MathError("math.script")

    def _group(self, depth: int) -> None:
        if depth + 1 > MAX_GROUP_DEPTH:
            raise _MathError("math.depth")
        self.pos += 1  # '{'
        if self._expr(depth + 1, "}") == 0:
            raise _MathError("math.syntax")
        self.pos += 1  # '}'

    def _atom(self, depth: int) -> None:
        char = self.s[self.pos]
        if char == "{":
            self._group(depth)
        elif char == "\\":
            self._command(depth)
        elif char in _LITERALS:
            self.pos += 1
        elif ord(char) > 0x7F:
            raise _MathError("math.text")
        else:
            raise _MathError("math.syntax")

    def _command_name(self) -> str:
        """Read ``\\name`` at the current position; returns ``""`` for an escape such as ``\\%``."""
        self.pos += 1  # '\'
        if self.pos >= self.n:
            raise _MathError("math.syntax")
        if self.s[self.pos] in _ESCAPES:
            self.pos += 1
            return ""
        start = self.pos
        while self.pos < self.n and self.s[self.pos] in _ASCII_LETTERS:
            self.pos += 1
        if self.pos == start:
            raise _MathError("math.syntax")
        return self.s[start : self.pos]

    def _command(self, depth: int) -> None:
        name = self._command_name()
        if name == "" or name in ZERO_ARG_COMMANDS:
            return
        if name == "text":
            self._text_argument()
        elif name == "mathbb":
            self._number_set_argument()
        elif name in GROUP_ARG_COMMANDS:
            if name == "sqrt" and self.pos < self.n and self.s[self.pos] == "[":
                self.pos += 1
                if self._expr(depth, "]") == 0:
                    raise _MathError("math.syntax")
                self.pos += 1  # ']'
            for _ in range(GROUP_ARG_COMMANDS[name]):
                if self.pos >= self.n or self.s[self.pos] != "{":
                    raise _MathError("math.missing_argument")
                self._group(depth)
        else:
            raise _MathError("math.unknown_command")

    def _text_argument(self) -> None:
        if self.pos >= self.n or self.s[self.pos] != "{":
            raise _MathError("math.missing_argument")
        self.pos += 1
        start = self.pos
        while self.pos < self.n and self.s[self.pos] != "}":
            if not _is_text_char(self.s[self.pos]):
                raise _MathError("math.text")
            self.pos += 1
        if self.pos >= self.n:
            raise _MathError("math.unbalanced")
        if self.pos == start:
            raise _MathError("math.syntax")
        self.pos += 1  # '}'

    def _number_set_argument(self) -> None:
        if self.pos >= self.n or self.s[self.pos] != "{":
            raise _MathError("math.missing_argument")
        if self.pos + 2 >= self.n or self.s[self.pos + 2] != "}":
            raise _MathError("math.syntax")
        if self.s[self.pos + 1] not in NUMBER_SETS:
            raise _MathError("math.syntax")
        self.pos += 3


def check_math_source(source: str) -> str | None:
    """Rule code of the first grammar error in ``source``, or ``None`` when it is valid.

    The character set and the length are the structural layer's job (the JSON
    Schema pattern); this function assumes they were checked first, but stays
    safe on any input: an unexpected character is a ``math.syntax`` or
    ``math.text`` error, never an exception.
    """
    parser = _Parser(source)
    try:
        parser.parse()
    except _MathError as error:
        return error.code
    return None
