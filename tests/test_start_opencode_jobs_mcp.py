import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "start_opencode_jobs_mcp.py"
SPEC = importlib.util.spec_from_file_location("start_opencode_jobs_mcp", MODULE_PATH)
starter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(starter)


class StartOpenCodeJobsMcpTests(unittest.TestCase):

    def test_is_managed_command_line_matches_only_expected_markers(self) -> None:
        self.assertTrue(
            starter._is_managed_command_line(
                "python -m scripts.codex_token_monitor_opencode_jobs_mcp"
            )
        )
        self.assertTrue(
            starter._is_managed_command_line(
                r'python "D:\repo\scripts\start_opencode_jobs_mcp.py"'
            )
        )
        self.assertFalse(starter._is_managed_command_line("python -m http.server"))

    def test_python_entrypoint_process_matches_real_module_launch(self) -> None:
        self.assertTrue(
            starter._is_python_entrypoint_process(
                "python.exe",
                "python -m scripts.codex_token_monitor_opencode_jobs_mcp",
            )
        )

    def test_python_entrypoint_process_matches_real_script_launch(self) -> None:
        self.assertTrue(
            starter._is_python_entrypoint_process(
                "python.exe",
                r'python -u "D:\repo\scripts\start_opencode_jobs_mcp.py"',
            )
        )

    def test_python_entrypoint_process_rejects_powershell_wrapper(self) -> None:
        self.assertFalse(
            starter._is_python_entrypoint_process(
                "powershell.exe",
                r'"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -Command "python scripts/start_opencode_jobs_mcp.py"',
            )
        )

    def test_python_entrypoint_process_rejects_python_c_reference(self) -> None:
        self.assertFalse(
            starter._is_python_entrypoint_process(
                "python.exe",
                r'python -c "import pathlib; pathlib.Path(\"scripts/start_opencode_jobs_mcp.py\")"',
            )
        )

    def test_classify_process_record_ignores_foreign_python_process(self) -> None:
        managed, details = starter._classify_process_record(
            {
                "pid": 100,
                "name": "python.exe",
                "command_line": "python app.py",
                "source": "process_scan",
            },
            current_pid=200,
            repo_root=starter.REPO_ROOT,
        )
        self.assertFalse(managed)
        self.assertEqual(details["reason"], "marker_missing")

    def test_classify_process_record_does_not_touch_opencode_serve(self) -> None:
        managed, details = starter._classify_process_record(
            {
                "pid": 101,
                "name": "opencode.exe",
                "command_line": "opencode serve --port 4096",
                "source": "process_scan",
            },
            current_pid=200,
            repo_root=starter.REPO_ROOT,
        )
        self.assertFalse(managed)
        self.assertEqual(details["reason"], "marker_missing")

    def test_classify_process_record_skips_different_repo_when_absolute_path_present(self) -> None:
        managed, details = starter._classify_process_record(
            {
                "pid": 102,
                "name": "python.exe",
                "command_line": r'python "D:\other\repo\scripts\start_opencode_jobs_mcp.py"',
                "source": "process_scan",
            },
            current_pid=200,
            repo_root=starter.REPO_ROOT,
        )
        self.assertFalse(managed)
        self.assertEqual(details["reason"], "different_repo")

    def test_classify_process_record_rejects_parent_powershell_wrapper(self) -> None:
        managed, details = starter._classify_process_record(
            {
                "pid": 103,
                "name": "powershell.exe",
                "command_line": r'"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -Command "python scripts/start_opencode_jobs_mcp.py"',
                "source": "process_scan",
            },
            current_pid=200,
            repo_root=starter.REPO_ROOT,
        )
        self.assertFalse(managed)
        self.assertEqual(details["reason"], "not_entrypoint_process")

    def test_build_cleanup_plan_marks_dead_pid_file_as_stale(self) -> None:
        with mock.patch.object(starter, "_is_pid_alive", return_value=False):
            kill_list, skipped, stale_pid_file = starter._build_cleanup_plan(
                current_pid=200,
                repo_root=starter.REPO_ROOT,
                pid_record={
                    "pid": 123,
                    "name": "python.exe",
                    "command_line": "python -m scripts.codex_token_monitor_opencode_jobs_mcp",
                    "source": "pid_file",
                },
                scanned_records=[],
            )
        self.assertEqual(kill_list, [])
        self.assertTrue(stale_pid_file)
        self.assertEqual(skipped[0]["reason"], "stale_pid_file")

    def test_build_cleanup_plan_deduplicates_pid_file_and_process_scan(self) -> None:
        with mock.patch.object(starter, "_is_pid_alive", return_value=True):
            kill_list, skipped, stale_pid_file = starter._build_cleanup_plan(
                current_pid=200,
                repo_root=starter.REPO_ROOT,
                pid_record={
                    "pid": 123,
                    "name": "python.exe",
                    "command_line": "python -m scripts.codex_token_monitor_opencode_jobs_mcp",
                    "source": "pid_file",
                },
                scanned_records=[
                    {
                        "pid": 123,
                        "name": "python.exe",
                        "command_line": "python -m scripts.codex_token_monitor_opencode_jobs_mcp",
                        "source": "process_scan",
                    },
                    {
                        "pid": 200,
                        "name": "python.exe",
                        "command_line": "python scripts/start_opencode_jobs_mcp.py",
                        "source": "process_scan",
                    },
                    {
                        "pid": 300,
                        "name": "powershell.exe",
                        "command_line": r'"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -Command "python scripts/start_opencode_jobs_mcp.py"',
                        "source": "process_scan",
                    },
                ],
            )
        self.assertFalse(stale_pid_file)
        self.assertEqual([item["pid"] for item in kill_list], [123])
        self.assertEqual(skipped[0]["reason"], "current_process")
        self.assertEqual(skipped[1]["reason"], "not_entrypoint_process")

    def test_parse_process_query_output_supports_single_object(self) -> None:
        parsed = starter._parse_process_query_output(
            json.dumps(
                {
                    "ProcessId": 321,
                    "ParentProcessId": 100,
                    "Name": "python.exe",
                    "CommandLine": "python scripts/start_opencode_jobs_mcp.py",
                }
            )
        )
        self.assertEqual(parsed[0]["pid"], 321)
        self.assertEqual(parsed[0]["name"], "python.exe")
        self.assertIn("start_opencode_jobs_mcp.py", parsed[0]["command_line"])

    def test_append_startup_log_writes_json_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            log_path = tmpdir / "startup.log"
            with mock.patch.object(starter, "STARTUP_LOG_PATH", log_path):
                starter._append_startup_log(
                    {
                        "started_at": "2026-01-01T00:00:00.000Z",
                        "current_pid": 111,
                        "found_pids": [1],
                        "killed_pids": [1],
                        "skipped_pids": [],
                        "errors": [],
                    }
                )
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["killed_pids"], [1])

    def test_write_pid_record_includes_cleanup_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pid_path = tmpdir / "opencode-jobs-mcp.pid.json"
            with mock.patch.object(starter, "PID_PATH", pid_path):
                with mock.patch.object(starter, "_current_command_line", return_value="python scripts/start_opencode_jobs_mcp.py"):
                    starter._write_pid_record(current_pid=555, killed_pids=[111, 222])
            payload = json.loads(pid_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], 555)
            self.assertEqual(payload["cleanup_killed_pids"], [111, 222])


if __name__ == "__main__":
    unittest.main()
