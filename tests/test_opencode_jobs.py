import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_token_monitor_opencode_jobs.py"
SPEC = importlib.util.spec_from_file_location("codex_token_monitor_opencode_jobs", MODULE_PATH)
jobs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(jobs)

FAKE_WORKER_SOURCE = r'''
import json
import sys
import time
from pathlib import Path


def _write_done(job_dir: Path, status: str = "completed") -> None:
    done = {
        "job_id": "test",
        "status": status,
        "reason": "completed" if status == "completed" else "partial",
        "summary": "Fake worker result",
        "started_at": "2025-01-01T00:00:00.000Z",
        "finished_at": "2025-01-01T00:01:00.000Z",
        "duration_ms": 60000,
        "exit_code": 0,
        "timed_out": False,
        "provider_id": "test",
        "model_id": "test-model",
        "result_path": str(job_dir / "result.md"),
        "stdout_path": str(job_dir / "stdout.log"),
        "stderr_path": str(job_dir / "stderr.log"),
    }
    (job_dir / "done.json").write_text(
        json.dumps(done, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_result(job_dir: Path, text: str = "# Success\n\nAll good.\n") -> None:
    (job_dir / "result.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = sys.argv[1:]
    job_dir = None
    mode = "success"
    sleep_sec = 0.5
    for i, arg in enumerate(args):
        if arg == "--job-dir" and i + 1 < len(args):
            job_dir = Path(args[i + 1])
        elif arg == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
        elif arg == "--sleep" and i + 1 < len(args):
            sleep_sec = float(args[i + 1])
    if job_dir is None:
        print("Missing --job-dir", file=sys.stderr)
        sys.exit(1)
    job_dir.mkdir(parents=True, exist_ok=True)

    if mode == "success":
        time.sleep(sleep_sec)
        _write_result(job_dir)
        time.sleep(0.05)
        _write_done(job_dir)
        print("ok")
    elif mode == "protocol_violation":
        _write_done(job_dir)
        sys.stdout.flush()
        time.sleep(sleep_sec)
        _write_result(job_dir)
        print("should-not-reach")
    elif mode == "fast_protocol_violation":
        _write_done(job_dir)
        sys.stdout.flush()
    elif mode == "exit_without_done":
        time.sleep(sleep_sec)
        print("done-no-done")
    elif mode == "done_then_sleep":
        time.sleep(sleep_sec)
        _write_result(job_dir)
        time.sleep(0.05)
        _write_done(job_dir)
        time.sleep(9999)
        print("never-here")
    elif mode == "timeout":
        time.sleep(9999)
        print("never-here")


if __name__ == "__main__":
    main()
'''


def _make_fake_worker(tmpdir: Path) -> Path:
    path = tmpdir / "fake_worker.py"
    path.write_text(FAKE_WORKER_SOURCE, encoding="utf-8")
    return path


def _run_job(tmpdir: Path, worker_path: Path, mode: str, config_overrides: dict | None = None) -> jobs.JobResult:
    jobs_dir = tmpdir / "jobs"
    cfg = jobs.JobConfig(
        jobs_dir=str(jobs_dir),
        timeout_seconds=10,
        poll_interval_ms=100,
        provider_id="test",
        model_id="test-model",
        summary_tail_lines=80,
        summary_max_chars=4000,
        command_template=[
            sys.executable, str(worker_path),
            "--job-dir", "{job_dir}",
            "--mode", mode,
            "--sleep", "0.05",
        ],
    )
    if config_overrides:
        for k, v in config_overrides.items():
            setattr(cfg, k, v)
    return jobs.run_opencode_job("test task", config=cfg)


class OpenCodeJobsCoreTests(unittest.TestCase):

    def test_job_config_default_timeout_is_180_seconds(self) -> None:
        self.assertEqual(jobs.JobConfig().timeout_seconds, 180)

    def test_build_adapter_command_includes_logs_directory_and_debug_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            cfg = jobs.JobConfig(
                debug_visible_terminal=True,
                debug_open_session_tui=True,
                opencode_attach_url="http://localhost:4096",
                opencode_command=r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                export_session="always",
            )
            command = jobs._build_adapter_command(
                cfg,
                task_file=tmpdir / "task.md",
                job_dir=tmpdir / "job-dir",
                provider_id="deepseek",
                model_id="deepseek-v4-flash",
                stdout_path=tmpdir / "stdout.log",
                stderr_path=tmpdir / "stderr.log",
                directory=str(tmpdir / "workspace"),
            )
            self.assertIn("--stdout-log", command)
            self.assertIn(str(tmpdir / "stdout.log"), command)
            self.assertIn("--stderr-log", command)
            self.assertIn(str(tmpdir / "stderr.log"), command)
            self.assertIn("--directory", command)
            self.assertIn(str(tmpdir / "workspace"), command)
            self.assertIn("--opencode-command", command)
            self.assertIn(r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd", command)
            self.assertIn("--debug-visible-terminal", command)
            self.assertIn("--debug-open-session-tui", command)
            self.assertIn("--opencode-attach-url", command)
            self.assertIn("http://localhost:4096", command)
            self.assertIn("--export-session", command)
            self.assertIn("always", command)
            self.assertEqual(command[0], sys.executable)
            self.assertEqual(command[1], str(jobs.REPO_ROOT / "scripts" / "codex_token_monitor_opencode_adapter.py"))

    def test_normalize_builtin_adapter_command_uses_current_python_and_absolute_script(self) -> None:
        command = jobs._normalize_builtin_adapter_command([
            "python",
            "scripts/codex_token_monitor_opencode_adapter.py",
            "--task-file",
            "task.md",
        ])
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], str(jobs.REPO_ROOT / "scripts" / "codex_token_monitor_opencode_adapter.py"))

    def test_load_config_reads_debug_visible_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config_path = tmpdir / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "jobs_dir": "jobs",
                        "debug_visible_terminal": True,
                        "debug_open_session_tui": True,
                        "opencode_attach_url": "http://localhost:4096",
                        "opencode_command": r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd",
                        "export_session": "always",
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            config = jobs.load_config(config_path)
            self.assertTrue(config.debug_visible_terminal)
            self.assertTrue(config.debug_open_session_tui)
            self.assertEqual(config.opencode_attach_url, "http://localhost:4096")
            self.assertEqual(config.opencode_command, r"C:\Users\andre\AppData\Roaming\npm\opencode.cmd")
            self.assertEqual(config.export_session, "always")

    def test_collect_debug_metadata_reports_requested_visibility_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            job_dir = tmpdir / "job"
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / "opencode_launch.json").write_text(
                json.dumps(
                    {
                        "attach_url": "http://localhost:4096",
                        "session_lookup_attempted": True,
                        "session_lookup_status": "session_found",
                        "session_lookup_error": "",
                        "session_id_found": True,
                        "session_id": "ses_123",
                        "tui_open_attempted": True,
                        "tui_open_status": "launched_not_confirmed",
                        "tui_open_command": "wt.exe new-tab ...",
                        "tui_open_error": "",
                        "export_session": "on_failure",
                        "export_session_status": "exported",
                        "export_session_reason": "",
                        "session_export_path": str(job_dir / "opencode_session_export.json"),
                        "session_transcript_path": str(job_dir / "opencode_session_transcript.md"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            cfg = jobs.JobConfig(
                debug_visible_terminal=True,
                debug_open_session_tui=True,
                opencode_attach_url="http://localhost:4096",
            )
            metadata = jobs._collect_debug_metadata(
                config=cfg,
                job_dir=job_dir,
                process_pid=777,
            )
            self.assertEqual(metadata["debug_visible_terminal_status"], "adapter_started_not_confirmed")
            self.assertEqual(metadata["debug_open_session_tui_status"], "launched_not_confirmed")
            self.assertEqual(metadata["debug_session_id"], "ses_123")
            self.assertEqual(metadata["debug_attach_url"], "http://localhost:4096")
            self.assertEqual(metadata["export_session_status"], "exported")

    def test_collect_debug_metadata_reports_session_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            job_dir = tmpdir / "job"
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / "opencode_launch.json").write_text(
                json.dumps(
                    {
                        "session_lookup_attempted": True,
                        "session_lookup_status": "session_not_found",
                        "session_lookup_error": "",
                        "session_id_found": False,
                        "session_id": "",
                        "tui_open_attempted": False,
                        "tui_open_status": "launch_not_attempted",
                        "tui_open_command": "",
                        "tui_open_error": "",
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            cfg = jobs.JobConfig(debug_open_session_tui=True)
            metadata = jobs._collect_debug_metadata(
                config=cfg,
                job_dir=job_dir,
                process_pid=555,
            )
            self.assertEqual(metadata["debug_open_session_tui_status"], "session_not_found")
            self.assertIn("session_not_found", metadata["debug_open_session_tui_reason"])

    def assert_iso_utc(self, ts: str) -> None:
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
        self.assertRegex(ts, pattern, f"Timestamp {ts!r} is not ISO UTC")

    def assert_file_order(self, first: Path, second: Path) -> None:
        self.assertTrue(first.exists(), f"{first} does not exist")
        self.assertTrue(second.exists(), f"{second} does not exist")
        self.assertLessEqual(
            first.stat().st_mtime_ns,
            second.stat().st_mtime_ns,
            f"{first.name} should be older than {second.name}",
        )

    def test_success_result_then_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "success")
            self.assertEqual(result.status, jobs.STATUS_COMPLETED)
            result_path = Path(result.result_path)
            done_path = result_path.with_name("done.json")
            self.assertTrue(result_path.exists())
            self.assertTrue(done_path.exists())
            self.assert_file_order(result_path, done_path)
            self.assertEqual(result.reason, "completed")

    def test_process_exits_without_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "exit_without_done")
            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertEqual(result.reason, "process_exited_without_done")
            result_path = Path(result.result_path)
            done_path = result_path.with_name("done.json")
            self.assertTrue(result_path.exists())
            self.assertTrue(done_path.exists())

    def test_early_done_protocol_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "protocol_violation")
            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertEqual(result.reason, "protocol_violation_done_before_result")
            result_path = Path(result.result_path)
            done_path = result_path.with_name("done.json")
            self.assertTrue(result_path.exists())
            self.assertTrue(done_path.exists())
            content = result_path.read_text(encoding="utf-8")
            self.assertIn("Protocol Violation", content)

    def test_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=1,
                poll_interval_ms=100,
                provider_id="test",
                model_id="test-model",
                summary_tail_lines=80,
                summary_max_chars=4000,
                command_template=[
                    sys.executable, str(worker),
                    "--job-dir", "{job_dir}",
                    "--mode", "timeout",
                ],
            )
            result = jobs.run_opencode_job("test task", config=cfg)
            self.assertEqual(result.status, jobs.STATUS_BLOCKED)
            self.assertTrue(result.timed_out)
            result_path = Path(result.result_path)
            done_path = result_path.with_name("done.json")
            self.assertTrue(result_path.exists())
            self.assertTrue(done_path.exists())

    def test_result_exists_for_all_terminal_statuses(self) -> None:
        modes = ["success", "exit_without_done", "protocol_violation", "fast_protocol_violation"]
        for mode in modes:
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as tmp:
                    tmpdir = Path(tmp)
                    worker = _make_fake_worker(tmpdir)
                    result = _run_job(tmpdir, worker, mode)
                    result_path = Path(result.result_path)
                    self.assertTrue(
                        result_path.exists(),
                        f"result.md missing for mode={mode} status={result.status}",
                    )

    def test_unknown_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=10,
                poll_interval_ms=100,
                provider_id="test",
                model_id="test-model",
                command_template=[
                    sys.executable, str(worker),
                    "--job-dir", "{job_dir}",
                    "--unknown", "{bad_placeholder}",
                ],
            )
            result = jobs.run_opencode_job("task", config=cfg)
            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertIn("config_error: Unknown placeholder", result.reason)
            self.assertIsNone(result.exit_code)

    def test_jobs_dir_resolves_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                cfg = jobs.JobConfig(
                    jobs_dir="relative-jobs",
                    timeout_seconds=5,
                    poll_interval_ms=100,
                    provider_id="test",
                    model_id="test-model",
                    command_template=[
                        sys.executable, "-c", "import sys; sys.exit(0)",
                        "--job-dir", "{job_dir}",
                    ],
                )
                resolved = jobs._resolve_jobs_dir(cfg)
                expected = jobs.REPO_ROOT / "relative-jobs"
                self.assertEqual(resolved, expected)
                self.assertNotEqual(resolved, tmpdir / "relative-jobs")
            finally:
                os.chdir(original_cwd)

    def test_jobs_dir_resolves_relative_to_config_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config_dir = tmpdir / "config_subdir"
            config_dir.mkdir(parents=True, exist_ok=True)
            cfg = jobs.JobConfig(
                jobs_dir="relative-from-config",
                timeout_seconds=5,
                poll_interval_ms=100,
                provider_id="test",
                model_id="test-model",
                command_template=[
                    sys.executable, "-c", "import sys; sys.exit(0)",
                    "--job-dir", "{job_dir}",
                ],
            )
            resolved = jobs._resolve_jobs_dir(cfg, config_root=config_dir)
            expected = config_dir / "relative-from-config"
            self.assertEqual(resolved, expected)
            self.assertNotEqual(resolved, jobs.REPO_ROOT / "relative-from-config")

    def test_timestamps_are_iso_utc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "success")
            self.assert_iso_utc(result.started_at)
            self.assert_iso_utc(result.finished_at)

    def test_concurrent_jobs_distinct_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            results: list[jobs.JobResult] = []
            errors: list[Exception] = []
            lock = threading.Lock()

            def run() -> None:
                try:
                    r = _run_job(tmpdir, worker, "success")
                    with lock:
                        results.append(r)
                except Exception as e:
                    with lock:
                        errors.append(e)

            threads = [threading.Thread(target=run) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            self.assertEqual(len(errors), 0, f"Errors: {errors}")
            self.assertEqual(len(results), 3)
            job_dirs = {Path(r.result_path).parent for r in results}
            self.assertEqual(len(job_dirs), 3, "Concurrent jobs must use distinct dirs")

    def test_done_json_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "success")
            done_path = Path(result.result_path).with_name("done.json")
            self.assertTrue(done_path.exists())
            done = json.loads(done_path.read_text(encoding="utf-8"))
            expected_keys = {
                "job_id", "status", "reason", "summary",
                "started_at", "finished_at", "duration_ms",
                "exit_code", "timed_out", "provider_id", "model_id",
                "result_path", "stdout_path", "stderr_path",
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
            }
            self.assertEqual(set(done.keys()), expected_keys)

    def test_cleanup_old_jobs_dry_run_preserves_recent_20(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            jobs_dir = tmpdir / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            now_ts = time.time()

            for index in range(25):
                job_dir = jobs_dir / f"job-{index:02d}"
                job_dir.mkdir(parents=True, exist_ok=True)
                status = jobs.STATUS_COMPLETED
                (job_dir / "done.json").write_text(
                    json.dumps({"status": status}, ensure_ascii=False),
                    encoding="utf-8",
                )
                ts = now_ts - ((40 - index) * 86400)
                os.utime(job_dir / "done.json", (ts, ts))

            cfg = jobs.JobConfig(jobs_dir=str(jobs_dir))
            result = jobs.cleanup_old_jobs(cfg, dry_run=True, now_ts=now_ts)
            self.assertEqual(result["scanned"], 25)
            self.assertEqual(result["kept_recent"], 20)
            self.assertEqual(result["eligible"], 5)
            self.assertEqual(result["deleted"], 0)
            self.assertEqual(len(result["candidates"]), 5)

    def test_cleanup_old_jobs_dry_run_respects_failure_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            jobs_dir = tmpdir / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            now_ts = time.time()

            for index in range(21):
                job_dir = jobs_dir / f"job-{index:02d}"
                job_dir.mkdir(parents=True, exist_ok=True)
                status = jobs.STATUS_BLOCKED
                age_days = 29
                (job_dir / "done.json").write_text(
                    json.dumps({"status": status}, ensure_ascii=False),
                    encoding="utf-8",
                )
                ts = now_ts - (age_days * 86400)
                os.utime(job_dir / "done.json", (ts, ts))

            cfg = jobs.JobConfig(jobs_dir=str(jobs_dir))
            result = jobs.cleanup_old_jobs(cfg, dry_run=True, now_ts=now_ts)
            self.assertEqual(result["eligible"], 0)
            self.assertEqual(result["kept_by_age"], 1)

    def test_done_not_written_before_result_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "success")
            result_path = Path(result.result_path)
            done_path = result_path.with_name("done.json")
            result_mtime = result_path.stat().st_mtime_ns
            done_mtime = done_path.stat().st_mtime_ns
            self.assertLessEqual(result_mtime, done_mtime)

    def test_fast_protocol_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "fast_protocol_violation")
            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertEqual(result.reason, "protocol_violation_done_before_result")
            result_path = Path(result.result_path)
            done_path = result_path.with_name("done.json")
            self.assertTrue(result_path.exists())
            self.assertTrue(done_path.exists())
            content = result_path.read_text(encoding="utf-8")
            self.assertIn("Protocol Violation", content)

    def test_files_ready_before_child_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "done_then_sleep")
            self.assertEqual(result.status, jobs.STATUS_COMPLETED)
            self.assertEqual(result.reason, "completed")
            self.assertFalse(result.timed_out, "Should not be marked as timed out")
            result_path = Path(result.result_path)
            done_path = result_path.with_name("done.json")
            self.assertTrue(result_path.exists())
            self.assertTrue(done_path.exists())
            self.assert_file_order(result_path, done_path)
            self.assertIsNotNone(result.exit_code,
                                 "Child process must be terminated (exit_code should not be None)")

    def test_status_json_created_with_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "success")
            job_dir = Path(result.result_path).parent
            status_path = job_dir / "status.json"
            self.assertTrue(status_path.exists())
            status_data = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_data["status"], "running")

    def test_status_json_queued_on_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=10,
                poll_interval_ms=100,
                provider_id="test",
                model_id="test-model",
                command_template=[
                    sys.executable, str(worker),
                    "--job-dir", "{job_dir}",
                    "--unknown", "{bad_placeholder}",
                ],
            )
            result = jobs.run_opencode_job("task", config=cfg)
            job_dir = Path(result.result_path).parent
            status_path = job_dir / "status.json"
            self.assertTrue(status_path.exists())
            status_data = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_data["status"], "queued")

    def test_summary_source_from_result_md_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "success")
            self.assertEqual(result.status, jobs.STATUS_COMPLETED)
            self.assertIn("All good", result.summary)

    def test_summary_source_from_stderr_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            result = _run_job(tmpdir, worker, "exit_without_done")
            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertIn("done-no-done", result.summary)

    def test_status_json_not_written_without_job_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=5,
                poll_interval_ms=100,
                provider_id="test",
                model_id="test-model",
                command_template=[
                    sys.executable, "-c", "import sys; sys.exit(0)",
                    "--job-dir", "{job_dir}",
                ],
            )
            result = jobs.run_opencode_job("task", config=cfg)
            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertEqual(result.reason, "process_exited_without_done")

    def test_builtin_adapter_bootstrap_timeout_creates_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker = _make_fake_worker(tmpdir)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=30,
                poll_interval_ms=50,
                provider_id="test",
                model_id="test-model",
                command_template=[
                    sys.executable, str(worker),
                    "--job-dir", "{job_dir}",
                    "--mode", "timeout",
                ],
            )
            with mock.patch.object(jobs, "_command_uses_builtin_adapter", return_value=True):
                with mock.patch.object(jobs, "ADAPTER_BOOTSTRAP_TIMEOUT_SECONDS", 1):
                    result = jobs.run_opencode_job("task", config=cfg)

            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertEqual(result.reason, "adapter_bootstrap_timeout")
            job_dir = Path(result.result_path).parent
            self.assertTrue((job_dir / "stdout.log").exists())
            self.assertTrue((job_dir / "stderr.log").exists())
            self.assertTrue((job_dir / "opencode_launch.json").exists())
            self.assertIn("adapter bootstrap timed out", (job_dir / "stderr.log").read_text(encoding="utf-8"))
            launch = json.loads((job_dir / "opencode_launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch["launch_writer"], "wrapper_prelaunch")
            self.assertEqual(launch["wrapper_launch_status"], "adapter_bootstrap_timeout")

    def test_builtin_adapter_exit_without_bootstrap_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=5,
                poll_interval_ms=50,
                provider_id="test",
                model_id="test-model",
                command_template=[
                    sys.executable, "-c", "import sys; sys.exit(0)",
                    "--job-dir", "{job_dir}",
                ],
            )
            with mock.patch.object(jobs, "_command_uses_builtin_adapter", return_value=True):
                result = jobs.run_opencode_job("task", config=cfg)

            self.assertEqual(result.status, jobs.STATUS_FAILED)
            self.assertEqual(result.reason, "adapter_exited_without_bootstrap")
            job_dir = Path(result.result_path).parent
            self.assertIn("adapter exited before writing adapter launch artifacts", (job_dir / "stderr.log").read_text(encoding="utf-8"))

    def test_builtin_adapter_launch_detaches_stdin_and_captures_bootstrap_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=5,
                poll_interval_ms=50,
                provider_id="test",
                model_id="test-model",
                command_template=[
                    sys.executable, "-c", "import sys; sys.exit(0)",
                    "--job-dir", "{job_dir}",
                ],
            )

            class FakeProcess:
                pid = 12345

                def __init__(self) -> None:
                    self.returncode = 0

                def poll(self) -> int:
                    return 0

                def wait(self, timeout: int | None = None) -> int:
                    self.returncode = 0
                    return 0

            with mock.patch.object(jobs, "_command_uses_builtin_adapter", return_value=True):
                with mock.patch.object(jobs.subprocess, "Popen", return_value=FakeProcess()) as popen_mock:
                    result = jobs.run_opencode_job("task", config=cfg)

            self.assertEqual(result.reason, "adapter_exited_without_bootstrap")
            self.assertIs(popen_mock.call_args.kwargs["stdin"], subprocess.DEVNULL)
            job_dir = Path(result.result_path).parent
            self.assertTrue((job_dir / "adapter_bootstrap_stdout.log").exists())
            self.assertTrue((job_dir / "adapter_bootstrap_stderr.log").exists())
            launch = json.loads((job_dir / "opencode_launch.json").read_text(encoding="utf-8"))
            self.assertEqual(
                launch["adapter_bootstrap_stdout_path"],
                str(job_dir / "adapter_bootstrap_stdout.log"),
            )
            self.assertEqual(
                launch["adapter_bootstrap_stderr_path"],
                str(job_dir / "adapter_bootstrap_stderr.log"),
            )


class OpenCodeJobsCliTests(unittest.TestCase):

    def _run_cli(self, tmpdir: Path, task_text: str, config_overrides: dict | None = None) -> subprocess.CompletedProcess:
        task_file = tmpdir / "task.txt"
        task_file.write_text(task_text, encoding="utf-8")

        if config_overrides:
            config_file = tmpdir / "config.json"
            defaults = {
                "jobs_dir": str(tmpdir / "jobs"),
                "timeout_seconds": 10,
                "poll_interval_ms": 100,
                "provider_id": "test",
                "model_id": "test-model",
                "summary_tail_lines": 80,
                "summary_max_chars": 4000,
                "command_template": [
                    sys.executable, "-c", "import sys; sys.exit(0)",
                    "--job-dir", "{job_dir}",
                ],
            }
            defaults.update(config_overrides)
            config_file.write_text(
                json.dumps(defaults, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            config_arg = ["--config", str(config_file)]
        else:
            config_arg = []

        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--task-file", str(task_file)] + config_arg,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result

    def test_cli_output_limited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            worker_path = _make_fake_worker(tmpdir)
            result = self._run_cli(tmpdir, "test", {
                "command_template": [
                    sys.executable, str(worker_path),
                    "--job-dir", "{job_dir}",
                    "--mode", "success",
                    "--sleep", "0.01",
                ],
            })
            self.assertEqual(result.returncode, 0)
            for line in result.stdout.splitlines():
                self.assertTrue(line.startswith("job_id:") or line.startswith("status:") or
                                line.startswith("reason:") or line.startswith("summary:") or
                                line.startswith("duration_ms:") or line.startswith("timed_out:") or
                                line.startswith("result:") or line.startswith("stdout:") or
                                line.startswith("stderr:"),
                                f"Unexpected CLI output line: {line}")

    def test_cli_exit_codes_mapped(self) -> None:
        cases = [
            ("success", jobs.EXIT_COMPLETED),
            ("exit_without_done", jobs.EXIT_FAILED),
            ("protocol_violation", jobs.EXIT_PROTOCOL_ERROR),
        ]
        for mode, expected_code in cases:
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as tmp:
                    tmpdir = Path(tmp)
                    worker_path = _make_fake_worker(tmpdir)
                    sleep_time = "0.5" if mode == "protocol_violation" else "0.01"
                    result = self._run_cli(tmpdir, "test", {
                        "command_template": [
                            sys.executable, str(worker_path),
                            "--job-dir", "{job_dir}",
                            "--mode", mode,
                            "--sleep", sleep_time,
                        ],
                    })
                    self.assertEqual(result.returncode, expected_code)

    def test_cli_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            missing = tmpdir / "nonexistent.txt"
            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--task-file", str(missing)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, jobs.EXIT_CONFIG_ERROR)

    def test_cli_unknown_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            result = self._run_cli(tmpdir, "test", {
                "command_template": ["echo", "{bad}"],
            })
            self.assertEqual(result.returncode, jobs.EXIT_CONFIG_ERROR)


class OpenCodeJobsSmokeTests(unittest.TestCase):

    def test_real_opencode_wrapper_smoke(self) -> None:
        if os.environ.get("OPENCODE_JOB_WRAPPER_SMOKE") != "1":
            self.skipTest("Set OPENCODE_JOB_WRAPPER_SMOKE=1 to run the real OpenCode smoke test")
        if shutil.which("opencode") is None:
            self.skipTest("opencode CLI is not available in PATH")

        provider_id = os.environ.get("OPENCODE_JOB_WRAPPER_PROVIDER_ID", "opencode")
        model_id = os.environ.get("OPENCODE_JOB_WRAPPER_MODEL_ID", "deepseek-v4-flash-free")
        task_text = (
            "Return a one-line validation message and follow the provided file protocol exactly. "
            "Do not modify repository files outside the supplied job directory."
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            cfg = jobs.JobConfig(
                jobs_dir=str(tmpdir / "jobs"),
                timeout_seconds=180,
                poll_interval_ms=500,
                provider_id=provider_id,
                model_id=model_id,
                summary_tail_lines=80,
                summary_max_chars=4000,
                command_template=[
                    sys.executable,
                    str(ROOT / "scripts" / "codex_token_monitor_opencode_adapter.py"),
                    "--task-file", "{task_file}",
                    "--job-dir", "{job_dir}",
                    "--provider-id", "{provider_id}",
                    "--model-id", "{model_id}",
                ],
            )

            result = jobs.run_opencode_job(task_text, config=cfg)

            self.assertNotEqual(result.reason, "opencode_not_found")
            self.assertFalse(result.timed_out, f"Smoke test timed out: {result.summary}")
            self.assertTrue(Path(result.result_path).exists())
            self.assertTrue(Path(result.result_path).with_name("done.json").exists())
            self.assertIn(
                result.status,
                {jobs.STATUS_COMPLETED, jobs.STATUS_PARTIAL, jobs.STATUS_FAILED},
                f"Unexpected smoke-test status: {result.status} summary={result.summary}",
            )


if __name__ == "__main__":
    unittest.main()
