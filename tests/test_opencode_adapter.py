import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_token_monitor_opencode_adapter.py"
SPEC = importlib.util.spec_from_file_location("codex_token_monitor_opencode_adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)


class OpenCodeAdapterTests(unittest.TestCase):

    def test_should_export_session_respects_mode(self) -> None:
        self.assertFalse(
            adapter._should_export_session(
                "off",
                status="failed",
                timed_out=False,
                debug_visible_terminal=True,
            )
        )
        self.assertTrue(
            adapter._should_export_session(
                "on_failure",
                status="blocked",
                timed_out=True,
                debug_visible_terminal=False,
            )
        )
        self.assertFalse(
            adapter._should_export_session(
                "on_failure",
                status="completed",
                timed_out=False,
                debug_visible_terminal=False,
            )
        )
        self.assertTrue(
            adapter._should_export_session(
                "on_debug",
                status="completed",
                timed_out=False,
                debug_visible_terminal=True,
            )
        )
        self.assertTrue(
            adapter._should_export_session(
                "always",
                status="completed",
                timed_out=False,
                debug_visible_terminal=False,
            )
        )

    def test_build_opencode_command_includes_directory_and_title(self) -> None:
        command = adapter._build_opencode_command(
            opencode_command=r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
            provider_id="deepseek",
            model_id="deepseek-v4-flash",
            directory=r"D:\workspace\repo",
            opencode_input_path=Path(r"D:\jobs\job-1\opencode_input.md"),
            job_title="codex-job-123",
            attach_url=None,
        )
        self.assertEqual(
            command,
            [
                r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                "run",
                "--model",
                "deepseek/deepseek-v4-flash",
                "--file",
                r"D:\jobs\job-1\opencode_input.md",
                "--title",
                "codex-job-123",
                "--dir",
                r"D:\workspace\repo",
                "Read the attached task file and follow its instructions exactly.",
            ],
        )

    def test_build_opencode_command_includes_attach_url_when_provided(self) -> None:
        command = adapter._build_opencode_command(
            opencode_command=r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
            provider_id="opencode",
            model_id="deepseek-v4-flash-free",
            directory=r"D:\workspace\repo",
            opencode_input_path=Path(r"D:\jobs\job-1\opencode_input.md"),
            job_title="codex-job-123",
            attach_url="http://localhost:4096",
        )
        self.assertIn("--attach", command)
        self.assertIn("http://localhost:4096", command)

    def test_resolve_opencode_command_prefers_windows_cmd_shim(self) -> None:
        with mock.patch.object(adapter.sys, "platform", "win32"):
            with mock.patch.object(adapter.shutil, "which") as which:
                which.side_effect = lambda name: {
                    "opencode.cmd": r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                    "opencode.exe": None,
                    "opencode": r"C:\Users\andre\AppData\Roaming\npm\opencode",
                }.get(name)
                command, found_by = adapter._resolve_opencode_command()
        self.assertEqual(command, r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd")
        self.assertEqual(found_by, "which:opencode.cmd")

    def test_format_manual_powershell_command_uses_input_file(self) -> None:
        command = adapter._format_manual_powershell_command(
            opencode_input_path=Path(r"D:\jobs\job-1\opencode_input.md"),
            command_tokens=[
                r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                "run",
                "--model",
                "deepseek/deepseek-v4-flash",
                "--file",
                r"D:\jobs\job-1\opencode_input.md",
                "--dir",
                r"D:\workspace\repo",
                "Read the attached task file and follow its instructions exactly.",
            ],
        )
        self.assertIn("opencode_input.md", command)
        self.assertIn("--file", command)
        self.assertIn("--dir", command)
        self.assertIn(r"D:\workspace\repo", command)

    def test_find_session_id_by_title_filters_by_directory(self) -> None:
        sessions_json = json.dumps(
            [
                {
                    "id": "ses_other",
                    "title": "codex-job-123",
                    "directory": r"D:\other",
                },
                {
                    "id": "ses_target",
                    "title": "codex-job-123",
                    "directory": r"D:\workspace\repo",
                },
            ]
        )
        session_id = adapter._find_session_id_by_title(
            sessions_json,
            title="codex-job-123",
            directory=r"D:\workspace\repo",
        )
        self.assertEqual(session_id, "ses_target")

    def test_build_session_tui_command_prefers_attach_mode_when_url_is_set(self) -> None:
        command = adapter._build_session_tui_command(
            opencode_command=r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
            session_id="ses_123",
            directory=r"D:\workspace\repo",
            attach_url="http://localhost:4096",
        )
        self.assertEqual(
            command,
            [
                r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                "attach",
                "http://localhost:4096",
                "--session",
                "ses_123",
                "--dir",
                r"D:\workspace\repo",
            ],
        )

    def test_build_session_tui_command_uses_local_session(self) -> None:
        command = adapter._build_session_tui_command(
            opencode_command=r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
            session_id="ses_123",
            directory=r"D:\workspace\repo",
            attach_url=None,
        )
        self.assertEqual(
            command,
            [
                r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                r"D:\workspace\repo",
                "--session",
                "ses_123",
            ],
        )

    def test_build_terminal_open_command_prefers_windows_terminal_when_available(self) -> None:
        with mock.patch.object(adapter.shutil, "which", return_value=r"C:\Windows\System32\wt.exe"):
            command, launcher = adapter._build_terminal_open_command(
                command_tokens=[
                    r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                    "attach",
                    "http://localhost:4096",
                ],
                window_title="codex-job-123",
            )
        self.assertEqual(launcher, "wt.exe")
        self.assertEqual(command[0], r"C:\Windows\System32\wt.exe")
        self.assertIn("new-tab", command)
        self.assertIn("--title", command)
        self.assertIn("codex-job-123", command)

    def test_build_terminal_open_command_falls_back_to_powershell(self) -> None:
        with mock.patch.object(adapter.shutil, "which", return_value=None):
            command, launcher = adapter._build_terminal_open_command(
                command_tokens=[
                    r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                    "attach",
                    "http://localhost:4096",
                ],
                window_title="codex-job-123",
            )
        self.assertEqual(launcher, "powershell.exe")
        self.assertEqual(command[0], "powershell.exe")
        self.assertIn("-NoExit", command)

    def test_write_launch_artifacts_writes_manual_command_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            adapter._write_launch_artifacts(
                job_dir=job_dir,
                opencode_input="task body",
                command_tokens=[
                    r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                    "run",
                    "--model",
                    "deepseek/deepseek-v4-flash",
                ],
                launch_payload={
                    "provider_id": "deepseek",
                    "model_id": "deepseek-v4-flash",
                    "working_directory": r"D:\workspace\repo",
                    "debug_visible_terminal": True,
                    "opencode_resolved_command": r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                    "opencode_found_by": "which:opencode.cmd",
                    "path_env": "PATH_VALUE",
                    "cwd": r"D:\Codex+opencode_new\Proect_C_O\codex-token-monitor",
                    "opencode_run_title": "codex-job-123",
                    "session_lookup_attempted": True,
                    "session_id_found": True,
                    "session_id": "ses_123",
                    "tui_open_attempted": True,
                    "tui_open_command": "wt.exe ...",
                    "tui_open_error": "",
                    "attach_url": "http://localhost:4096",
                },
            )
            self.assertTrue((job_dir / "opencode_input.md").exists())
            self.assertTrue((job_dir / "opencode_manual_command.txt").exists())
            self.assertTrue((job_dir / "opencode_launch.json").exists())
            launch = json.loads((job_dir / "opencode_launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch["opencode_resolved_command"], r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd")
            self.assertEqual(launch["opencode_found_by"], "which:opencode.cmd")
            self.assertEqual(launch["path_env"], "PATH_VALUE")
            self.assertEqual(launch["opencode_run_title"], "codex-job-123")
            self.assertTrue(launch["session_lookup_attempted"])
            self.assertTrue(launch["session_id_found"])
            self.assertEqual(launch["session_id"], "ses_123")
            self.assertTrue(launch["tui_open_attempted"])
            self.assertEqual(launch["attach_url"], "http://localhost:4096")

    def test_maybe_export_session_writes_artifacts_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            adapter._atomic_write_json(
                job_dir / "opencode_launch.json",
                {
                    "session_id": "ses_123",
                    "export_session": "on_failure",
                },
            )
            proc = mock.Mock(returncode=0, stdout=json.dumps({"messages": [{"role": "assistant", "content": [{"text": "done"}]}]}), stderr="")
            with mock.patch.object(adapter.subprocess, "run", return_value=proc):
                adapter._maybe_export_session(
                    job_dir=job_dir,
                    opencode_command="opencode",
                    export_mode="on_failure",
                    debug_visible_terminal=False,
                    job_title=None,
                    directory=None,
                    status="failed",
                    timed_out=False,
                )

            launch = json.loads((job_dir / "opencode_launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch["export_session_status"], "exported")
            self.assertTrue((job_dir / "opencode_session_export.json").exists())
            self.assertTrue((job_dir / "opencode_session_transcript.md").exists())

    def test_maybe_export_session_failure_does_not_raise_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            adapter._atomic_write_json(
                job_dir / "opencode_launch.json",
                {
                    "session_id": "ses_123",
                    "export_session": "on_failure",
                },
            )
            proc = mock.Mock(returncode=1, stdout="", stderr="export failed")
            with mock.patch.object(adapter.subprocess, "run", return_value=proc):
                adapter._maybe_export_session(
                    job_dir=job_dir,
                    opencode_command="opencode",
                    export_mode="on_failure",
                    debug_visible_terminal=False,
                    job_title=None,
                    directory=None,
                    status="failed",
                    timed_out=False,
                )

            launch = json.loads((job_dir / "opencode_launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch["export_session_status"], "export_failed")
            self.assertIn("export failed", launch["export_session_reason"])
            self.assertFalse((job_dir / "opencode_session_export.json").exists())


if __name__ == "__main__":
    unittest.main()
