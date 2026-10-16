from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import main


class SystemPromptTests(unittest.TestCase):
    def test_saved_prompt_is_returned_and_applied_to_active_task_messages(self) -> None:
        stored: dict[str, str] = {}
        active_id = "test-system-prompt-session"
        messages = [{
            "role": "system",
            "content": (
                "Fixed instructions."
                + main.SYSTEM_PROMPT_START
                + "Old persona."
                + main.SYSTEM_PROMPT_END
                + "More fixed instructions."
            ),
        }]
        main.ACTIVE_TASK_MESSAGES[active_id] = messages

        def fake_db_one(_sql: str, _values: tuple[object, ...] = ()) -> dict[str, str] | None:
            value = stored.get("system_prompt")
            return {"value": value} if value is not None else None

        def fake_db_run(sql: str, values: tuple[object, ...] = ()) -> None:
            if sql.startswith("INSERT INTO assistant_preferences"):
                stored["system_prompt"] = str(values[0])
            elif sql.startswith("DELETE FROM assistant_preferences"):
                stored.pop("system_prompt", None)

        try:
            with patch.object(main, "db_one", side_effect=fake_db_one), patch.object(
                main, "db_run", side_effect=fake_db_run
            ):
                saved = main.save_system_prompt_config("Use a concise, collaborative voice.")

            self.assertEqual(saved["systemPrompt"], "Use a concise, collaborative voice.")
            self.assertTrue(saved["isCustomized"])
            self.assertIn(
                main.SYSTEM_PROMPT_START
                + "Use a concise, collaborative voice."
                + main.SYSTEM_PROMPT_END,
                messages[0]["content"],
            )
            self.assertTrue(messages[0]["content"].startswith("Fixed instructions."))
            self.assertTrue(messages[0]["content"].endswith("More fixed instructions."))
        finally:
            main.ACTIVE_TASK_MESSAGES.pop(active_id, None)

    def test_empty_prompt_restores_environment_or_builtin_default(self) -> None:
        stored = {"system_prompt": "Previous custom prompt"}

        def fake_db_one(_sql: str, _values: tuple[object, ...] = ()) -> dict[str, str] | None:
            value = stored.get("system_prompt")
            return {"value": value} if value is not None else None

        def fake_db_run(sql: str, _values: tuple[object, ...] = ()) -> None:
            if sql.startswith("DELETE FROM assistant_preferences"):
                stored.pop("system_prompt", None)

        with patch.dict(os.environ, {"FORGE_SYSTEM_PROMPT": "Environment persona"}), patch.object(
            main, "db_one", side_effect=fake_db_one
        ), patch.object(main, "db_run", side_effect=fake_db_run):
            result = main.save_system_prompt_config(" \n ")

        self.assertEqual(result, {"systemPrompt": "Environment persona", "isCustomized": False})
        self.assertNotIn("system_prompt", stored)
