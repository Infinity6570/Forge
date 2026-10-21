"""Validation and layering helpers for bounded specialist task DAGs."""

from __future__ import annotations

import re
from typing import Any

NODE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MAX_NODES = 8
MAX_DEPENDENCIES = 8
VALID_ROLES = {"general", "coding", "research", "analysis"}
VALID_TIERS = {"fast", "balanced", "reasoning"}


def validate_task_dag(raw_nodes: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_nodes, list) or not 2 <= len(raw_nodes) <= MAX_NODES:
        raise ValueError(f"A task DAG must contain between 2 and {MAX_NODES} nodes.")
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise ValueError("Every DAG node must be an object.")
        node_id = raw.get("id")
        task = raw.get("task")
        if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id) or node_id in seen:
            raise ValueError("DAG node IDs must be unique lowercase identifiers.")
        if not isinstance(task, str) or not task.strip() or len(task) > 3_000:
            raise ValueError(f"DAG node '{node_id}' needs a task description up to 3,000 characters.")
        role = raw.get("role", "general")
        tier = raw.get("tier", "fast")
        dependencies = raw.get("depends_on", [])
        if role not in VALID_ROLES or tier not in VALID_TIERS:
            raise ValueError(f"DAG node '{node_id}' has an unsupported role or tier.")
        if (
            not isinstance(dependencies, list)
            or len(dependencies) > MAX_DEPENDENCIES
            or any(not isinstance(value, str) or not NODE_ID.fullmatch(value) for value in dependencies)
            or len(set(dependencies)) != len(dependencies)
            or node_id in dependencies
        ):
            raise ValueError(f"DAG node '{node_id}' has invalid dependencies.")
        nodes.append({
            "id": node_id,
            "title": str(raw.get("title", node_id.replace("-", " ").replace("_", " ")))[:120],
            "task": task.strip(),
            "role": role,
            "tier": tier,
            "depends_on": dependencies,
            "allow_workspace_write": raw.get("allow_workspace_write") is True,
            "allow_terminal_execution": raw.get("allow_terminal_execution") is True,
        })
        seen.add(node_id)

    node_ids = {node["id"] for node in nodes}
    for node in nodes:
        unknown = set(node["depends_on"]) - node_ids
        if unknown:
            raise ValueError(f"DAG node '{node['id']}' depends on unknown node(s): {', '.join(sorted(unknown))}.")

    # Validate acyclicity while preserving input order within each ready layer.
    remaining = {node["id"]: set(node["depends_on"]) for node in nodes}
    emitted: set[str] = set()
    while remaining:
        ready = [node_id for node_id in remaining if remaining[node_id] <= emitted]
        if not ready:
            raise ValueError("Task DAG contains a dependency cycle.")
        emitted.update(ready)
        for node_id in ready:
            remaining.pop(node_id)
    return nodes


def task_dag_layers(nodes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    remaining = {node["id"]: node for node in nodes}
    completed: set[str] = set()
    layers: list[list[dict[str, Any]]] = []
    while remaining:
        ready = [
            node for node in remaining.values()
            if set(node["depends_on"]) <= completed
        ]
        if not ready:
            raise ValueError("Task DAG contains a dependency cycle.")
        layers.append(ready)
        completed.update(node["id"] for node in ready)
        for node in ready:
            remaining.pop(node["id"])
    return layers
