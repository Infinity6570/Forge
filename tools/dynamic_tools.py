"""Task-scoped, data-only micro-tools interpreted outside the main server process.

Dynamic tools use a deliberately small Python-like AST instead of executing uploaded
source with ``exec``. They can transform JSON data, but cannot import modules, access
the filesystem, open sockets, spawn commands, or inspect Python objects.
"""

from __future__ import annotations

import ast
import json
import operator
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_TOOL_SOURCE_BYTES = 32_000
MAX_TOOL_INPUT_BYTES = 64_000
MAX_TOOL_OUTPUT_BYTES = 128_000
MAX_DYNAMIC_TOOLS = 64
MAX_AST_NODES = 4_000
MAX_STEPS = 25_000
MAX_LOOP_ITEMS = 10_000
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

_ALLOWED_NODE_TYPES = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign,
    ast.If, ast.For, ast.Expr, ast.Pass, ast.Constant, ast.Name, ast.Load, ast.Store,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.List, ast.Tuple,
    ast.Dict, ast.Subscript, ast.Slice, ast.Call, ast.Attribute, ast.keyword,
    ast.ListComp, ast.comprehension, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt,
    ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
}
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
_COMPARE_OPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_, ast.IsNot: operator.is_not,
}
_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "float": float, "int": int, "len": len, "list": list,
    "max": max, "min": min, "range": range, "round": round, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "zip": zip,
}
_SAFE_METHODS = {
    str: frozenset({
        "capitalize", "casefold", "count", "endswith", "find", "isalnum", "isalpha",
        "isdigit", "islower", "isspace", "isupper", "join", "lower", "lstrip",
        "replace", "rfind", "rstrip", "split", "startswith", "strip", "title",
        "upper",
    }),
    list: frozenset({"append", "count", "extend", "index"}),
    tuple: frozenset({"count", "index"}),
    dict: frozenset({"get", "items", "keys", "values"}),
}


def _tool_directory(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    directory = (root / "tools" / "dynamic").resolve()
    if not directory.is_relative_to(root):
        raise PermissionError("Dynamic tools must remain inside tools/dynamic.")
    return directory


def _parse_and_validate_source(source: str) -> ast.Module:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Provide a non-empty Python-like run(data) function.")
    if len(source.encode("utf-8")) > MAX_TOOL_SOURCE_BYTES:
        raise ValueError(f"Dynamic tool source is limited to {MAX_TOOL_SOURCE_BYTES} bytes.")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as error:
        raise ValueError(f"Dynamic tool syntax error: {error.msg} (line {error.lineno}).") from error
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError("Dynamic tool source contains too many syntax nodes.")
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Define exactly one top-level function: def run(data):")
    function = tree.body[0]
    if (
        function.name != "run"
        or function.decorator_list
        or function.args.posonlyargs
        or function.args.kwonlyargs
        or function.args.vararg
        or function.args.kwarg
        or function.args.defaults
        or len(function.args.args) != 1
        or function.args.args[0].arg != "data"
    ):
        raise ValueError("The only supported entry point is def run(data): with no defaults or decorators.")
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODE_TYPES:
            raise ValueError(f"Dynamic tools do not support {type(node).__name__}.")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("Names beginning with double underscores are not supported.")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("_") or node.attr not in {
                method for methods in _SAFE_METHODS.values() for method in methods
            }
        ):
            raise ValueError("Only approved data-type methods are available in dynamic tools.")
        if isinstance(node, ast.Call):
            if any(keyword.arg is None for keyword in node.keywords):
                raise ValueError("Keyword expansion is not supported in dynamic tools.")
            if isinstance(node.func, ast.Name):
                if node.func.id not in _SAFE_BUILTINS:
                    raise ValueError(f"Dynamic tool function '{node.func.id}' is not available.")
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr.startswith("_"):
                    raise ValueError("Private and dunder methods are not available.")
            else:
                raise ValueError("Dynamic tools may call only approved built-ins or data methods.")
        if isinstance(node, ast.For) and node.orelse:
            raise ValueError("The else clause on loops is not supported.")
        if isinstance(node, ast.comprehension) and node.ifs:
            raise ValueError("Filtered comprehensions are not supported; use an if statement.")
        if isinstance(node, ast.comprehension) and node.is_async:
            raise ValueError("Asynchronous comprehensions are not supported.")
    return tree


def _validate_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("Input schema must be a JSON Schema object with type 'object'.")
    properties = schema.get("properties")
    if not isinstance(properties, dict) or len(properties) > 20:
        raise ValueError("Input schema must define at most 20 named properties.")
    allowed_types = {"string", "number", "integer", "boolean", "array", "object"}
    clean_properties: dict[str, Any] = {}
    for key, value in properties.items():
        if not isinstance(key, str) or not TOOL_NAME_PATTERN.fullmatch(key):
            raise ValueError(f"Invalid dynamic-tool input property name: {key!r}.")
        if not isinstance(value, dict) or value.get("type") not in allowed_types:
            raise ValueError(f"Input property '{key}' needs a supported JSON Schema type.")
        clean = {"type": value["type"]}
        description = value.get("description")
        if isinstance(description, str):
            clean["description"] = description[:300]
        if value["type"] == "array":
            items = value.get("items", {})
            if not isinstance(items, dict) or items.get("type") not in allowed_types - {"array", "object"}:
                raise ValueError(f"Array property '{key}' must specify a primitive item type.")
            clean["items"] = {"type": items["type"]}
        clean_properties[key] = clean
    required = schema.get("required", [])
    if not isinstance(required, list) or any(item not in clean_properties for item in required):
        raise ValueError("Schema 'required' must contain only declared property names.")
    return {
        "type": "object",
        "properties": clean_properties,
        "required": required[:20],
        "additionalProperties": False,
    }


def create_dynamic_tool(
    project_root: str | Path,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    script_content: str,
) -> dict[str, Any]:
    """Validate and persist one data-only helper for later discovery."""
    normalized_name = str(name).strip().lower()
    if not TOOL_NAME_PATTERN.fullmatch(normalized_name):
        raise ValueError("Tool name must use lowercase letters, digits, and underscores.")
    if normalized_name.startswith("dynamic_"):
        normalized_name = normalized_name[len("dynamic_"):]
    if not TOOL_NAME_PATTERN.fullmatch(normalized_name):
        raise ValueError("Tool name must use lowercase letters, digits, and underscores.")
    clean_description = " ".join(str(description).split())[:500]
    if not clean_description:
        raise ValueError("Provide a short description for the dynamic tool.")
    schema = _validate_schema(input_schema)
    _parse_and_validate_source(script_content)

    directory = _tool_directory(project_root)
    directory.mkdir(parents=True, exist_ok=True)
    resolved_directory = directory.resolve()
    py_path = resolved_directory / f"{normalized_name}.py"
    metadata_path = resolved_directory / f"{normalized_name}.json"
    if py_path.exists() or metadata_path.exists():
        raise FileExistsError(
            f"Dynamic tool '{normalized_name}' already exists. Choose a new name instead of replacing it."
        )
    if len(list(resolved_directory.glob("*.json"))) >= MAX_DYNAMIC_TOOLS:
        raise ValueError(f"At most {MAX_DYNAMIC_TOOLS} dynamic tools may be installed.")

    metadata = {
        "name": normalized_name,
        "description": clean_description,
        "parameters": schema,
        "script_file": py_path.name,
        "version": 1,
    }
    try:
        py_path.write_text(script_content.rstrip() + "\n", encoding="utf-8")
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        py_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        raise
    return {"name": f"dynamic_{normalized_name}", "created": True}


def discover_dynamic_tool_schemas(project_root: str | Path) -> list[dict[str, Any]]:
    """Load validated tool definitions from the dedicated dynamic-tools directory."""
    directory = _tool_directory(project_root)
    if not directory.is_dir():
        return []
    tools: list[dict[str, Any]] = []
    for metadata_path in sorted(directory.glob("*.json"))[:MAX_DYNAMIC_TOOLS]:
        try:
            if metadata_path.is_symlink() or not metadata_path.resolve().is_relative_to(directory.resolve()):
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            name = metadata.get("name")
            script_file = metadata.get("script_file")
            if not isinstance(name, str) or not TOOL_NAME_PATTERN.fullmatch(name):
                continue
            if script_file != f"{name}.py":
                continue
            script_path = directory / script_file
            if script_path.is_symlink() or not script_path.resolve().is_relative_to(directory.resolve()):
                continue
            _parse_and_validate_source(script_path.read_text(encoding="utf-8"))
            parameters = _validate_schema(metadata.get("parameters"))
            description = metadata.get("description")
            if not isinstance(description, str) or not description.strip():
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": f"dynamic_{name}",
                    "description": f"{description[:500]} Data-only helper; no filesystem, network, or shell access.",
                    "parameters": parameters,
                },
            })
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return tools


def execute_dynamic_tool(
    project_root: str | Path,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout_seconds: float = 3.0,
) -> Any:
    """Run one validated micro-tool in a short-lived process with a data-only interpreter."""
    if not isinstance(arguments, dict):
        raise ValueError("Dynamic tool input must be a JSON object.")
    normalized_name = str(tool_name).removeprefix("dynamic_")
    if not TOOL_NAME_PATTERN.fullmatch(normalized_name):
        raise ValueError("Invalid dynamic tool name.")
    directory = _tool_directory(project_root)
    script_path = (directory / f"{normalized_name}.py").resolve()
    if not script_path.is_relative_to(directory.resolve()) or script_path.is_symlink():
        raise PermissionError("Dynamic tool path must remain inside tools/dynamic.")
    source = script_path.read_text(encoding="utf-8")
    _parse_and_validate_source(source)
    payload = json.dumps({"source": source, "arguments": arguments}, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_TOOL_INPUT_BYTES:
        raise ValueError(f"Dynamic tool input is limited to {MAX_TOOL_INPUT_BYTES} bytes.")
    runner = Path(__file__).with_name("dynamic_tool_runtime.py").resolve()
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
    def apply_posix_limits() -> None:
        if os.name != "posix":
            return
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
            resource.setrlimit(resource.RLIMIT_AS, (192 * 1024 * 1024, 192 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        except (ImportError, OSError, ValueError):
            # The parent-enforced timeout and AST interpreter remain in force if
            # a platform does not expose one of these optional process limits.
            return
    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(runner)],
            cwd=directory,
            env=env,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
            preexec_fn=apply_posix_limits if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("Dynamic tool exceeded its 3-second execution limit.") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-1000:]
        raise RuntimeError(detail or "Dynamic tool execution failed.")
    if len(completed.stdout.encode("utf-8")) > MAX_TOOL_OUTPUT_BYTES:
        raise ValueError(f"Dynamic tool output is limited to {MAX_TOOL_OUTPUT_BYTES} bytes.")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Dynamic tool returned malformed output.") from error
    return result.get("result")
