"""A tiny, safe evaluator for the arithmetic used to CHECK answers and worked examples.

Allowed: integer and boolean literals, integer arithmetic (+ - * // % and a bounded **), comparisons, boolean
operators, lists/tuples, one-generator list comprehensions over `range`, and a short list of pure functions.
Refused: names (other than comprehension variables), attributes, imports, strings, floats, true division, and any
arithmetic whose operands are not plain integers (so `[2] * 2` is an error, not a sequence repeat).

The evaluator is also bounded, so a hostile expression cannot exhaust a runner: expression length, syntax-tree
size and nesting depth, a total step budget, the bit length of every integer, and the length of every list.
All limits are in `EvalLimits` so tests can inject tiny ones.
"""

from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass
from typing import Any

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_FUNCS = {"max": max, "min": min, "sum": sum, "abs": abs, "len": len, "range": range, "sorted": sorted, "gcd": math.gcd}
MAX_EXPONENT = 12


@dataclass(frozen=True)
class EvalLimits:
    max_chars: int = 400
    max_nodes: int = 400
    max_depth: int = 30
    max_steps: int = 200_000
    max_bits: int = 128
    max_list: int = 10_000
    max_range: int = 100_000
    max_operands: int = 64  # arguments of max/min/gcd


class UnsafeExpression(ValueError):
    """Raised for anything outside the allowed subset or beyond a resource limit."""


class _Run:
    def __init__(self, limits: EvalLimits) -> None:
        self.limits = limits
        self.steps = 0

    def tick(self) -> None:
        self.steps += 1
        if self.steps > self.limits.max_steps:
            raise UnsafeExpression("step budget exceeded")


def safe_eval(expr: str, limits: EvalLimits | None = None) -> Any:
    lim = limits or EvalLimits()
    if not isinstance(expr, str):
        raise UnsafeExpression("expression must be a string")
    if len(expr) > lim.max_chars:
        raise UnsafeExpression(f"expression longer than {lim.max_chars} characters")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"syntax error: {exc.msg}") from exc
    except (RecursionError, MemoryError, ValueError) as exc:  # ValueError: NUL byte
        raise UnsafeExpression("expression cannot be parsed safely") from exc
    _preflight(tree, lim)
    return _eval(tree.body, {}, _Run(lim))


def _preflight(tree: ast.AST, lim: EvalLimits) -> None:
    """Refuse oversized or too deeply nested syntax trees BEFORE evaluating anything."""
    count = 0
    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > lim.max_nodes:
            raise UnsafeExpression(f"expression has more than {lim.max_nodes} syntax nodes")
        if depth > lim.max_depth:
            raise UnsafeExpression(f"expression nested deeper than {lim.max_depth} levels")
        stack.extend((c, depth + 1) for c in ast.iter_child_nodes(node))


def _int(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise UnsafeExpression("arithmetic works on integers only")
    return v


def _check_bits(v: int, run: _Run) -> int:
    if v.bit_length() > run.limits.max_bits:
        raise UnsafeExpression(f"integer larger than {run.limits.max_bits} bits")
    return v


def _check_list(v: list[Any], run: _Run) -> list[Any]:
    if len(v) > run.limits.max_list:
        raise UnsafeExpression(f"list longer than {run.limits.max_list} items")
    return v


def _eval(node: ast.AST, env: dict[str, Any], run: _Run) -> Any:
    run.tick()
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return node.value
        if isinstance(node.value, int):
            return _check_bits(node.value, run)
        raise UnsafeExpression(f"constant {node.value!r} not allowed")
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise UnsafeExpression(f"name {node.id!r} not allowed")
    if isinstance(node, (ast.Tuple, ast.List)):
        return _check_list([_eval(e, env, run) for e in node.elts], run)
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env, run)
        if isinstance(node.op, ast.USub):
            return -_int(v)
        if isinstance(node.op, ast.Not):
            return not v
        raise UnsafeExpression("unary operator not allowed")
    if isinstance(node, ast.BinOp):
        left, right = _int(_eval(node.left, env, run)), _int(_eval(node.right, env, run))
        if isinstance(node.op, ast.Pow):
            if not 0 <= right <= MAX_EXPONENT or abs(left).bit_length() * right > run.limits.max_bits:
                raise UnsafeExpression("exponent out of range")
            return _check_bits(left**right, run)
        op = _BIN.get(type(node.op))
        if op is None:
            raise UnsafeExpression("operator not allowed (true division is not used for naturals)")
        return _check_bits(op(left, right), run)
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, env, run) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, run)
        for op_node, comp in zip(node.ops, node.comparators, strict=True):
            op = _CMP.get(type(op_node))
            if op is None:
                raise UnsafeExpression("comparison not allowed")
            right = _eval(comp, env, run)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env, run) if _eval(node.test, env, run) else _eval(node.orelse, env, run)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords:
            raise UnsafeExpression("call not allowed")
        args = [_eval(a, env, run) for a in node.args]
        return _call(node.func.id, args, run)
    if isinstance(node, ast.ListComp):
        if len(node.generators) != 1:
            raise UnsafeExpression("one generator only")
        gen = node.generators[0]
        if not isinstance(gen.target, ast.Name) or gen.is_async:
            raise UnsafeExpression("comprehension target not allowed")
        source = _eval(gen.iter, env, run)
        if not isinstance(source, (list, range)):
            raise UnsafeExpression("a comprehension iterates over a list or a range only")
        out: list[Any] = []
        for item in source:
            run.tick()
            inner = {**env, gen.target.id: item}
            if all(_eval(c, inner, run) for c in gen.ifs):
                out.append(_eval(node.elt, inner, run))
                _check_list(out, run)
        return out
    raise UnsafeExpression(f"{type(node).__name__} not allowed")


def _call(name: str, args: list[Any], run: _Run) -> Any:
    """Every builtin enforces the same bounds as the operators: operand counts, step budget, integer bit length."""
    lim = run.limits
    if len(args) > lim.max_operands:
        raise UnsafeExpression(f"more than {lim.max_operands} arguments")
    if name == "range":
        ints = [_int(a) for a in args]
        if not 1 <= len(ints) <= 3 or (len(ints) == 3 and ints[2] == 0):
            raise UnsafeExpression("range needs 1 to 3 integer arguments (step not 0)")
        if max(abs(a) for a in ints) > lim.max_range:
            raise UnsafeExpression("range too large")
        return range(*ints)
    if name == "gcd":
        return _check_bits(math.gcd(*[_int(a) for a in args]), run)
    if name == "abs":
        if len(args) != 1:
            raise UnsafeExpression("abs takes one argument")
        return _check_bits(abs(_int(args[0])), run)
    if name in ("max", "min") and len(args) >= 2:
        return _check_bits(_FUNCS[name](*[_int(a) for a in args]), run)
    if len(args) != 1 or not isinstance(args[0], (list, range)):
        raise UnsafeExpression(f"{name}() takes one list or range")
    seq = args[0]
    if len(seq) > lim.max_list:
        raise UnsafeExpression("list too long")
    for _ in seq:  # sequence work is charged to the step budget before any aggregate runs
        run.tick()
    if name == "len":
        return len(seq)
    items = [_int(item) for item in seq]
    if name == "sum":
        total = 0
        for item in items:  # check the running total, not only the final one
            total = _check_bits(total + item, run)
        return total
    if name in ("max", "min") and not items:
        raise UnsafeExpression(f"{name}() of an empty list")
    result = _FUNCS[name](items)
    return _check_list(result, run) if isinstance(result, list) else _check_bits(result, run)
