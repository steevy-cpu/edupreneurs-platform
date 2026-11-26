import pytest
from content_pilot.safe_eval import UnsafeExpression, safe_eval
from content_pilot.textrules import number_tokens, scan_text


@pytest.mark.parametrize(
    ("expr", "value"),
    [
        ("348 + 275", 623),
        ("623 - 275", 348),
        ("6 * 12", 72),
        ("17 // 5", 3),
        ("17 % 5", 2),
        ("2 ** 3", 8),
        ("max(1, 9, 3)", 9),
        ("5 > 3", True),
        ("1 < 2 < 3", True),
        ("1 < 3 < 2", False),
        ("True and not False", True),
        ("[d for d in range(1, 13) if 12 % d == 0]", [1, 2, 3, 4, 6, 12]),
        ("min([n for n in (2, 3, 4, 6) if 18 % n != 0])", 4),
        ("len([1, 2, 3])", 3),
        ("1 if 2 > 1 else 0", 1),
        ("gcd(12, 18)", 6),
    ],
)
def test_allowed_expressions(expr, value):
    assert safe_eval(expr) == value


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "open('f')",
        "().__class__",
        "x + 1",
        "'a'.upper()",
        "lambda: 1",
        "[x for x in range(3) for y in range(3)]",
        "2 ** 99",
        "2 ** -1",
        "10 / 2",
        "range(10 ** 9)",
        "print(1)",
        "eval('1')",
        "1 +",
        "{1: 2}",
        "1.5 + 1",
        "b'x'",
        "f'{1}'",
    ],
)
def test_refused_expressions(expr):
    with pytest.raises((UnsafeExpression, ZeroDivisionError)):
        safe_eval(expr)


def test_division_by_zero_is_an_error_not_a_crash():
    with pytest.raises(ZeroDivisionError):
        safe_eval("1 // 0")


def test_scan_text_accepts_normal_french_and_creole():
    for s in ("Calcule : 348 + 275 = 623.", "Nan nonb 5\u00a0723 lan, ki valè chif 7 la ?", "Si 3 < 5 et 5 > 3 : « oui »."):
        assert scan_text(s) == [], s


def test_number_tokens_join_nbsp_groups_only():
    assert number_tokens("de 2\u00a0450 à 1\u00a0980 et 7") == sorted(["2\u00a0450", "1\u00a0980", "7"])
    assert number_tokens("2 450") == sorted(["2", "450"])  # a plain space is two numbers
