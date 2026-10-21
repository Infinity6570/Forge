from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.dynamic_tools import (
    create_dynamic_tool,
    discover_dynamic_tool_schemas,
    execute_dynamic_tool,
)
from tools.task_dag import task_dag_layers, validate_task_dag


class DynamicToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def create_helper(self, name="double_positive_values"):
        return create_dynamic_tool(
            self.root,
            name,
            "Double positive values and return their sum.",
            {
                "type": "object",
                "properties": {"values": {"type": "array", "items": {"type": "number"}}},
                "required": ["values"],
            },
            (
                "def run(data):\n"
                "    doubled = []\n"
                "    for value in data.get('values', []):\n"
                "        if value > 0:\n"
                "            doubled.append(value * 2)\n"
                "    return {'values': doubled, 'total': sum(doubled)}\n"
            ),
        )

    def test_create_discover_and_execute_data_only_micro_tool(self):
        created = self.create_helper()
        self.assertEqual(created["name"], "dynamic_double_positive_values")
        tools = discover_dynamic_tool_schemas(self.root)
        self.assertEqual([tool["function"]["name"] for tool in tools], [created["name"]])
        result = execute_dynamic_tool(
            self.root,
            created["name"],
            {"values": [1, -2, 3]},
        )
        self.assertEqual(result, {"values": [2, 6], "total": 8})

    def test_dynamic_tools_reject_imports_dunder_access_and_replacement(self):
        with self.assertRaisesRegex(ValueError, "do not support Import"):
            create_dynamic_tool(
                self.root,
                "unsafe",
                "Must not import.",
                {"type": "object", "properties": {}},
                "import os\ndef run(data):\n    return data\n",
            )
        with self.assertRaisesRegex(ValueError, "double underscores"):
            create_dynamic_tool(
                self.root,
                "unsafe_dunder",
                "Must not inspect Python objects.",
                {"type": "object", "properties": {}},
                "def run(data):\n    return data.__class__\n",
            )
        self.create_helper()
        with self.assertRaises(FileExistsError):
            self.create_helper()

    def test_dynamic_tool_execution_budget_stops_large_loops(self):
        created = create_dynamic_tool(
            self.root,
            "large_loop",
            "Count over a bounded input array.",
            {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "integer"}}}},
            "def run(data):\n    total = 0\n    for item in data['items']:\n        total = total + item\n    return total\n",
        )
        values = list(range(10_001))
        with self.assertRaisesRegex(RuntimeError, "execution-step limit|10,000"):
            execute_dynamic_tool(self.root, created["name"], {"items": values})

    def test_dynamic_registry_ignores_corrupt_and_escaped_descriptors(self):
        directory = self.root / "tools" / "dynamic"
        directory.mkdir(parents=True)
        (directory / "broken.json").write_text("{", encoding="utf-8")
        outside = self.root / "outside.py"
        outside.write_text("def run(data):\n    return data\n", encoding="utf-8")
        (directory / "escaped.py").symlink_to(outside)
        (directory / "escaped.json").write_text(json.dumps({
            "name": "escaped",
            "description": "escape",
            "parameters": {"type": "object", "properties": {}},
            "script_file": "escaped.py",
        }), encoding="utf-8")
        self.assertEqual(discover_dynamic_tool_schemas(self.root), [])


class TaskDagTests(unittest.TestCase):
    def test_validates_dependencies_and_groups_independent_nodes(self):
        nodes = validate_task_dag([
            {"id": "literature", "task": "Search literature", "role": "research"},
            {"id": "code-audit", "task": "Audit code", "role": "coding"},
            {"id": "synthesis", "task": "Combine findings", "depends_on": ["literature", "code-audit"]},
        ])
        layers = task_dag_layers(nodes)
        self.assertEqual([[node["id"] for node in layer] for layer in layers], [
            ["literature", "code-audit"],
            ["synthesis"],
        ])

    def test_rejects_cycles_unknown_dependencies_and_excessive_nodes(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_task_dag([
                {"id": "one", "task": "One", "depends_on": ["two"]},
                {"id": "two", "task": "Two", "depends_on": ["one"]},
            ])
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_task_dag([
                {"id": "one", "task": "One", "depends_on": ["missing"]},
                {"id": "two", "task": "Two"},
            ])
        with self.assertRaisesRegex(ValueError, "between 2 and"):
            validate_task_dag([{"id": "one", "task": "Only one"}])


if __name__ == "__main__":
    unittest.main()
