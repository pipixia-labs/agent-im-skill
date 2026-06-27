from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "agent_im_contacts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("agent_im_contacts", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentImContactsTests(unittest.TestCase):
    def run_cli(
        self,
        args: list[str],
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=check,
        )

    def test_resolve_home_prefers_explicit_and_env(self) -> None:
        module = load_module()

        self.assertEqual(
            module.resolve_home("/tmp/custom-agent-im", env={}, platform_name="linux"),
            Path("/tmp/custom-agent-im"),
        )
        self.assertEqual(
            module.resolve_home(
                env={"AGENT_IM_HOME": "/tmp/from-env"},
                platform_name="darwin",
            ),
            Path("/tmp/from-env"),
        )

    def test_resolve_home_supports_windows_local_app_data(self) -> None:
        module = load_module()

        home = module.resolve_home(
            env={"LOCALAPPDATA": r"C:\Users\agent\AppData\Local"},
            platform_name="win32",
        )

        self.assertIn("agent-im-skill", str(home))
        self.assertIn("AppData", str(home))

    def test_workspace_local_init_creates_deny_all_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)

            result = self.run_cli(["init", "--workspace-local"], cwd=cwd)

            payload = json.loads(result.stdout)
            self.assertTrue(payload["workspace_local"])
            self.assertEqual(
                (cwd / ".agent-im" / ".gitignore").read_text(encoding="utf-8"),
                "*\n!.gitignore\n",
            )

    def test_local_identity_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "state"

            self.run_cli(["init", "--home", str(home)])
            self.run_cli(
                [
                    "set-local",
                    "--home",
                    str(home),
                    "--agent-id",
                    "a_agent",
                    "--email",
                    "a_agent@example.invalid",
                    "--display-name",
                    "A Agent",
                ]
            )

            result = self.run_cli(["show-local", "--home", str(home)])
            payload = json.loads(result.stdout)

            self.assertEqual(payload["agent_id"], "a_agent")
            self.assertEqual(payload["email"], "a_agent@example.invalid")

    def test_checkpoint_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "state"

            self.run_cli(["init", "--home", str(home)])
            self.run_cli(
                [
                    "set-checkpoint",
                    "--home",
                    str(home),
                    "--name",
                    "inbox",
                    "--timestamp",
                    "2026-06-27T00:00:00+00:00",
                    "--cursor",
                    "cursor_secret",
                    "--message-id",
                    "msg_checkpoint",
                ]
            )

            result = self.run_cli(["get-checkpoint", "--home", str(home), "--name", "inbox"])
            payload = json.loads(result.stdout)

            self.assertEqual(payload["name"], "inbox")
            self.assertEqual(payload["cursor"], "cursor_secret")
            self.assertEqual(payload["message_id"], "msg_checkpoint")

    def test_can_auto_send_allows_manual_direct_peer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "state"

            self.run_cli(["init", "--home", str(home)])
            self.run_cli(
                [
                    "upsert-agent",
                    "--home",
                    str(home),
                    "--agent-id",
                    "b_agent",
                    "--email",
                    "b_agent@example.invalid",
                    "--trust",
                    "manual",
                ]
            )

            result = self.run_cli(
                ["can-auto-send", "--home", str(home), "--peer-agent-id", "b_agent"]
            )
            payload = json.loads(result.stdout)

            self.assertTrue(payload["allowed"])
            self.assertEqual(payload["mode"], "auto")

    def test_can_auto_send_escalates_high_risk_or_observed_peer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "state"

            self.run_cli(["init", "--home", str(home)])
            self.run_cli(
                [
                    "upsert-agent",
                    "--home",
                    str(home),
                    "--agent-id",
                    "b_agent",
                    "--email",
                    "b_agent@example.invalid",
                    "--trust",
                    "observed",
                ]
            )

            result = self.run_cli(
                [
                    "can-auto-send",
                    "--home",
                    str(home),
                    "--peer-agent-id",
                    "b_agent",
                    "--has-attachment",
                ],
                check=False,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            self.assertFalse(payload["allowed"])
            self.assertEqual(payload["mode"], "escalate")
            self.assertGreaterEqual(len(payload["reasons"]), 2)

    def test_peer_message_refs_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "state"

            self.run_cli(["init", "--home", str(home)])
            self.run_cli(
                [
                    "upsert-agent",
                    "--home",
                    str(home),
                    "--agent-id",
                    "b_agent",
                    "--email",
                    "b_agent@example.invalid",
                    "--trust",
                    "manual",
                ]
            )
            self.run_cli(
                [
                    "upsert-agent",
                    "--home",
                    str(home),
                    "--agent-id",
                    "c_agent",
                    "--email",
                    "c_agent@example.invalid",
                    "--trust",
                    "manual",
                ]
            )
            self.run_cli(
                [
                    "record-message",
                    "--home",
                    str(home),
                    "--peer-agent-id",
                    "b_agent",
                    "--direction",
                    "inbound",
                    "--message-id",
                    "msg_b",
                    "--conversation-id",
                    "conv_a_b",
                    "--timestamp",
                    "2026-06-27T00:00:00+00:00",
                ]
            )
            self.run_cli(
                [
                    "record-message",
                    "--home",
                    str(home),
                    "--peer-agent-id",
                    "c_agent",
                    "--direction",
                    "inbound",
                    "--message-id",
                    "msg_c",
                    "--conversation-id",
                    "conv_a_c",
                    "--timestamp",
                    "2026-06-27T00:01:00+00:00",
                ]
            )

            b_result = self.run_cli(
                ["list-peer", "--home", str(home), "--peer-agent-id", "b_agent"]
            )
            b_state = json.loads(b_result.stdout)

            self.assertEqual(b_state["peer_agent_id"], "b_agent")
            self.assertEqual(len(b_state["messages"]), 1)
            self.assertEqual(b_state["messages"][0]["message_id"], "msg_b")
            self.assertNotIn("msg_c", b_result.stdout)

    def test_redacted_export_removes_emails_and_message_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "state"

            self.run_cli(["init", "--home", str(home)])
            self.run_cli(
                [
                    "set-local",
                    "--home",
                    str(home),
                    "--agent-id",
                    "a_agent",
                    "--email",
                    "a_agent@example.invalid",
                ]
            )
            self.run_cli(
                [
                    "upsert-agent",
                    "--home",
                    str(home),
                    "--agent-id",
                    "b_agent",
                    "--email",
                    "b_agent@example.invalid",
                    "--trust",
                    "manual",
                ]
            )
            self.run_cli(
                [
                    "record-message",
                    "--home",
                    str(home),
                    "--peer-agent-id",
                    "b_agent",
                    "--direction",
                    "outbound",
                    "--message-id",
                    "msg_secret",
                    "--conversation-id",
                    "conv_secret",
                ]
            )
            self.run_cli(
                [
                    "set-checkpoint",
                    "--home",
                    str(home),
                    "--name",
                    "inbox",
                    "--cursor",
                    "cursor_secret",
                    "--message-id",
                    "msg_checkpoint",
                ]
            )

            result = self.run_cli(["export-redacted", "--home", str(home)])
            payload = json.loads(result.stdout)

            self.assertNotIn("a_agent@example.invalid", result.stdout)
            self.assertNotIn("b_agent@example.invalid", result.stdout)
            self.assertNotIn("msg_secret", result.stdout)
            self.assertNotIn("conv_secret", result.stdout)
            self.assertNotIn("cursor_secret", result.stdout)
            self.assertNotIn("msg_checkpoint", result.stdout)
            self.assertEqual(payload["local"]["email"], "email_1@example.invalid")
            self.assertEqual(payload["agents"]["b_agent"]["email"], "email_2@example.invalid")
            self.assertEqual(
                payload["direct"]["b_agent"]["messages"][0]["message_id"],
                "msg_redacted_1",
            )

    def test_skill_package_does_not_depend_on_agently_mail_skill(self) -> None:
        forbidden = "agently" + "-mail"
        for path in SKILL_ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".py", ".json"}:
                self.assertNotIn(forbidden, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
