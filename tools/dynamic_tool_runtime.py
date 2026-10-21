"""Minimal AST interpreter used by the dynamic micro-tool subprocess."""

from __future__ import annotations

import ast
import json
import sys
from typing import Any

from dynamic_tools import (
    MAX_LOOP_ITEMS,
    MAX_STEPS,
    _ALLOWED_NODE_TYPES,
    _BIN_OPS,
    _COMPARE_OPS,
    _SAFE_BUILTINS,
    _SAFE_METHODS,
    _UNARY_OPS,
    _parse_and_validate_source,
)


class _ReturnValue(Exception):
    def __init__(self, value: Any):
        self.value = value


class _Budget:
    def __init__(self) -> None:
        self.remaining = MAX_STEPS

    def consume(self, amount: int = 1) -> None:
        self.remaining -= amount
        if self.remaining < 0:
            raise RuntimeError("Dynamic tool exceeded its execution-step limit.")


def _safe_method(target: Any, name: str) -> Any:
    for target_type, methods in _SAFE_METHODS.items():
        if type(target) is target_type and name in methods:
            return getattr(target, name)
    raise ValueError(f"Method '{name}' is not allowed for this value.")


def _eval(node: ast.AST, env: dict[str, Any], budget: _Budget) -> Any:
    budget.consume()
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _SAFE_BUILTINS:
            return _SAFE_BUILTINS[node.id]
        raise ValueError(f"Name '{node.id}' is not available.")
    if isinstance(node, ast.List):
        return [_eval(item, env, budget) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(item, env, budget) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _eval(key, env, budget): _eval(value, env, budget)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.BinOp):
        operation = _BIN_OPS.get(type(node.op))
        if operation is None:
            raise ValueError("This arithmetic operator is not available.")
        return operation(_eval(node.left, env, budget), _eval(node.right, env, budget))
    if isinstance(node, ast.UnaryOp):
        operation = _UNARY_OPS.get(type(node.op))
        if operation is None:
            raise ValueError("This unary operator is not available.")
        return operation(_eval(node.operand, env, budget))
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = _eval(value, env, budget)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = _eval(value, env, budget)
            if result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, budget)
        for operation_node, comparator in zip(node.ops, node.comparators):
            operation = _COMPARE_OPS.get(type(operation_node))
            if operation is None:
                raise ValueError("This comparison operator is not available.")
            right = _eval(comparator, env, budget)
            if not operation(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, env, budget) else node.orelse, env, budget)
    if isinstance(node, ast.Subscript):
        target = _eval(node.value, env, budget)
        if type(target) not in {dict, list, tuple, str}:
            raise ValueError("Indexing is limited to JSON objects, arrays, and strings.")
        index = _eval(node.slice, env, budget)
        return target[index]
    if isinstance(node, ast.Slice):
        lower = _eval(node.lower, env, budget) if node.lower else None
        upper = _eval(node.upper, env, budget) if node.upper else None
        step = _eval(node.step, env, budget) if node.step else None
        return slice(lower, upper, step)
    if isinstance(node, ast.Attribute):
        raise ValueError("Data methods may only be used as direct function calls.")
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            function = _eval(node.func, env, budget)
            positional = [_eval(arg, env, budget) for arg in node.args]
            named = {item.arg: _eval(item.value, env, budget) for item in node.keywords}
            if function is range:
                result = range(*positional, **named)
                if len(result) > MAX_LOOP_ITEMS:
                    raise ValueError(f"Dynamic ranges are limited to {MAX_LOOP_ITEMS} values.")
                return result
            return function(*positional, **named)
        if isinstance(node.func, ast.Attribute):
            target = _eval(node.func.value, env, budget)
            function = _safe_method(target, node.func.attr)
            positional = [_eval(arg, env, budget) for arg in node.args]
            named = {item.arg: _eval(item.value, env, budget) for item in node.keywords}
            return function(*positional, **named)
        raise ValueError("Only approved built-ins and data methods may be called.")
    if isinstance(node, ast.ListComp):
        if len(node.generators) > 3:
            raise ValueError("Comprehensions may contain at most three loops.")
        result: list[Any] = []

        def walk_generator(index: int, local_env: dict[str, Any]) -> None:
            budget.consume()
            if index >= len(node.generators):
                result.append(_eval(node.elt, local_env, budget))
                if len(result) > MAX_LOOP_ITEMS:
                    raise ValueError(f"Comprehensions are limited to {MAX_LOOP_ITEMS} items.")
                return
            generator = node.generators[index]
            if not isinstance(generator.target, ast.Name):
                raise ValueError("Comprehension targets must be simple names.")
            iterable = _eval(generator.iter, local_env, budget)
            if not isinstance(iterable, (list, tuple, str, range, dict)):
                raise ValueError("Comprehensions may iterate only over JSON-like collections.")
            if len(iterable) > MAX_LOOP_ITEMS:
                raise ValueError(f"Comprehensions are limited to {MAX_LOOP_ITEMS} items.")
            for item in iterable:
                nested = dict(local_env)
                nested[generator.target.id] = item
                walk_generator(index + 1, nested)

        walk_generator(0, env)
        return result
    raise ValueError(f"Unsupported expression: {type(node).__name__}.")


def _run_statement(node: ast.stmt, env: dict[str, Any], budget: _Budget) -> None:
    budget.consume()
    if isinstance(node, ast.Return):
        raise _ReturnValue(_eval(node.value, env, budget) if node.value else None)
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise ValueError("Assignments must target one simple variable name.")
        env[node.targets[0].id] = _eval(node.value, env, budget)
        return
    if isinstance(node, ast.If):
        branch = node.body if _eval(node.test, env, budget) else node.orelse
        for statement in branch:
            _run_statement(statement, env, budget)
        return
    if isinstance(node, ast.For):
        if not isinstance(node.target, ast.Name):
            raise ValueError("For-loop targets must be simple variable names.")
        iterable = _eval(node.iter, env, budget)
        if not isinstance(iterable, (list, tuple, str, range, dict)):
            raise ValueError("For loops may iterate only over JSON-like collections.")
        if len(iterable) > MAX_LOOP_ITEMS:
            raise ValueError(f"For loops are limited to {MAX_LOOP_ITEMS} items.")
        for item in iterable:
            budget.consume()
            env[node.target.id] = item
            for statement in node.body:
                _run_statement(statement, env, budget)
        return
    if isinstance(node, ast.Expr):
        _eval(node.value, env, budget)
        return
    if isinstance(node, ast.Pass):
        return
    raise ValueError(f"Unsupported statement: {type(node).__name__}.")


def run(source: str, arguments: dict[str, Any]) -> Any:
    tree = _parse_and_validate_source(source)
    function = tree.body[0]
    environment: dict[str, Any] = {"data": arguments}
    budget = _Budget()
    try:
        for statement in function.body:
            _run_statement(statement, environment, budget)
    except _ReturnValue as returned:
        return returned.value
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = run(payload["source"], payload["arguments"])
        output = json.dumps({"result": result}, ensure_ascii=False, allow_nan=False)
        print(output)
        return 0
    except Exception as error:
        print(str(error)[:1000], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
