import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

ALLOWED_PLACEHOLDERS = frozenset({"{task_file}", "{job_dir}", "{provider_id}", "{model_id}"})

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"

GRACE_TERMINATE_SECONDS = 5
EXIT_COMPLETED = 0
EXIT_PARTIAL = 10
EXIT_BLOCKED = 20
EXIT_FAILED = 30
EXIT_CONFIG_ERROR = 31
EXIT_PROTOCOL_ERROR = 32

EXPORT_SESSION_OFF = "off"
EXPORT_SESSION_ON_FAILURE = "on_failure"
EXPORT_SESSION_ON_DEBUG = "on_debug"
EXPORT_SESSION_ALWAYS = "always"
VALID_EXPORT_SESSION_MODES = frozenset({
    EXPORT_SESSION_OFF,
    EXPORT_SESSION_ON_FAILURE,
    EXPORT_SESSION_ON_DEBUG,
    EXPORT_SESSION_ALWAYS,
})


@dataclass
class JobConfig:
    jobs_dir: str = "_local/codex-token-monitor/opencode-jobs"
    timeout_seconds: int = 600
    poll_interval_ms: int = 1000
    provider_id: str = "opencode"
    model_id: str = "deepseek-v4-flash-free"
    opencode_command: str = ""
    debug_visible_terminal: bool = False
    debug_open_session_tui: bool = False
    opencode_attach_url: str = ""
    export_session: str = EXPORT_SESSION_ON_FAILURE
    summary_tail_lines: int = 80
    summary_max_chars: int = 4000
    cleanup_success_after_days: int = 7
    cleanup_failure_after_days: int = 30
    cleanup_keep_recent: int = 20
    command_template: list[str] = field(default_factory=lambda: [
        "python",
        "scripts/codex_token_monitor_opencode_adapter.py",
        "--task-file", "{task_file}",
        "--job-dir", "{job_dir}",
        "--provider-id", "{provider_id}",
        "--model-id", "{model_id}",
    ])


@dataclass
class JobResult:
    job_id: str = ""
    status: str = ""
    reason: str = ""
    summary: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    exit_code: int | None = None
    timed_out: bool = False
    provider_id: str = ""
    model_id: str = ""
    result_path: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    launch_path: str = ""
    debug_visible_terminal_requested: bool = False
    debug_visible_terminal_status: str = "not_requested"
    debug_visible_terminal_reason: str = ""
    debug_visible_terminal_pid: int | None = None
    debug_open_session_tui_requested: bool = False
    debug_open_session_tui_status: str = "not_requested"
    debug_open_session_tui_reason: str = ""
    debug_session_id: str = ""
    debug_tui_command: str = ""
    debug_attach_url: str = ""
    export_session_mode: str = EXPORT_SESSION_ON_FAILURE
    export_session_status: str = "not_requested"
    export_session_reason: str = ""
    session_export_path: str = ""
    session_transcript_path: str = ""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_json_safe(path: Path) -> Any | None:
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def _normalize_export_session_mode(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in VALID_EXPORT_SESSION_MODES:
        return normalized
    return EXPORT_SESSION_ON_FAILURE


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _utcnow() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:3] + "Z"


def _terminate_process_tree(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _validate_placeholders(tokens: list[str]) -> None:
    for token in tokens:
        if "{" in token:
            for part in token.split("{")[1:]:
                placeholder = "{" + part.split("}")[0] + "}"
                if placeholder not in ALLOWED_PLACEHOLDERS:
                    raise ValueError(f"Unknown placeholder: {placeholder}")


def _substitute_placeholders(tokens: list[str], *, task_file: str, job_dir: str, provider_id: str, model_id: str) -> list[str]:
    mapping = {
        "{task_file}": task_file,
        "{job_dir}": job_dir,
        "{provider_id}": provider_id,
        "{model_id}": model_id,
    }
    result = []
    for token in tokens:
        t = token
        for key, value in mapping.items():
            t = t.replace(key, value)
        result.append(t)
    return result


def _build_adapter_command(
    config: JobConfig,
    *,
    task_file: Path,
    job_dir: Path,
    provider_id: str,
    model_id: str,
    stdout_path: Path,
    stderr_path: Path,
    directory: str | None,
) -> list[str]:
    command_tokens = _substitute_placeholders(
        config.command_template,
        task_file=str(task_file),
        job_dir=str(job_dir),
        provider_id=provider_id,
        model_id=model_id,
    )
    command_tokens.extend([
        "--stdout-log", str(stdout_path),
        "--stderr-log", str(stderr_path),
    ])
    if directory:
        command_tokens.extend(["--directory", directory])
    if config.opencode_command:
        command_tokens.extend(["--opencode-command", config.opencode_command])
    if config.debug_visible_terminal:
        command_tokens.append("--debug-visible-terminal")
    if config.debug_open_session_tui:
        command_tokens.append("--debug-open-session-tui")
    if config.opencode_attach_url:
        command_tokens.extend(["--opencode-attach-url", config.opencode_attach_url])
    command_tokens.extend(["--export-session", _normalize_export_session_mode(config.export_session)])
    return command_tokens


def _command_uses_builtin_adapter(command_tokens: list[str]) -> bool:
    adapter_markers = {
        "scripts/codex_token_monitor_opencode_adapter.py",
        "scripts\\codex_token_monitor_opencode_adapter.py",
        "codex_token_monitor_opencode_adapter.py",
    }
    return any(token in adapter_markers or token.endswith("codex_token_monitor_opencode_adapter.py") for token in command_tokens)


def load_config(config_path: Path | None = None) -> JobConfig:
    if config_path is None:
        config_path = CONFIG_DIR / "opencode_job_defaults.json"
    defaults = JobConfig()
    data = _read_json_safe(config_path)
    if not data:
        return defaults
    kwargs = {k: data.get(k, getattr(defaults, k)) for k in JobConfig.__dataclass_fields__}
    config = JobConfig(**kwargs)
    config.export_session = _normalize_export_session_mode(config.export_session)
    return config


def _resolve_jobs_dir(config: JobConfig, config_root: Path | None = None) -> Path:
    jobs_dir = Path(config.jobs_dir)
    if not jobs_dir.is_absolute():
        if config_root is not None:
            jobs_dir = config_root / jobs_dir
        else:
            jobs_dir = REPO_ROOT / jobs_dir
    return jobs_dir


def _read_with_tail_max(path: Path, config: JobConfig) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    tail = lines[-config.summary_tail_lines:] if config.summary_tail_lines > 0 else lines
    summary = "\n".join(tail)
    if config.summary_max_chars > 0 and len(summary) > config.summary_max_chars:
        summary = summary[:config.summary_max_chars] + "..."
    return summary


def _derive_summary(status: str, result_path: Path, stderr_path: Path, stdout_path: Path, config: JobConfig) -> str:
    success_like = frozenset({STATUS_COMPLETED, STATUS_PARTIAL})
    if status in success_like:
        primary = result_path
        fallbacks = [stderr_path, stdout_path]
    else:
        primary = stderr_path
        fallbacks = [stdout_path, result_path]
    text = _read_with_tail_max(primary, config)
    if text.strip():
        return text
    for fb in fallbacks:
        text = _read_with_tail_max(fb, config)
        if text.strip():
            return text
    return ""


def _collect_debug_metadata(
    *,
    config: JobConfig,
    job_dir: Path,
    process_pid: int | None,
    process_launch_error: str = "",
) -> dict[str, Any]:
    launch_path = job_dir / "opencode_launch.json"
    launch_data = _read_json_safe(launch_path)
    if not isinstance(launch_data, dict):
        launch_data = {}

    visible_requested = bool(config.debug_visible_terminal)
    open_tui_requested = bool(config.debug_open_session_tui)
    attach_url = str(launch_data.get("attach_url", "") or config.opencode_attach_url or "")
    session_id = str(launch_data.get("session_id", "") or "")
    tui_command = str(launch_data.get("tui_open_command", "") or "")
    export_session_mode = _normalize_export_session_mode(
        str(launch_data.get("export_session", "") or config.export_session)
    )
    export_session_status = str(
        launch_data.get("export_session_status", "")
        or ("not_requested" if export_session_mode == EXPORT_SESSION_OFF else "pending")
    )
    export_session_reason = str(launch_data.get("export_session_reason", "") or "")
    session_export_path = str(launch_data.get("session_export_path", "") or "")
    session_transcript_path = str(launch_data.get("session_transcript_path", "") or "")

    if not visible_requested:
        visible_status = "not_requested"
        visible_reason = ""
    elif process_launch_error:
        visible_status = "launch_failed"
        visible_reason = process_launch_error
    elif process_pid is not None:
        visible_status = "adapter_started_not_confirmed"
        visible_reason = (
            "Wrapper started the adapter in visible-terminal mode, but actual "
            "console visibility is not machine-confirmed."
        )
    else:
        visible_status = "not_started"
        visible_reason = "Wrapper did not record a started adapter process."

    if not open_tui_requested:
        open_tui_status = "not_requested"
        open_tui_reason = ""
    elif process_launch_error:
        open_tui_status = "not_started"
        open_tui_reason = "Adapter launch failed before session lookup could start."
    elif process_pid is None and not launch_data:
        open_tui_status = "not_started"
        open_tui_reason = "Adapter did not start, so session lookup did not begin."
    elif not launch_data:
        open_tui_status = "diagnostics_missing"
        open_tui_reason = "Adapter did not write opencode_launch.json diagnostics."
    elif not bool(launch_data.get("session_lookup_attempted")):
        open_tui_status = "lookup_not_attempted"
        open_tui_reason = "Adapter did not attempt OpenCode session lookup."
    elif str(launch_data.get("session_lookup_error", "")).strip():
        open_tui_status = "lookup_failed"
        open_tui_reason = str(launch_data.get("session_lookup_error", "")).strip()
    elif not bool(launch_data.get("session_id_found")):
        open_tui_status = "session_not_found"
        open_tui_reason = (
            str(launch_data.get("session_lookup_status", "")).strip()
            or "Matching OpenCode session was not found for this job."
        )
    elif str(launch_data.get("tui_open_error", "")).strip():
        open_tui_status = "launch_failed"
        open_tui_reason = str(launch_data.get("tui_open_error", "")).strip()
    elif bool(launch_data.get("tui_open_attempted")):
        open_tui_status = "launched_not_confirmed"
        open_tui_reason = (
            "Wrapper launched a TUI/attach terminal, but actual window visibility "
            "is not machine-confirmed."
        )
    else:
        open_tui_status = "launch_not_attempted"
        open_tui_reason = "Session was found but no TUI launch attempt was recorded."

    return {
        "launch_path": str(launch_path),
        "debug_visible_terminal_requested": visible_requested,
        "debug_visible_terminal_status": visible_status,
        "debug_visible_terminal_reason": visible_reason,
        "debug_visible_terminal_pid": process_pid,
        "debug_open_session_tui_requested": open_tui_requested,
        "debug_open_session_tui_status": open_tui_status,
        "debug_open_session_tui_reason": open_tui_reason,
        "debug_session_id": session_id,
        "debug_tui_command": tui_command,
        "debug_attach_url": attach_url,
        "export_session_mode": export_session_mode,
        "export_session_status": export_session_status,
        "export_session_reason": export_session_reason,
        "session_export_path": session_export_path,
        "session_transcript_path": session_transcript_path,
    }


def _job_sort_timestamp(job_dir: Path) -> float:
    done_path = job_dir / "done.json"
    if done_path.exists():
        try:
            return done_path.stat().st_mtime
        except OSError:
            return 0.0
    try:
        return job_dir.stat().st_mtime
    except OSError:
        return 0.0


def _job_status(job_dir: Path) -> str:
    data = _read_json_safe(job_dir / "done.json")
    if isinstance(data, dict):
        return str(data.get("status", "")).strip().lower()
    return ""


def cleanup_old_jobs(
    config: JobConfig,
    *,
    config_root: Path | None = None,
    dry_run: bool = True,
    now_ts: float | None = None,
) -> dict[str, Any]:
    jobs_dir = _resolve_jobs_dir(config, config_root=config_root)
    if not jobs_dir.exists():
        return {
            "jobs_dir": str(jobs_dir),
            "dry_run": dry_run,
            "scanned": 0,
            "eligible": 0,
            "deleted": 0,
            "kept_recent": 0,
            "kept_by_age": 0,
            "candidates": [],
        }

    now_value = time.time() if now_ts is None else now_ts
    job_dirs = [path for path in jobs_dir.iterdir() if path.is_dir()]
    decorated = [
        {
            "path": path,
            "status": _job_status(path),
            "timestamp": _job_sort_timestamp(path),
        }
        for path in job_dirs
    ]
    decorated.sort(key=lambda item: item["timestamp"], reverse=True)

    keep_recent = max(int(config.cleanup_keep_recent), 0)
    success_statuses = {STATUS_COMPLETED, STATUS_PARTIAL}
    candidates: list[str] = []
    deleted = 0
    kept_by_age = 0

    for index, item in enumerate(decorated):
        if index < keep_recent:
            continue
        status = str(item["status"])
        age_days = (now_value - float(item["timestamp"])) / 86400.0 if item["timestamp"] else float("inf")
        threshold_days = (
            config.cleanup_success_after_days
            if status in success_statuses
            else config.cleanup_failure_after_days
        )
        if age_days < threshold_days:
            kept_by_age += 1
            continue
        candidate_path = str(Path(item["path"]).resolve(strict=False))
        candidates.append(candidate_path)
        if not dry_run:
            shutil.rmtree(item["path"], ignore_errors=False)
            deleted += 1

    return {
        "jobs_dir": str(jobs_dir),
        "dry_run": dry_run,
        "scanned": len(decorated),
        "eligible": len(candidates),
        "deleted": deleted,
        "kept_recent": min(keep_recent, len(decorated)),
        "kept_by_age": kept_by_age,
        "candidates": candidates,
        "retention": {
            "success_after_days": config.cleanup_success_after_days,
            "failure_after_days": config.cleanup_failure_after_days,
            "keep_recent": keep_recent,
        },
    }


def run_opencode_job(
    task_text: str,
    *,
    config: JobConfig,
    config_root: Path | None = None,
    directory: str | None = None,
) -> JobResult:
    job_id = str(uuid.uuid4())
    provider_id = config.provider_id
    model_id = config.model_id

    jobs_dir = _resolve_jobs_dir(config, config_root=config_root)
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    status_path = job_dir / "status.json"
    _atomic_write_json(status_path, {"status": "queued"})

    started_at = _utcnow()

    task_file = job_dir / "task.md"
    task_file.write_text(task_text, encoding="utf-8")

    result_path = job_dir / "result.md"
    done_path = job_dir / "done.json"
    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"
    debug_metadata = _collect_debug_metadata(config=config, job_dir=job_dir, process_pid=None)

    for p in [done_path, result_path]:
        if p.exists():
            p.unlink(missing_ok=True)

    try:
        _validate_placeholders(config.command_template)
    except ValueError as e:
        finished_at = _utcnow()
        duration_ms = 0
        result = JobResult(
            job_id=job_id,
            status=STATUS_FAILED,
            reason=f"config_error: {e}",
            summary=_derive_summary(STATUS_FAILED, result_path, stderr_path, stdout_path, config),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            exit_code=None,
            timed_out=False,
            provider_id=provider_id,
            model_id=model_id,
            result_path=str(result_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            **debug_metadata,
        )
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** {e}\n")
        _atomic_write_json(done_path, asdict(result))
        return result

    command_tokens = _build_adapter_command(
        config,
        task_file=task_file,
        job_dir=job_dir,
        provider_id=provider_id,
        model_id=model_id,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        directory=directory,
    )

    stdout_handle = None
    stderr_handle = None
    process_pid: int | None = None
    process_launch_error = ""
    try:
        popen_kwargs: dict[str, Any] = {
            "shell": False,
            "cwd": str(REPO_ROOT),
        }
        if config.debug_visible_terminal and sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        elif _command_uses_builtin_adapter(command_tokens):
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL
        else:
            stdout_handle = open(stdout_path, "w", encoding="utf-8")
            stderr_handle = open(stderr_path, "w", encoding="utf-8")
            popen_kwargs["stdout"] = stdout_handle
            popen_kwargs["stderr"] = stderr_handle
        process = subprocess.Popen(command_tokens, **popen_kwargs)
        process_pid = process.pid
    except OSError as e:
        process_launch_error = f"Failed to launch process: {e}"
        debug_metadata = _collect_debug_metadata(
            config=config,
            job_dir=job_dir,
            process_pid=None,
            process_launch_error=process_launch_error,
        )
        finished_at = _utcnow()
        duration_ms = 0
        result = JobResult(
            job_id=job_id,
            status=STATUS_FAILED,
            reason=process_launch_error,
            summary=_derive_summary(STATUS_FAILED, result_path, stderr_path, stdout_path, config),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            exit_code=None,
            timed_out=False,
            provider_id=provider_id,
            model_id=model_id,
            result_path=str(result_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            **debug_metadata,
        )
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** {process_launch_error}\n")
        _atomic_write_json(done_path, asdict(result))
        return result
    finally:
        if stdout_handle is not None:
            stdout_handle.close()
        if stderr_handle is not None:
            stderr_handle.close()

    _atomic_write_json(status_path, {"status": "running"})

    timed_out = False
    protocol_violation = False
    poll_interval = config.poll_interval_ms / 1000.0
    deadline = time.monotonic() + config.timeout_seconds

    while time.monotonic() < deadline:
        ret = process.poll()
        if ret is not None:
            break
        if done_path.exists() and not result_path.exists():
            protocol_violation = True
            _terminate_process_tree(process.pid)
            try:
                process.wait(timeout=30)
            except Exception:
                pass
            break
        if done_path.exists() and result_path.exists():
            break
        time.sleep(poll_interval)
    else:
        timed_out = True
        _terminate_process_tree(process.pid)
        try:
            process.wait(timeout=30)
        except Exception:
            pass

    if not protocol_violation and done_path.exists() and not result_path.exists():
        protocol_violation = True

    if not timed_out and not protocol_violation and process.returncode is None:
        try:
            process.wait(timeout=GRACE_TERMINATE_SECONDS)
        except Exception:
            pass
        if process.returncode is None:
            _terminate_process_tree(process.pid)
            try:
                process.wait(timeout=30)
            except Exception:
                pass

    exit_code = process.returncode

    finished_at = _utcnow()
    try:
        started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished_dt = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        duration_ms = int((finished_dt - started_dt).total_seconds() * 1000)
    except Exception:
        duration_ms = 0

    if protocol_violation:
        status = STATUS_FAILED
        reason = "protocol_violation_done_before_result"
        summary = _derive_summary(status, result_path, stderr_path, stdout_path, config)
        _atomic_write_text(result_path, f"# Protocol Violation\n\ndone.json was written before result.md\n")
    elif timed_out:
        status = STATUS_BLOCKED
        reason = "timed_out"
        summary = _derive_summary(status, result_path, stderr_path, stdout_path, config)
        _atomic_write_text(result_path, f"# Job Blocked\n\n**Reason:** timed_out\n")
    elif done_path.exists():
        done_data = _read_json_safe(done_path) or {}
        status = done_data.get("status", STATUS_FAILED)
        reason = done_data.get("reason", "")
        summary = _derive_summary(status, result_path, stderr_path, stdout_path, config)
    elif exit_code is not None:
        status = STATUS_FAILED
        reason = "process_exited_without_done"
        summary = _derive_summary(status, result_path, stderr_path, stdout_path, config)
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** process_exited_without_done\n")
    else:
        status = STATUS_FAILED
        reason = "process_exited_without_done"
        summary = _derive_summary(status, result_path, stderr_path, stdout_path, config)
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** process_exited_without_done\n")

    debug_metadata = _collect_debug_metadata(
        config=config,
        job_dir=job_dir,
        process_pid=process_pid,
    )

    result = JobResult(
        job_id=job_id,
        status=status,
        reason=reason,
        summary=summary,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        exit_code=exit_code,
        timed_out=timed_out,
        provider_id=provider_id,
        model_id=model_id,
        result_path=str(result_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        **debug_metadata,
    )

    _atomic_write_json(done_path, asdict(result))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an OpenCode job")
    parser.add_argument("--task-file", type=str, default=None, help="Path to task file")
    parser.add_argument("--config", type=str, default=None, help="Path to config file")
    parser.add_argument("--directory", type=str, default=None, help="Working directory for the OpenCode task")
    parser.add_argument(
        "--cleanup-jobs",
        action="store_true",
        help="List removable old job directories using retention rules",
    )
    parser.add_argument(
        "--apply-cleanup",
        action="store_true",
        help="Actually delete cleanup candidates instead of running a dry-run",
    )
    parser.add_argument(
        "--debug-visible-terminal",
        action="store_true",
        help="Launch the adapter in a visible Windows terminal for manual debugging",
    )
    parser.add_argument(
        "--debug-open-session-tui",
        action="store_true",
        help="Try to open a separate OpenCode TUI/attach window for the live run session",
    )
    parser.add_argument(
        "--opencode-attach-url",
        type=str,
        default=None,
        help="Optional shared OpenCode server URL used for run/attach debug flows",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    config_root = config_path.parent if config_path else None

    if args.cleanup_jobs:
        payload = cleanup_old_jobs(
            config,
            config_root=config_root,
            dry_run=not args.apply_cleanup,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED)

    if not args.task_file:
        print("Error: --task-file is required unless --cleanup-jobs is used", file=sys.stderr)
        sys.exit(EXIT_CONFIG_ERROR)

    task_path = Path(args.task_file)
    if not task_path.exists():
        print(f"Error: task file not found: {task_path}", file=sys.stderr)
        sys.exit(EXIT_CONFIG_ERROR)
    if args.debug_visible_terminal:
        config.debug_visible_terminal = True
    if args.debug_open_session_tui:
        config.debug_open_session_tui = True
    if args.opencode_attach_url:
        config.opencode_attach_url = args.opencode_attach_url

    task_text = task_path.read_text(encoding="utf-8")

    try:
        result = run_opencode_job(
            task_text,
            config=config,
            config_root=config_root,
            directory=args.directory,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(EXIT_FAILED)

    print(f"job_id: {result.job_id}")
    print(f"status: {result.status}")
    print(f"reason: {result.reason}")
    summary = result.summary.replace("\n", "\\n")
    print(f"summary: {summary}")
    print(f"duration_ms: {result.duration_ms}")
    print(f"timed_out: {result.timed_out}")
    print(f"result: {result.result_path}")
    print(f"stdout: {result.stdout_path}")
    print(f"stderr: {result.stderr_path}")

    exit_map = {
        STATUS_COMPLETED: EXIT_COMPLETED,
        STATUS_PARTIAL: EXIT_PARTIAL,
        STATUS_BLOCKED: EXIT_BLOCKED,
        STATUS_FAILED: EXIT_FAILED,
    }
    exit_code = exit_map.get(result.status, EXIT_FAILED)
    if result.reason == "protocol_violation_done_before_result":
        exit_code = EXIT_PROTOCOL_ERROR
    elif result.reason.startswith("config_error: "):
        exit_code = EXIT_CONFIG_ERROR
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
