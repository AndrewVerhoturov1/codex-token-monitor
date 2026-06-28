import asyncio
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]

JOBS_MODULE_PATH = ROOT / "scripts" / "codex_token_monitor_opencode_jobs.py"
JOBS_SPEC = importlib.util.spec_from_file_location("codex_token_monitor_opencode_jobs", JOBS_MODULE_PATH)
jobs = importlib.util.module_from_spec(JOBS_SPEC)
assert JOBS_SPEC.loader is not None
JOBS_SPEC.loader.exec_module(jobs)

MCP_MODULE_PATH = ROOT / "scripts" / "codex_token_monitor_opencode_jobs_mcp.py"
MCP_SPEC = importlib.util.spec_from_file_location("codex_token_monitor_opencode_jobs_mcp", MCP_MODULE_PATH)
jobs_mcp = importlib.util.module_from_spec(MCP_SPEC)
assert MCP_SPEC.loader is not None
MCP_SPEC.loader.exec_module(jobs_mcp)

FAKE_WORKER_SOURCE = r'''
import json
import sys
import time
from pathlib import Path


def _arg(name: str, default: str | None = None) -> str | None:
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            return args[i + 1]
    return default


def main() -> None:
    job_dir_arg = _arg("--job-dir")
    if not job_dir_arg:
        print("Missing --job-dir", file=sys.stderr)
        sys.exit(1)

    mode = _arg("--mode", "success")
    job_dir = Path(job_dir_arg)
    job_dir.mkdir(parents=True, exist_ok=True)

    result_text = "# Success\n\nAll good.\n"
    if mode == "long":
        result_text = "# Long\n\n" + ("line\n" * 900)

    (job_dir / "result.md").write_text(result_text, encoding="utf-8")
    time.sleep(0.05)

    status = "completed"
    reason = "completed"
    summary = "Fake worker summary"
    if mode == "blocked":
        status = "blocked"
        reason = "timed_out"
        summary = "Fake worker blocked"

    done = {
        "job_id": "fake-job",
        "status": status,
        "reason": reason,
        "summary": summary,
        "started_at": "2026-01-01T00:00:00.000Z",
        "finished_at": "2026-01-01T00:00:01.000Z",
        "duration_ms": 1000,
        "exit_code": 0,
        "timed_out": status == "blocked",
        "provider_id": "fake-provider",
        "model_id": "fake-model",
        "result_path": str(job_dir / "result.md"),
        "stdout_path": str(job_dir / "stdout.log"),
        "stderr_path": str(job_dir / "stderr.log"),
    }
    (job_dir / "done.json").write_text(
        json.dumps(done, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("ok")


if __name__ == "__main__":
    main()
'''


def _make_fake_worker(tmpdir: Path) -> Path:
    worker_path = tmpdir / "fake_worker.py"
    worker_path.write_text(FAKE_WORKER_SOURCE, encoding="utf-8")
    return worker_path


def _write_config(tmpdir: Path, worker_path: Path, *, jobs_dir: Path, mode: str = "success") -> Path:
    config = {
        "jobs_dir": str(jobs_dir),
        "timeout_seconds": 10,
        "poll_interval_ms": 50,
        "provider_id": "deepseek",
        "model_id": "deepseek-v4-flash",
        "summary_tail_lines": 80,
        "summary_max_chars": 4000,
        "command_template": [
            sys.executable,
            str(worker_path),
            "--job-dir", "{job_dir}",
            "--mode", mode,
        ],
    }
    config_path = tmpdir / "opencode_jobs_mcp_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config_path


def _make_job_result(*, status: str = "completed", reason: str = "completed", summary: str = "Short summary") -> jobs.JobResult:
    result_dir = ROOT / "_local" / "tests" / "job-result"
    return jobs.JobResult(
        job_id="job-123",
        status=status,
        reason=reason,
        summary=summary,
        started_at="2026-01-01T00:00:00.000Z",
        finished_at="2026-01-01T00:00:01.000Z",
        duration_ms=1000,
        exit_code=0,
        timed_out=status == "blocked",
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        result_path=str(result_dir / "result.md"),
        stdout_path=str(result_dir / "stdout.log"),
        stderr_path=str(result_dir / "stderr.log"),
        launch_path=str(result_dir / "opencode_launch.json"),
        debug_visible_terminal_requested=True,
        debug_visible_terminal_status="adapter_started_not_confirmed",
        debug_visible_terminal_reason="Visible terminal launch is not machine-confirmed.",
        debug_visible_terminal_pid=4242,
        debug_open_session_tui_requested=True,
        debug_open_session_tui_status="launched_not_confirmed",
        debug_open_session_tui_reason="TUI launch is not machine-confirmed.",
        debug_session_id="ses_123",
        debug_tui_command="wt.exe new-tab ...",
        debug_attach_url="http://localhost:4096",
        export_session_mode="on_failure",
        export_session_status="exported",
        export_session_reason="",
        session_export_path=str(result_dir / "opencode_session_export.json"),
        session_transcript_path=str(result_dir / "opencode_session_transcript.md"),
    )


class OpenCodeJobsMcpAdapterTests(unittest.TestCase):

    def test_legacy_entrypoint_redirects_to_starter(self) -> None:
        with mock.patch.dict(jobs_mcp.os.environ, {}, clear=True):
            with mock.patch.object(jobs_mcp.os, "execve") as execve:
                jobs_mcp._ensure_started_via_starter()

        execve.assert_called_once()
        executable, argv, env = execve.call_args.args
        self.assertEqual(executable, sys.executable)
        self.assertEqual(argv, [sys.executable, str(jobs_mcp.STARTER_PATH)])
        self.assertEqual(env[jobs_mcp.STARTER_ENV], "1")

    def test_legacy_entrypoint_skips_redirect_when_started_via_starter(self) -> None:
        with mock.patch.dict(jobs_mcp.os.environ, {jobs_mcp.STARTER_ENV: "1"}, clear=True):
            with mock.patch.object(jobs_mcp.os, "execve") as execve:
                jobs_mcp._ensure_started_via_starter()
        execve.assert_not_called()

    def test_job_result_to_mcp_response_returns_expected_fields(self) -> None:
        response = jobs_mcp.job_result_to_mcp_response(_make_job_result())
        self.assertEqual(
            set(response.keys()),
            {
                "job_id",
                "status",
                "reason",
                "summary",
                "duration_ms",
                "timed_out",
                "result_path",
                "done_path",
                "stdout_path",
                "stderr_path",
                "launch_path",
                "debug_visible_terminal_requested",
                "debug_visible_terminal_status",
                "debug_visible_terminal_reason",
                "debug_visible_terminal_pid",
                "debug_open_session_tui_requested",
                "debug_open_session_tui_status",
                "debug_open_session_tui_reason",
                "debug_session_id",
                "debug_tui_command",
                "debug_attach_url",
                "export_session_mode",
                "export_session_status",
                "export_session_reason",
                "session_export_path",
                "session_transcript_path",
                "route_c_profile",
                "route_c_profile_account_id",
                "route_c_profile_account_index",
            },
        )
        self.assertTrue(response["done_path"].endswith("done.json"))
        self.assertTrue(response["launch_path"].endswith("opencode_launch.json"))
        self.assertEqual(response["debug_open_session_tui_status"], "launched_not_confirmed")
        self.assertTrue(response["session_export_path"].endswith("opencode_session_export.json"))

    def test_job_result_to_mcp_response_truncates_long_summary(self) -> None:
        long_summary = "X" * (jobs_mcp.MCP_SUMMARY_MAX_CHARS + 200)
        response = jobs_mcp.job_result_to_mcp_response(_make_job_result(summary=long_summary))
        self.assertLessEqual(len(response["summary"]), jobs_mcp.MCP_SUMMARY_MAX_CHARS + 3)
        self.assertTrue(response["summary"].endswith("..."))
        self.assertNotEqual(response["summary"], long_summary)

    def test_impl_calls_core_wrapper(self) -> None:
        fake_config = jobs.JobConfig()
        fake_result = _make_job_result()
        with mock.patch.object(jobs_mcp.jobs, "load_config", return_value=fake_config) as load_config:
            with mock.patch.object(jobs_mcp.jobs, "run_opencode_job", return_value=fake_result) as run_job:
                response = jobs_mcp.opencode_job_run_and_wait_impl(
                    task_text="Run test",
                    directory=".",
                    timeout_seconds="45",
                    provider_id="deepseek",
                    model_id="deepseek-v4-flash",
                    debug_visible_terminal="true",
                    debug_open_session_tui="true",
                    opencode_attach_url="http://localhost:4096",
                    export_session="always",
                    config_path="config/opencode_job_defaults.json",
                )

        load_config.assert_called_once_with(ROOT / "config" / "opencode_job_defaults.json")
        run_job.assert_called_once()
        kwargs = run_job.call_args.kwargs
        self.assertEqual(kwargs["directory"], str(ROOT))
        self.assertEqual(kwargs["config"].timeout_seconds, 45)
        self.assertEqual(kwargs["config"].provider_id, "deepseek")
        self.assertEqual(kwargs["config"].model_id, "deepseek-v4-flash")
        self.assertTrue(kwargs["config"].debug_visible_terminal)
        self.assertTrue(kwargs["config"].debug_open_session_tui)
        self.assertEqual(kwargs["config"].opencode_attach_url, "http://localhost:4096")
        self.assertEqual(kwargs["config"].export_session, "always")
        self.assertEqual(kwargs["config_root"], ROOT / "config")
        self.assertEqual(response["job_id"], "job-123")

    def test_impl_preserves_config_visible_terminal_when_not_passed(self) -> None:
        fake_result = _make_job_result()
        with mock.patch.object(jobs_mcp.jobs, "load_config", return_value=jobs.JobConfig(debug_visible_terminal=False)):
            with mock.patch.object(jobs_mcp.jobs, "run_opencode_job", return_value=fake_result) as run_job:
                jobs_mcp.opencode_job_run_and_wait_impl(task_text="Run test")

        kwargs = run_job.call_args.kwargs
        self.assertFalse(kwargs["config"].debug_visible_terminal)

    def test_impl_allows_explicit_visible_terminal_off(self) -> None:
        fake_result = _make_job_result()
        with mock.patch.object(jobs_mcp.jobs, "load_config", return_value=jobs.JobConfig(debug_visible_terminal=True)):
            with mock.patch.object(jobs_mcp.jobs, "run_opencode_job", return_value=fake_result) as run_job:
                jobs_mcp.opencode_job_run_and_wait_impl(
                    task_text="Run test",
                    debug_visible_terminal=False,
                )

        kwargs = run_job.call_args.kwargs
        self.assertFalse(kwargs["config"].debug_visible_terminal)

    def test_impl_preserves_blocked_result(self) -> None:
        blocked = _make_job_result(status="blocked", reason="timed_out", summary="Blocked summary")
        with mock.patch.object(jobs_mcp.jobs, "load_config", return_value=jobs.JobConfig()):
            with mock.patch.object(jobs_mcp.jobs, "run_opencode_job", return_value=blocked):
                response = jobs_mcp.opencode_job_run_and_wait_impl(task_text="Run test")
        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["reason"], "timed_out")
        self.assertTrue(response["timed_out"])

    def test_impl_preserves_explicit_visible_terminal_true(self) -> None:
        fake_result = _make_job_result()
        with mock.patch.object(jobs_mcp.jobs, "load_config", return_value=jobs.JobConfig(debug_visible_terminal=False)):
            with mock.patch.object(jobs_mcp.jobs, "run_opencode_job", return_value=fake_result) as run_job:
                jobs_mcp.opencode_job_run_and_wait_impl(
                    task_text="Run test",
                    debug_visible_terminal=True,
                )

        kwargs = run_job.call_args.kwargs
        self.assertTrue(kwargs["config"].debug_visible_terminal)

    def test_impl_handles_unknown_input_without_crashing(self) -> None:
        fake_result = _make_job_result()
        with mock.patch.object(jobs_mcp.jobs, "load_config", return_value=jobs.JobConfig()):
            with mock.patch.object(jobs_mcp.jobs, "run_opencode_job", return_value=fake_result):
                response = jobs_mcp.opencode_job_run_and_wait_impl(
                    task_text="Run test",
                    timeout_seconds="not-an-int",
                    provider_id={"provider": "deepseek"},
                    model_id=["deepseek-v4-flash"],
                    config_path=None,
                )
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["job_id"], "job-123")

    def test_impl_rejects_missing_directory(self) -> None:
        missing = ROOT / "missing-directory-for-mcp-test"
        response = jobs_mcp.opencode_job_run_and_wait_impl(
            task_text="Run test",
            directory=str(missing),
        )
        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["reason"], "invalid_directory")
        self.assertEqual(response["debug_visible_terminal_status"], "not_requested")


class OpenCodeJobsMcpIntegrationTests(unittest.TestCase):

    async def _call_tool(self, arguments: dict) -> dict:
        async with Client(jobs_mcp.mcp) as client:
            result = await client.call_tool(jobs_mcp.TOOL_NAME, arguments)
        return result.data

    def test_mcp_tool_smoke_with_fake_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker_path = _make_fake_worker(tmpdir)
            jobs_dir = tmpdir / "jobs"
            config_path = _write_config(tmpdir, worker_path, jobs_dir=jobs_dir, mode="long")

            response = asyncio.run(
                self._call_tool(
                    {
                        "task_text": "Return a short validation line only.",
                        "config_path": str(config_path),
                        "directory": str(ROOT),
                    }
                )
            )

            self.assertEqual(response["status"], "completed")
            self.assertTrue(response["job_id"])
            self.assertTrue(response["summary"])
            self.assertTrue(response["result_path"])
            self.assertTrue(response["done_path"])
            self.assertTrue(response["stdout_path"])
            self.assertTrue(response["stderr_path"])
            self.assertLessEqual(len(response["summary"]), jobs_mcp.MCP_SUMMARY_MAX_CHARS + 3)

            result_path = Path(response["result_path"])
            done_path = Path(response["done_path"])
            self.assertTrue(result_path.exists())
            self.assertTrue(done_path.exists())
            self.assertEqual(result_path.parent.parent, jobs_dir)
            self.assertLessEqual(result_path.stat().st_mtime_ns, done_path.stat().st_mtime_ns)

            result_text = result_path.read_text(encoding="utf-8")
            self.assertGreater(len(result_text), len(response["summary"]))

    def test_mcp_tool_is_registered(self) -> None:
        async def run() -> None:
            async with Client(jobs_mcp.mcp) as client:
                tools = await client.list_tools()
            expected = {
                jobs_mcp.TOOL_NAME,
                "opencode_zworker_prompt_pack",
                "opencode_zworker_result_unpack",
                "opencode_zworker_process_result",
                "opencode_zworker_revision_prompt",
            }
            self.assertEqual({tool.name for tool in tools}, expected)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
