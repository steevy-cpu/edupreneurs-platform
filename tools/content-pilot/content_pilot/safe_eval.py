"""A tiny, safe evaluator for the arithmetic used to CHECK answers and worked examples.

Only literals, arithmetic, comparisons, boolean operators, tuples/lists, list comprehensions over `range`
and a short list of pure functions are allowed. No attribute access, no names other than the comprehension
variables, no imports, no calls to anything not listed. Exponents are capped so a hostile expression cannot
hang the validator.
"""

from __future__ import annotations

import ast
import math
import operator
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
_FUNCS = {
    "max": max,
    "min": min,
    "sum": sum,
    "abs": abs,
    "len": len,
    "range": range,
    "sorted": sorted,
    "gcd": math.gcd,
}
MAX_EXPONENT = 12
MAX_RANGE = 100_000


class UnsafeExpression(ValueError):
    """Raised for anything outside the allowed subset."""


def safe_eval(expr: str) -> Any:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"syntax error: {exc.msg}") from exc
    return _eval(tree.body, {})


def _eval(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, bool, str)):
            return node.value
        raise UnsafeExpression(f"constant {node.value!r} not allowed")
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise UnsafeExpression(f"name {node.id!r} not allowed")
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_eval(e, env) for e in node.elts]
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.Not):
            return not v
        raise UnsafeExpression("unary operator not allowed")
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow):
            if not (isinstance(right, int) and 0 <= right <= MAX_EXPONENT):
                raise UnsafeExpression("exponent out of range")
            return left**right
        op = _BIN.get(type(node.op))
        if op is None:
            raise UnsafeExpression("operator not allowed (true division is not used for naturals)")
        return op(left, right)
    if isinstance(node, ast.BoolOp):
        vals = (_eval(v, env) for v in node.values)
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op_node, comp in zip(node.ops, node.comparators, strict=True):
            op = _CMP.get(type(op_node))
            if op is None:
                raise UnsafeExpression("comparison not allowed")
            right = _eval(comp, env)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords:
            raise UnsafeExpression("call not allowed")
        args = [_eval(a, env) for a in node.args]
        if node.func.id == "range" and args and max(abs(a) for a in args) > MAX_RANGE:
            raise UnsafeExpression("range too large")
        return _FUNCS[node.func.id](*args)
    if isinstance(node, ast.ListComp):
        if len(node.generators) != 1:
            raise UnsafeExpression("one generator only")
        gen = node.generators[0]
        if not isinstance(gen.target, ast.Name) or gen.is_async:
            raise UnsafeExpression("comprehension target not allowed")
        out = []
        for item in _eval(gen.iter, env):
            inner = {**env, gen.target.id: item}
            if all(_eval(c, inner) for c in gen.ifs):
                out.append(_eval(node.elt, inner))
        return out
    raise UnsafeExpression(f"{type(node).__name__} not allowed")
