import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import git_utils as _git_utils
except ImportError:
    _git_utils = None

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
DEFAULT_TIMEOUT_SECONDS = 180
ADAPTER_BOOTSTRAP_TIMEOUT_SECONDS = 15

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

ZWORKER_MODE_PROMPT_PACK = "zworker_prompt_pack"
ZWORKER_MODE_RESULT_UNPACK = "zworker_result_unpack"
ZWORKER_MODE_PROCESS_RESULT = "zworker_process_result"
ZWORKER_MODE_REVISION_PROMPT = "zworker_revision_prompt"
ZWORKER_VALID_MODES = frozenset({
    ZWORKER_MODE_PROMPT_PACK,
    ZWORKER_MODE_RESULT_UNPACK,
    ZWORKER_MODE_PROCESS_RESULT,
    ZWORKER_MODE_REVISION_PROMPT,
})

ZWORKER_RUNTIME_REQUESTS = REPO_ROOT / ".ai" / "zworker" / "runtime" / "requests"
ZWORKER_RUNTIME_INBOX = REPO_ROOT / ".ai" / "zworker" / "runtime" / "inbox"
ZWORKER_RUNTIME_REVISIONS = REPO_ROOT / ".ai" / "zworker" / "runtime" / "revisions"
ZWORKER_TEMPLATE_DIR = REPO_ROOT / ".ai" / "zworker" / "templates"

@dataclass
class JobConfig:
    jobs_dir: str = "_local/codex-token-monitor/opencode-jobs"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
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
    route_c_profile: str = ""
    route_c_profiles: dict = field(default_factory=dict)
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
    route_c_profile: str = ""
    route_c_profile_account_id: str = ""
    route_c_profile_account_index: int = 0


ROUTE_C_QUOTA_HINTS = (
    "quota exceeded",
    "rate limit",
    "daily limit",
    "insufficient credits",
    "insufficient credit",
    "credit balance",
    "quota_exceeded",
    "rate_limit",
    "too many requests",
    "http 429",
    "status 429",
    " 429 ",
)

ROUTE_C_RETRYABLE_REASON_HINTS = (
    "opencode_exit_",
    "quota",
    "rate_limit",
)


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


def _append_text(path: Path, text: str) -> None:
    if not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _normalize_positive_int(value: Any, *, default: int, minimum: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    if normalized < minimum:
        return minimum
    return normalized


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
    if _command_uses_builtin_adapter(command_tokens):
        command_tokens = _normalize_builtin_adapter_command(command_tokens)
        command_tokens = _force_builtin_adapter_model_args(
            command_tokens,
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


def _normalize_builtin_adapter_command(command_tokens: list[str]) -> list[str]:
    normalized = list(command_tokens)
    if normalized:
        launcher = Path(normalized[0]).name.casefold()
        if launcher in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"} and sys.executable:
            normalized[0] = sys.executable
    for index, token in enumerate(normalized):
        token_norm = token.replace("\\", "/")
        if token_norm.endswith("scripts/codex_token_monitor_opencode_adapter.py"):
            normalized[index] = str(REPO_ROOT / "scripts" / "codex_token_monitor_opencode_adapter.py")
            break
        if token_norm == "codex_token_monitor_opencode_adapter.py":
            normalized[index] = str(REPO_ROOT / "scripts" / "codex_token_monitor_opencode_adapter.py")
            break
    return normalized


def _force_builtin_adapter_model_args(
    command_tokens: list[str],
    *,
    provider_id: str,
    model_id: str,
) -> list[str]:
    normalized = list(command_tokens)
    replacements = {
        "--provider-id": provider_id,
        "--model-id": model_id,
    }
    for flag, value in replacements.items():
        try:
            index = normalized.index(flag)
        except ValueError:
            normalized.extend([flag, value])
            continue
        if index + 1 < len(normalized):
            normalized[index + 1] = value
        else:
            normalized.append(value)
    return normalized


def _command_display(command_tokens: list[str]) -> str:
    try:
        return subprocess.list2cmdline(command_tokens)
    except Exception:
        return " ".join(command_tokens)


def _update_launch_artifact(job_dir: Path, **updates: Any) -> None:
    launch_path = job_dir / "opencode_launch.json"
    payload = _read_json_safe(launch_path)
    if not isinstance(payload, dict):
        payload = {}
    payload.update(updates)
    _atomic_write_json(launch_path, payload)


def _write_wrapper_log_preamble(path: Path, *, mode: str, cwd: str | None, command_tokens: list[str]) -> None:
    preamble = (
        f"[wrapper] mode={mode}\n"
        f"[wrapper] cwd={cwd or ''}\n"
        f"[wrapper] command={_command_display(command_tokens)}\n\n"
    )
    _atomic_write_text(path, preamble)


def _write_wrapper_bootstrap_artifacts(
    *,
    job_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    command_tokens: list[str],
    directory: str | None,
    provider_id: str,
    model_id: str,
    config: JobConfig,
    uses_builtin_adapter: bool,
) -> None:
    mode = "visible_terminal" if config.debug_visible_terminal else "silent"
    _write_wrapper_log_preamble(stdout_path, mode=mode, cwd=directory, command_tokens=command_tokens)
    _write_wrapper_log_preamble(stderr_path, mode=mode, cwd=directory, command_tokens=command_tokens)
    _atomic_write_json(
        job_dir / "opencode_launch.json",
        {
            "launch_writer": "wrapper_prelaunch",
            "wrapper_started_at": _utcnow(),
            "wrapper_launch_status": "pending",
            "wrapper_launch_error": "",
            "provider_id": provider_id,
            "model_id": model_id,
            "working_directory": directory or "",
            "cwd": str(REPO_ROOT),
            "debug_visible_terminal": config.debug_visible_terminal,
            "debug_open_session_tui": config.debug_open_session_tui,
            "export_session": _normalize_export_session_mode(config.export_session),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "command_tokens": command_tokens,
            "command_display": _command_display(command_tokens),
            "uses_builtin_adapter": uses_builtin_adapter,
            "adapter_bootstrap_timeout_seconds": ADAPTER_BOOTSTRAP_TIMEOUT_SECONDS if uses_builtin_adapter else 0,
        },
    )


def _adapter_bootstrap_completed(job_dir: Path) -> bool:
    launch_data = _read_json_safe(job_dir / "opencode_launch.json")
    if isinstance(launch_data, dict) and str(launch_data.get("launch_writer", "")) == "adapter":
        return True
    return (job_dir / "opencode_input.md").exists() and (job_dir / "opencode_manual_command.txt").exists()


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


def _append_bootstrap_capture_excerpt(
    *,
    target_path: Path,
    bootstrap_path: Path,
    label: str,
    config: JobConfig,
) -> None:
    excerpt = _read_with_tail_max(bootstrap_path, config).strip()
    if not excerpt:
        return
    _append_text(
        target_path,
        f"\n[wrapper] {label} bootstrap capture:\n{excerpt}\n",
    )


def _is_log_preamble_only(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith("[wrapper]") or line.startswith("[adapter]") for line in lines)


def _derive_summary(status: str, result_path: Path, stderr_path: Path, stdout_path: Path, config: JobConfig) -> str:
    success_like = frozenset({STATUS_COMPLETED, STATUS_PARTIAL})
    if status in success_like:
        primary = result_path
        fallbacks = [stderr_path, stdout_path]
    else:
        primary = stderr_path
        fallbacks = [stdout_path, result_path]
    text = _read_with_tail_max(primary, config)
    if text.strip() and not _is_log_preamble_only(text):
        return text
    for fb in fallbacks:
        text = _read_with_tail_max(fb, config)
        if text.strip() and not _is_log_preamble_only(text):
            return text
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
    launch_writer = str(launch_data.get("launch_writer", "") or "")
    wrapper_launch_status = str(launch_data.get("wrapper_launch_status", "") or "")
    wrapper_launch_error = str(launch_data.get("wrapper_launch_error", "") or "")

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
    elif launch_writer == "wrapper_prelaunch" and wrapper_launch_status in {
        "adapter_bootstrap_timeout",
        "adapter_exited_without_bootstrap",
        "launch_failed",
    }:
        visible_status = "diagnostics_missing"
        visible_reason = wrapper_launch_error or "Adapter did not replace wrapper bootstrap diagnostics."
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
    elif launch_writer == "wrapper_prelaunch":
        open_tui_status = "diagnostics_missing"
        open_tui_reason = wrapper_launch_error or "Adapter did not replace wrapper bootstrap diagnostics."
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


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_hex(path.read_bytes())

ZWORKER_STATIC_MANUAL_URL = (
    "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/"
    "docs/zworker_external_agent_manual.md"
)
ZWORKER_REPO_NAVIGATION_URL = (
    "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/"
    "docs/zworker_repo_navigation.md"
)


@dataclass
class ZworkerPromptPackResult:
    mode: str = ZWORKER_MODE_PROMPT_PACK
    request_id: str = ""
    output_dir: str = ""
    artifacts: list[str] = field(default_factory=list)
    status: str = ""
    error: str = ""
    timings: dict[str, int] = field(default_factory=dict)
    prompt_lines: int = 0
    passport_lines: int = 0
    self_check_passed: bool = True
    self_check_errors: list[str] = field(default_factory=list)


@dataclass
class ZworkerUnpackResult:
    mode: str = ZWORKER_MODE_RESULT_UNPACK
    request_id: str = ""
    unpack_dir: str = ""
    verdict: str = ""
    status: str = ""
    error: str = ""
    answer_found: bool = False
    files_extracted: int = 0
    files_rejected: int = 0
    rejection_details: list[str] = field(default_factory=list)
    report_path: str = ""
    timings: dict[str, int] = field(default_factory=dict)


@dataclass
class ZworkerProcessResultResult:
    mode: str = ZWORKER_MODE_PROCESS_RESULT
    request_id: str = ""
    decision: str = ""
    status: str = ""
    error: str = ""
    answer_read: bool = False
    sources_report_found: bool = False
    sources_report_valid: bool = False
    sources_report_issues: list[str] = field(default_factory=list)
    repo_files_found: int = 0
    repo_files_in_scope: int = 0
    repo_files_out_of_scope: int = 0
    auto_applied: bool = False
    auto_apply_files: int = 0
    auto_apply_errors: list[str] = field(default_factory=list)
    requires_revision: bool = False
    requires_clarification: bool = False
    human_readable_summary: str = ""
    report_path: str = ""
    timings: dict[str, int] = field(default_factory=dict)


@dataclass
class ZworkerRevisionPromptResult:
    mode: str = ZWORKER_MODE_REVISION_PROMPT
    request_id: str = ""
    revision_name: str = ""
    revision_dir: str = ""
    revision_number: int = 0
    status: str = ""
    error: str = ""
    artifacts: list[str] = field(default_factory=list)
    prompt_lines: int = 0
    timings: dict[str, int] = field(default_factory=dict)



def _normalize_path_list(value: str | list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return [p.strip() for p in value.split(",") if p.strip()]
    if isinstance(value, list):
        result = [str(p).strip() for p in value if str(p).strip()]
        return result if result else None
    return None




ZWORKER_SELF_CHECK_INVARIANTS = {
    "no_file_uris": "file://",
    "no_windows_drives": r"[A-Za-z]:[/\\]",
    "manual_url_present": "zworker_external_agent_manual.md",
    "nav_url_present": "zworker_repo_navigation.md",
    "no_package_ready": "PACKAGE_READY",
    "no_contract_conflict": "CONTRACT_CONFLICT",
    "no_blocked_missing_context": "BLOCKED_MISSING_CONTEXT",
    "no_manifest_json": "manifest.json",
}


def _is_valid_external_https_url(url: str) -> tuple[bool, str]:
    url = url.strip()
    if not url:
        return False, "empty URL"
    if re.match(r"^file://", url, re.IGNORECASE):
        return False, f"file:// URI not allowed: {url}"
    if re.match(r"^[A-Za-z]:[/\\]", url):
        return False, f"Windows absolute path not allowed: {url}"
    if url.startswith("/"):
        return False, f"Unix absolute path not allowed: {url}"
    if url.startswith("./") or url.startswith("../"):
        return False, f"relative path not allowed: {url}"
    if url.startswith("\\\\"):
        return False, f"UNC path not allowed: {url}"
    if url.startswith("https://"):
        return True, ""
    if url.startswith("http://"):
        return False, f"non-HTTPS URL not allowed (only HTTPS): {url}"
    return False, f"not an absolute HTTPS URL: {url}"


def _zworker_validate_source_urls(urls: list[str]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for url in urls:
        valid, error = _is_valid_external_https_url(url)
        if not valid:
            errors.append(error)
    return len(errors) == 0, errors


def _zworker_prompt_self_check(
    prompt_text: str,
    manual_url: str,
    nav_url: str,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if manual_url not in prompt_text:
        errors.append(f"manual URL not found in prompt: {manual_url}")

    if nav_url not in prompt_text:
        errors.append(f"repo navigation URL not found in prompt: {nav_url}")

    lines = prompt_text.splitlines()
    in_files_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Files to read") or stripped.startswith("### Files to read"):
            in_files_section = True
            continue
        if in_files_section and stripped.startswith("##"):
            in_files_section = False
            continue
        if in_files_section and stripped.startswith("- "):
            url_candidate = stripped[2:].strip()
            if (
                url_candidate
                and url_candidate
                != "No specific repository files are required for this task."
                and not url_candidate.startswith("https://")
            ):
                errors.append(
                    f"non-HTTPS link in Files to read section: {url_candidate}"
                )

    if "file://" in prompt_text:
        errors.append("prompt contains file:// URI")

    if re.search(r"\]\(\.\./", prompt_text):
        errors.append("prompt contains Markdown relative link (](../ )")

    if re.search(r"\]\(\.\.\\", prompt_text):
        errors.append("prompt contains Markdown relative link (](..\\ )")

    if re.search(r"(?:^|\n|[ \t])\.\./", prompt_text):
        errors.append("prompt contains relative path ../ (may appear in links)")

    if re.search(r"(?:^|\n|[ \t])\.\.\\", prompt_text):
        errors.append("prompt contains relative path ..\\ (may appear in links)")

    if "C:/" in prompt_text:
        errors.append("prompt contains local path C:/")
    if "D:/" in prompt_text or "D:\\" in prompt_text:
        errors.append("prompt contains local path D:/")

    drive_matches = re.findall(r"\b[A-Za-z]:[/\\]", prompt_text)
    for match in drive_matches:
        errors.append(f"prompt contains Windows path: {match}")

    for forbidden in [
        "PACKAGE_READY",
        "CONTRACT_CONFLICT",
        "BLOCKED_MISSING_CONTEXT",
        "manifest.json",
        "checksums.sha256",
        "payload/",
    ]:
        if forbidden in prompt_text:
            errors.append(f"prompt contains forbidden text: {forbidden}")

    return len(errors) == 0, errors


def _zworker_task_to_slug(task: str) -> str:
    if _git_utils is not None:
        return _git_utils._task_text_to_slug(task)
    import re
    raw = task.strip().casefold()
    raw = re.sub(r"[^a-z0-9\s-]", "", raw)
    raw = re.sub(r"\s+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw)
    raw = raw.strip("-")
    if len(raw) > 48:
        raw = raw[:48].rstrip("-")
    if not raw:
        raw = "task"
    return raw


def _zworker_request_name(task: str | None = None) -> str:
    if _git_utils is not None:
        return _git_utils.zworker_request_name(task)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    slug = _zworker_task_to_slug(task) if task else "task"
    return f"ZWORKER-{ts}-{slug}"


def _zworker_request_name_is_valid(name: str) -> bool:
    if _git_utils is not None:
        return _git_utils.zworker_request_name_is_valid(name)
    import re
    return bool(re.match(r"^ZWORKER-\d{8}-\d{6}-[a-z0-9][a-z0-9-]*$", name))


def _zworker_revision_name(base_name: str, revision: int) -> str:
    if _git_utils is not None:
        return _git_utils.zworker_revision_name(base_name, revision)
    if revision < 2:
        raise ValueError("Revision must be >= 2")
    return f"{base_name}-ver{revision}"


def _zworker_validate_request_id_slug(request_id: str, task: str) -> tuple[bool, str]:
    if not request_id or not task:
        return True, ""
    task_slug = _zworker_task_to_slug(task)
    if not request_id.endswith(f"-{task_slug}") and not request_id.endswith(f"-{task_slug}-ver"):
        rev_match = bool(re.match(r"^ZWORKER-\d{8}-\d{6}-(.+?)-ver\d+$", request_id))
        if rev_match:
            return True, ""
        return False, (
            f"Request ID slug mismatch: request_id '{request_id}' does not match "
            f"task-derived slug '{task_slug}'. "
            f"Request ID must end with '-{task_slug}' (e.g. ZWORKER-YYYYMMDD-HHMMSS-{task_slug})."
        )
    return True, ""


def zworker_prompt_pack(
    task: str,
    *,
    output_dir: Path | None = None,
    context: str = "",
    constraints: str = "",
    request_id: str = "",
    source_urls: list[str] | None = None,
    allowed_paths: str | list[str] | None = None,
    forbidden_paths: str | list[str] | None = None,
    expected_outputs: str | list[str] | None = None,
) -> ZworkerPromptPackResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    normalized_task = task.strip() if task else "task"

    request_name = request_id if request_id else _zworker_request_name(normalized_task)

    if request_id:
        slug_ok, slug_err = _zworker_validate_request_id_slug(request_id, normalized_task)
        if not slug_ok:
            timings["prompt_pack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
            return ZworkerPromptPackResult(
                request_id=request_name,
                output_dir=str(output_dir) if output_dir else "",
                status="failed",
                error=slug_err,
                timings=timings,
            )

    if output_dir is None:
        output_dir = ZWORKER_RUNTIME_REQUESTS / request_name
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_urls = source_urls or []

    url_valid, url_errors = _zworker_validate_source_urls(resolved_urls)
    if not url_valid:
        timings["prompt_pack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZworkerPromptPackResult(
            request_id=request_name,
            output_dir=str(output_dir) if output_dir else "",
            status="failed",
            error="Source URL validation failed: " + "; ".join(url_errors),
            timings=timings,
            self_check_passed=False,
            self_check_errors=url_errors,
        )

    normalized_allowed = _normalize_path_list(allowed_paths) or []
    normalized_forbidden = _normalize_path_list(forbidden_paths) or []
    normalized_expected = _normalize_path_list(expected_outputs) or []

    branch_decision = _git_utils.resolve_branch_decision(source_urls=resolved_urls) if _git_utils else {"decision": "no_branch_needed", "reason": "", "create_branch": False}
    branch_may_be_needed = branch_decision.get("decision") == "branch_may_be_needed"
    branch_slug_id = ""
    branch_name = ""
    if branch_may_be_needed:
        branch_slug_id = hashlib.sha256(request_name.encode()).hexdigest()[:12]
        branch_name = _git_utils.zworker_context_branch_name(request_name) if _git_utils else f"zworker/context/{request_name}"

    try:
        now_utc = _utcnow()
        artifacts: list[str] = []

        manual_url = ZWORKER_STATIC_MANUAL_URL
        nav_url = ZWORKER_REPO_NAVIGATION_URL

        t_render_start = time.perf_counter_ns()

        files_to_read_block: str
        if resolved_urls:
            files_to_read_block = "\n".join(f"- {url}" for url in resolved_urls)
        else:
            files_to_read_block = (
                "No specific repository files are required for this task.\n"
                "Create a standalone result based on the task description."
            )

        prompt_template = (ZWORKER_TEMPLATE_DIR / "prompt.md").read_text(encoding="utf-8")
        prompt_content = prompt_template.replace("{request_id}", request_name)
        prompt_content = prompt_content.replace("{task}", normalized_task)
        prompt_content = prompt_content.replace("{context}", context or "No additional context provided.")
        prompt_content = prompt_content.replace("{manual_url}", manual_url)
        prompt_content = prompt_content.replace("{repo_navigation_url}", nav_url)
        prompt_content = prompt_content.replace("{files_to_read}", files_to_read_block)

        prompt_path = output_dir / "prompt.md"
        _atomic_write_text(prompt_path, prompt_content)
        artifacts.append("prompt.md")

        files_linked_block: str
        if resolved_urls:
            files_linked_block = "\n".join(f"- {url}" for url in resolved_urls)
        else:
            files_linked_block = "(none — standalone task)"

        passport_template = (ZWORKER_TEMPLATE_DIR / "prompt_passport.md").read_text(encoding="utf-8")
        passport_content = passport_template.replace("{request_id}", request_name)
        passport_content = passport_content.replace("{task}", normalized_task)
        passport_content = passport_content.replace("{prompt_path}", str(output_dir / "prompt.md"))
        passport_content = passport_content.replace("{manual_url}", manual_url)
        passport_content = passport_content.replace("{repo_navigation_url}", nav_url)
        passport_content = passport_content.replace("{files_linked}", files_linked_block)
        passport_path = output_dir / "prompt_passport.md"
        _atomic_write_text(passport_path, passport_content)
        artifacts.append("prompt_passport.md")

        timings["render_templates_ms"] = int((time.perf_counter_ns() - t_render_start) / 1_000_000)

        task_slug = _zworker_task_to_slug(normalized_task)
        manifest = {
            "request_id": request_name,
            "slug": task_slug,
            "task_summary": normalized_task[:200],
            "manual_url": manual_url,
            "repo_navigation_url": nav_url,
            "files_to_read": list(resolved_urls),
            "strict_zip_contract": False,
            "requires_answer_md": True,
            "created_at": now_utc,
            "allowed_paths": normalized_allowed,
            "forbidden_paths": normalized_forbidden,
            "expected_outputs": normalized_expected,
            "auto_apply_enabled": True,
            "branch_may_be_needed": branch_may_be_needed,
            "create_branch": False,
            "branch_slug_id": branch_slug_id,
            "branch_name": branch_name,
        }
        manifest_path = output_dir / "request_manifest.json"
        _atomic_write_json(manifest_path, manifest)
        artifacts.append("request_manifest.json")

        prompt_lines = prompt_content.count("\n") + 1
        passport_lines = passport_content.count("\n") + 1
        timings["prompt_pack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

        self_check_ok, self_check_errors = _zworker_prompt_self_check(
            prompt_content, manual_url, nav_url
        )

        return ZworkerPromptPackResult(
            request_id=request_name,
            output_dir=str(output_dir),
            artifacts=artifacts,
            status="completed",
            timings=timings,
            prompt_lines=prompt_lines,
            passport_lines=passport_lines,
            self_check_passed=self_check_ok,
            self_check_errors=self_check_errors,
        )
    except Exception as e:
        timings["prompt_pack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZworkerPromptPackResult(
            request_id=request_name,
            output_dir=str(output_dir) if output_dir else "",
            status="failed",
            error=f"{type(e).__name__}: {e}",
            timings=timings,
            self_check_passed=False,
            self_check_errors=[f"{type(e).__name__}: {e}"],
        )


def zworker_result_unpack(
    zip_path: Path,
    *,
    request_id: str = "",
    target_root: Path | None = None,
) -> ZworkerUnpackResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    if target_root is None:
        target_root = REPO_ROOT
    target_root = target_root.resolve(strict=True)

    if not zip_path.exists():
        return ZworkerUnpackResult(
            request_id=request_id,
            verdict="rejected_structural",
            status="failed",
            error=f"ZIP file not found: {zip_path}",
            timings=timings,
        )

    if not request_id:
        request_id = f"unpack-{uuid.uuid4().hex[:12]}"

    inbox_dir = ZWORKER_RUNTIME_INBOX / request_id
    inbox_dir.mkdir(parents=True, exist_ok=True)

    report_path = inbox_dir / "unpack_report.md"

    forbidden_prefixes = frozenset({
        ".git/", ".ai/zworker/runtime/", ".ai/zchat/runtime/",
    })

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zip_entries = [info.filename.replace("\\", "/") for info in zf.infolist() if not info.is_dir()]
        timings["unpack_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
    except zipfile.BadZipFile as e:
        timings["unpack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZworkerUnpackResult(
            request_id=request_id,
            verdict="rejected_structural",
            status="failed",
            error=f"Bad ZIP file: {e}",
            timings=timings,
        )

    files_extracted = 0
    files_rejected = 0
    rejection_details: list[str] = []
    answer_found = False

    for entry in zip_entries:
        normalized = entry.replace("\\", "/")
        if not normalized:
            continue

        if re.match(r"^[A-Za-z]:[/\\]", normalized) or normalized.startswith("/"):
            files_rejected += 1
            rejection_details.append(f"Absolute path rejected: {entry}")
            continue

        normalized = normalized.lstrip("/")

        if ".." in Path(normalized).parts:
            files_rejected += 1
            rejection_details.append(f"Path traversal rejected: {entry}")
            continue

        for prefix in forbidden_prefixes:
            if normalized.startswith(prefix):
                files_rejected += 1
                rejection_details.append(f"Forbidden prefix '{prefix}' rejected: {entry}")
                break
        else:
            resolved = (target_root / normalized).resolve(strict=False)
            try:
                resolved.relative_to(target_root)
            except ValueError:
                files_rejected += 1
                rejection_details.append(f"Path escapes repository root: {entry}")
                continue

            if normalized == "answer.md":
                answer_found = True

            dest_path = inbox_dir / normalized
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                dest_path.write_bytes(zf.read(entry))
            files_extracted += 1

    timings["unpack_extract_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

    if not answer_found:
        verdict = "accepted_missing_answer"
    elif files_rejected > 0:
        verdict = "accepted_with_warnings"
    else:
        verdict = "accepted"

    report_lines = [
        "# Zworker Unpack Report",
        "",
        f"- **Request ID**: `{request_id}`",
        f"- **ZIP**: `{zip_path}`",
        f"- **Unpack directory**: `{inbox_dir}`",
        f"- **Verdict**: {verdict}",
        "",
        f"## Summary",
        f"- Files extracted: {files_extracted}",
        f"- Files rejected: {files_rejected}",
        f"- answer.md found: {answer_found}",
        "",
    ]

    if rejection_details:
        report_lines.append("### Rejection Details")
        for detail in rejection_details:
            report_lines.append(f"- {detail}")
        report_lines.append("")

    if not answer_found:
        report_lines.append("### NOTE: answer.md not found in ZIP root")
        report_lines.append("The result is technically unpacked but marked as requiring revision (missing answer.md).")

    report_lines.append("")
    _atomic_write_text(report_path, "\n".join(report_lines))

    timings["unpack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

    return ZworkerUnpackResult(
        request_id=request_id,
        unpack_dir=str(inbox_dir),
        verdict=verdict,
        status="completed",
        answer_found=answer_found,
        files_extracted=files_extracted,
        files_rejected=files_rejected,
        rejection_details=rejection_details,
        report_path=str(report_path),
        timings=timings,
    )


ZWORKER_SOURCES_REPORT_REQUIRED_SECTIONS = frozenset({
    "Sources Read Report",
    "Read fully",
    "Read partially",
    "Not read",
    "External search used",
})


def _zworker_validate_sources_read_report(content: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if "Sources Read Report" not in content:
        issues.append("Missing 'Sources Read Report' section")
    if "Read fully" not in content:
        issues.append("Missing 'Read fully' subsection")
    if "Read partially" not in content:
        issues.append("Missing 'Read partially' subsection")
    if "Not read" not in content:
        issues.append("Missing 'Not read' subsection")
    if "External search used" not in content:
        issues.append("Missing 'External search used' subsection")
    return len(issues) == 0, issues


def _zworker_is_repo_candidate(path: Path, relative: str) -> bool:
    name = relative.replace("\\", "/")
    return name not in {"answer.md", "unpack_report.md", "process_report.md"} and not name.startswith("__")


def _zworker_file_in_scope(path: str, manifest: dict) -> tuple[bool, str]:
    allowed = manifest.get("allowed_paths", []) or []
    forbidden = manifest.get("forbidden_paths", []) or []
    task_scope_hints = manifest.get("task_scope_hints", []) or []

    normalized = path.replace("\\", "/")

    for fp in forbidden:
        if normalized.startswith(fp.replace("\\", "/")):
            return False, f"Matches forbidden_path '{fp}'"

    scopes = list(allowed)
    if task_scope_hints:
        scopes = scopes + list(task_scope_hints)

    if not scopes:
        return True, "No scope constraints defined, accepted by default"

    for scope in scopes:
        scope_norm = scope.replace("\\", "/").rstrip("/")
        if normalized.startswith(scope_norm + "/") or normalized == scope_norm or scope_norm == "" or scope_norm == "*":
            return True, f"Within scope '{scope}'"

    return False, f"Not within any allowed scope: {scopes}"


def _zworker_resolve_request_dir(request_id: str) -> Path | None:
    candidate = ZWORKER_RUNTIME_REQUESTS / request_id
    if candidate.exists():
        return candidate

    if ZWORKER_RUNTIME_REQUESTS.exists():
        for child in ZWORKER_RUNTIME_REQUESTS.iterdir():
            if child.is_dir() and child.name == request_id:
                return child

    return None


def zworker_process_result(
    request_id: str,
    *,
    unpack_dir: Path | None = None,
    target_root: Path | None = None,
) -> ZworkerProcessResultResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    if target_root is None:
        target_root = REPO_ROOT
    target_root = target_root.resolve(strict=True)

    if unpack_dir is None:
        unpack_dir = ZWORKER_RUNTIME_INBOX / request_id

    unpack_dir = unpack_dir.resolve(strict=False)
    if not unpack_dir.exists():
        return ZworkerProcessResultResult(
            request_id=request_id,
            decision="needs_revision",
            status="failed",
            error=f"Unpack directory not found: {unpack_dir}",
            requires_revision=True,
            human_readable_summary=f"Unpack directory not found: {unpack_dir}",
            timings=timings,
        )

    report_path = unpack_dir / "process_report.md"

    t_answer_start = time.perf_counter_ns()
    answer_path = unpack_dir / "answer.md"
    answer_read = False
    answer_content = ""
    if answer_path.exists():
        try:
            answer_content = answer_path.read_text(encoding="utf-8-sig", errors="replace")
            answer_read = True
        except OSError:
            pass
    timings["process_answer_ms"] = int((time.perf_counter_ns() - t_answer_start) / 1_000_000)

    t_sources_start = time.perf_counter_ns()
    sources_report_found = False
    sources_report_valid = False
    sources_report_issues: list[str] = []
    if answer_content:
        sources_report_found = "Sources Read Report" in answer_content
        if sources_report_found:
            sources_report_valid, sources_report_issues = _zworker_validate_sources_read_report(answer_content)
        else:
            sources_report_issues.append("Sources Read Report section not found in answer.md")
    timings["process_sources_check_ms"] = int((time.perf_counter_ns() - t_sources_start) / 1_000_000)

    t_scope_start = time.perf_counter_ns()
    manifest: dict = {}
    request_dir = _zworker_resolve_request_dir(request_id)
    if request_dir is not None:
        manifest_path = request_dir / "request_manifest.json"
        if manifest_path.exists():
            manifest = _read_json_safe(manifest_path) or {}
    timings["process_manifest_ms"] = int((time.perf_counter_ns() - t_scope_start) / 1_000_000)

    t_files_start = time.perf_counter_ns()
    repo_files_found = 0
    repo_files_in_scope = 0
    repo_files_out_of_scope = 0
    out_of_scope_details: list[str] = []
    in_scope_files: list[tuple[Path, str]] = []

    for entry in sorted(unpack_dir.rglob("*")):
        if entry.is_file():
            rel = str(entry.relative_to(unpack_dir)).replace("\\", "/")
            if _zworker_is_repo_candidate(entry, rel):
                repo_files_found += 1
                in_scope, reason = _zworker_file_in_scope(rel, manifest)
                if in_scope:
                    repo_files_in_scope += 1
                    in_scope_files.append((entry, rel))
                else:
                    repo_files_out_of_scope += 1
                    out_of_scope_details.append(f"{rel}: {reason}")
    timings["process_files_scan_ms"] = int((time.perf_counter_ns() - t_files_start) / 1_000_000)

    auto_applied = False
    auto_apply_files = 0
    auto_apply_errors: list[str] = []
    requires_revision = False
    requires_clarification = False
    decision = "needs_revision"

    auto_apply_enabled = manifest.get("auto_apply_enabled", True)
    if isinstance(auto_apply_enabled, str):
        auto_apply_enabled = auto_apply_enabled.lower() in {"true", "1", "yes"}

    if not answer_read:
        requires_revision = True
        decision = "needs_revision"
        human_readable = (
            f"## Process Result: REVISION REQUIRED\n\n"
            f"**Reason**: answer.md not found in unpack directory `{unpack_dir}`.\n"
            f"The external agent must include answer.md at the root of the ZIP.\n"
            f"Request a revision with `zworker_revision_prompt`.\n"
        )
    elif repo_files_out_of_scope > 0 and auto_apply_enabled:
        requires_clarification = True
        decision = "needs_clarification"
        oos_text = "\n".join(f"- {detail}" for detail in out_of_scope_details)
        human_readable = (
            f"## Process Result: CLARIFICATION REQUIRED\n\n"
            f"**Reason**: {repo_files_out_of_scope} file(s) are out of scope and auto-apply is blocked.\n\n"
            f"### In-scope files: {repo_files_in_scope}\n"
            f"### Out-of-scope files:\n{oos_text}\n\n"
            f"### answer.md\n- Sources Read Report: {'valid' if sources_report_valid else 'issues found'}\n"
            f"- answer.md read: yes\n\n"
            f"**Manual review is needed before applying.**\n"
            f"Review the unpacked files at `{unpack_dir}` and decide whether to apply or request revision.\n"
        )
    elif repo_files_out_of_scope > 0 and not auto_apply_enabled:
        requires_clarification = True
        decision = "needs_clarification"
        human_readable = (
            f"## Process Result: CLARIFICATION REQUIRED\n\n"
            f"**Reason**: {repo_files_out_of_scope} file(s) are out of scope and auto_apply_enabled is false.\n"
            f"Manual review is required.\n"
        )
    elif repo_files_in_scope > 0 and auto_apply_enabled:
        t_apply_start = time.perf_counter_ns()
        for file_path, rel_path in in_scope_files:
            try:
                dest = target_root / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(file_path.read_bytes())
                auto_apply_files += 1
            except OSError as e:
                auto_apply_errors.append(f"Failed to write {rel_path}: {e}")
        timings["process_apply_ms"] = int((time.perf_counter_ns() - t_apply_start) / 1_000_000)

        if auto_apply_errors:
            decision = "needs_revision"
            requires_revision = True
            err_text = "\n".join(f"- {e}" for e in auto_apply_errors)
            human_readable = (
                f"## Process Result: FAILED\n\n"
                f"**Reason**: {len(auto_apply_errors)} write error(s) during auto-apply.\n\n"
                f"### Errors\n{err_text}\n\n"
                f"### Files applied before failure: {auto_apply_files}\n"
                f"Request a revision with `zworker_revision_prompt`.\n"
            )
        else:
            auto_applied = True
            decision = "accepted"
            applied_list = "\n".join(f"- `{rel}`" for _, rel in in_scope_files)
            if not sources_report_found:
                sources_note = (
                    "**Note**: answer.md found and read but no Sources Read Report section was found. "
                    "Consider requesting a revision if source traceability matters."
                )
            elif not sources_report_valid:
                issues_text = "; ".join(sources_report_issues)
                sources_note = (
                    f"**Note**: Sources Read Report found but incomplete ({issues_text}). "
                    f"Consider requesting a revision if source traceability matters."
                )
            else:
                sources_note = "Sources Read Report: valid"
            human_readable = (
                f"## Process Result: ACCEPTED\n\n"
                f"All {auto_apply_files} in-scope file(s) applied automatically.\n\n"
                f"### Applied Files\n{applied_list}\n\n"
                f"### answer.md\n- {sources_note}\n"
                f"- answer.md read: yes\n"
            )
    else:
        expected = manifest.get("expected_outputs", []) or []
        allowed = manifest.get("allowed_paths", []) or []
        is_informational = not expected and not allowed

        if repo_files_found == 0 and is_informational:
            auto_applied = True
            decision = "accepted"
            if not sources_report_found:
                sources_note = (
                    "**Note**: answer.md found and read but no Sources Read Report section was found. "
                    "Consider requesting a revision if source traceability matters."
                )
            elif not sources_report_valid:
                issues_text = "; ".join(sources_report_issues)
                sources_note = (
                    f"**Note**: Sources Read Report found but incomplete ({issues_text}). "
                    f"Consider requesting a revision if source traceability matters."
                )
            else:
                sources_note = "Sources Read Report: valid"
            human_readable = (
                f"## Process Result: ACCEPTED (INFORMATIONAL)\n\n"
                f"**Reason**: Answer-only informational task. No repo files expected.\n\n"
                f"### answer.md\n- {sources_note}\n"
                f"- answer.md read: yes\n"
            )
        elif not auto_apply_enabled:
            decision = "needs_clarification"
            requires_clarification = True
            human_readable = (
                f"## Process Result: CLARIFICATION REQUIRED\n\n"
                f"**Reason**: auto_apply_enabled is false and no auto-apply was performed.\n"
                f"answer.md was read. Sources Read Report is valid. No out-of-scope files.\n"
                f"Manual review is needed.\n"
            )
        else:
            requires_revision = True
            decision = "needs_revision"
            human_readable = (
                f"## Process Result: REVISION REQUIRED\n\n"
                f"**Reason**: No repo-candidate files found in unpack directory.\n"
                f"answer.md was read. No files to auto-apply.\n"
                f"Request a revision with `zworker_revision_prompt`.\n"
            )

    report_lines = [
        "# Zworker Process Result Report",
        "",
        f"- **Request ID**: `{request_id}`",
        f"- **Unpack directory**: `{unpack_dir}`",
        f"- **Decision**: {decision}",
        f"- **Time**: {_utcnow()}",
        "",
        human_readable,
        "",
        "### Timings",
    ]
    for k, v in timings.items():
        report_lines.append(f"- **{k}**: {v} ms")
    report_lines.append("")

    _atomic_write_text(report_path, "\n".join(report_lines))

    timings["process_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

    return ZworkerProcessResultResult(
        request_id=request_id,
        decision=decision,
        status="completed",
        answer_read=answer_read,
        sources_report_found=sources_report_found,
        sources_report_valid=sources_report_valid,
        sources_report_issues=sources_report_issues,
        repo_files_found=repo_files_found,
        repo_files_in_scope=repo_files_in_scope,
        repo_files_out_of_scope=repo_files_out_of_scope,
        auto_applied=auto_applied,
        auto_apply_files=auto_apply_files,
        auto_apply_errors=auto_apply_errors,
        requires_revision=requires_revision,
        requires_clarification=requires_clarification,
        human_readable_summary=human_readable,
        report_path=str(report_path),
        timings=timings,
    )


def zworker_revision_prompt(
    request_id: str,
    *,
    feedback: str = "",
    revision_number: int = 0,
    manifest_dir: Path | None = None,
) -> ZworkerRevisionPromptResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    if not request_id:
        return ZworkerRevisionPromptResult(
            status="failed",
            error="request_id is required",
            timings=timings,
        )

    if revision_number < 2:
        inbox_dir = ZWORKER_RUNTIME_INBOX / request_id
        existing_revisions: list[int] = []
        if (ZWORKER_RUNTIME_REVISIONS).exists():
            for child in sorted(ZWORKER_RUNTIME_REVISIONS.iterdir()):
                if child.is_dir() and child.name.startswith(f"{request_id}-ver"):
                    try:
                        ver_str = child.name.rsplit("ver", 1)[1]
                        existing_revisions.append(int(ver_str))
                    except (ValueError, IndexError):
                        pass
        revision_number = max(existing_revisions) + 1 if existing_revisions else 2

    revision_name = _zworker_revision_name(request_id, revision_number)
    revision_dir = ZWORKER_RUNTIME_REVISIONS / revision_name
    revision_dir.mkdir(parents=True, exist_ok=True)

    if manifest_dir is None:
        manifest_dir = _zworker_resolve_request_dir(request_id)
    if manifest_dir is None:
        manifest_dir = ZWORKER_RUNTIME_REQUESTS / request_id

    original_task = ""
    original_context = ""
    request_manifest: dict = {}
    manifest_path = manifest_dir / "request_manifest.json" if manifest_dir else None
    if manifest_path and manifest_path.exists():
        try:
            request_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            pass

    original_prompt_path = manifest_dir / "prompt.md" if manifest_dir else None
    if original_prompt_path and original_prompt_path.exists():
        try:
            original_task = original_prompt_path.read_text(encoding="utf-8")
        except OSError:
            pass

    process_report_path = ZWORKER_RUNTIME_INBOX / request_id / "process_report.md"
    process_summary = ""
    if process_report_path.exists():
        try:
            process_summary = process_report_path.read_text(encoding="utf-8")
        except OSError:
            pass

    artifacts: list[str] = []

    prompt_lines_list = [
        f"# Zworker Revision Prompt - {revision_name}",
        "",
        f"## Original Request: {request_id}",
        "",
        f"**Revision**: ver{revision_number}",
        f"**Generated**: {_utcnow()}",
        "",
        "## What was good",
        "",
        feedback if feedback else "(No specific feedback provided.)",
        "",
        "## What to fix / improve",
        "",
        "1. Ensure answer.md is at the root of the ZIP and complete.",
        "2. Describe which sources were read (it helps traceability — include Read fully, Read partially, Not read, External search used if applicable).",
        "3. All repo files must be within the allowed scope.",
        "4. Do NOT include files in .git/, .ai/zworker/runtime/, or .ai/zchat/runtime/.",
        "5. Use repo-relative paths directly at ZIP root (no payload/ directory).",
        "",
        "## Must include in the ZIP",
        "",
        "- `answer.md` at ZIP root (REQUIRED)",
        "- Sources description in answer.md (recommended for traceability)",
        "",
    ]

    if process_summary:
        prompt_lines_list.append("## Previous Process Result")
        prompt_lines_list.append("")
        prompt_lines_list.append("```")
        prompt_lines_list.append(process_summary[:3000])
        if len(process_summary) > 3000:
            prompt_lines_list.append("...(truncated)")
        prompt_lines_list.append("```")
        prompt_lines_list.append("")

    prompt_lines_list.append("## Original Task")
    prompt_lines_list.append("")
    prompt_lines_list.append(f"{original_task[:2000] if original_task else '(Original task not available, re-request if needed)'}")
    prompt_lines_list.append("")

    prompt_text = "\n".join(prompt_lines_list)
    prompt_path = revision_dir / "revision_prompt.md"
    _atomic_write_text(prompt_path, prompt_text)
    artifacts.append("revision_prompt.md")

    revision_manifest = {
        "manifest_version": "1.0",
        "revision_name": revision_name,
        "original_request_id": request_id,
        "revision_number": revision_number,
        "created_at": _utcnow(),
        "mode": ZWORKER_MODE_REVISION_PROMPT,
        "feedback": feedback,
    }
    manifest_out = revision_dir / "revision_manifest.json"
    _atomic_write_json(manifest_out, revision_manifest)
    artifacts.append("revision_manifest.json")

    prompt_lines = prompt_text.count("\n") + 1
    timings["revision_prompt_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

    return ZworkerRevisionPromptResult(
        request_id=request_id,
        revision_name=revision_name,
        revision_dir=str(revision_dir),
        revision_number=revision_number,
        status="completed",
        artifacts=artifacts,
        prompt_lines=prompt_lines,
        timings=timings,
    )


def _resolve_route_c_profile(config: JobConfig) -> dict[str, Any]:
    profile_name = (config.route_c_profile or "").strip()
    if not profile_name:
        return {
            "provider_id": config.provider_id,
            "model_id": config.model_id,
            "route_c_profile": "",
            "route_c_profile_account_id": "",
            "route_c_profile_account_index": -1,
            "route_c_profile_state_file": None,
            "route_c_profile_accounts_count": 0,
            "quota_cooldown_seconds": 0,
            "timeout_cooldown_seconds": 0,
            "timeout_cooldown_after_failures": 0,
            "immediate_retry_attempts": 0,
        }

    profile_cfg = config.route_c_profiles.get(profile_name)
    if not isinstance(profile_cfg, dict):
        return {
            "provider_id": config.provider_id,
            "model_id": config.model_id,
            "route_c_profile": profile_name,
            "route_c_profile_account_id": "",
            "route_c_profile_account_index": -1,
            "route_c_profile_state_file": None,
            "route_c_profile_accounts_count": 0,
            "quota_cooldown_seconds": 0,
            "timeout_cooldown_seconds": 0,
            "timeout_cooldown_after_failures": 0,
            "immediate_retry_attempts": 0,
        }

    accounts = profile_cfg.get("accounts")
    state_rel = profile_cfg.get("state_file", "")
    if not accounts or not isinstance(accounts, list) or not state_rel:
        return {
            "provider_id": config.provider_id,
            "model_id": config.model_id,
            "route_c_profile": profile_name,
            "route_c_profile_account_id": "",
            "route_c_profile_account_index": -1,
            "route_c_profile_state_file": None,
            "route_c_profile_accounts_count": 0,
            "quota_cooldown_seconds": 0,
            "timeout_cooldown_seconds": 0,
            "timeout_cooldown_after_failures": 0,
            "immediate_retry_attempts": 0,
        }

    import codex_token_monitor_route_c_round_robin as round_robin
    state_file = REPO_ROOT / state_rel
    reservation = round_robin.reserve_next_account(
        accounts=accounts,
        state_file=state_file,
    )

    return {
        "provider_id": reservation["provider_id"],
        "model_id": reservation["model_id"],
        "route_c_profile": profile_name,
        "route_c_profile_account_id": reservation["account_id"],
        "route_c_profile_account_index": int(reservation["index"]),
        "route_c_profile_state_file": state_file,
        "route_c_profile_accounts_count": len(accounts),
        "quota_cooldown_seconds": _normalize_positive_int(
            profile_cfg.get("quota_cooldown_seconds"),
            default=12 * 60 * 60,
        ),
        "timeout_cooldown_seconds": _normalize_positive_int(
            profile_cfg.get("timeout_cooldown_seconds"),
            default=30 * 60,
        ),
        "timeout_cooldown_after_failures": _normalize_positive_int(
            profile_cfg.get("timeout_cooldown_after_failures"),
            default=2,
            minimum=1,
        ),
        "immediate_retry_attempts": _normalize_positive_int(
            profile_cfg.get("immediate_retry_attempts"),
            default=max(len(accounts) - 1, 0),
        ),
    }


def _read_text_if_exists(path_value: str | Path | None) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _collect_route_c_failure_text(result: JobResult) -> str:
    parts = [
        result.reason,
        result.summary,
        _read_text_if_exists(result.stderr_path),
        _read_text_if_exists(result.stdout_path),
        _read_text_if_exists(result.result_path),
    ]
    return "\n".join(part for part in parts if part).lower()


def _classify_route_c_result(result: JobResult, route_c_resolved: dict[str, Any]) -> dict[str, Any]:
    if result.status in {STATUS_COMPLETED, STATUS_PARTIAL}:
        return {
            "category": "success",
            "retry_now": False,
            "timed_out": False,
            "cooldown_seconds": 0,
            "summary": "",
        }

    failure_text = _collect_route_c_failure_text(result)
    quota_hit = any(hint in failure_text for hint in ROUTE_C_QUOTA_HINTS)
    timed_out = bool(result.timed_out) or str(result.reason).strip() == "timed_out"

    if quota_hit:
        return {
            "category": "quota_exhausted",
            "retry_now": True,
            "timed_out": False,
            "cooldown_seconds": int(route_c_resolved.get("quota_cooldown_seconds", 0) or 0),
            "summary": "quota or rate-limit signal detected",
        }

    reason = str(result.reason or "").strip().lower()
    retryable_reason = any(hint in reason for hint in ROUTE_C_RETRYABLE_REASON_HINTS)
    if timed_out:
        return {
            "category": "timed_out",
            "retry_now": False,
            "timed_out": True,
            "cooldown_seconds": 0,
            "summary": "task timed out",
        }
    if retryable_reason:
        return {
            "category": "retryable_failure",
            "retry_now": False,
            "timed_out": False,
            "cooldown_seconds": 0,
            "summary": "retryable adapter failure without explicit quota signal",
        }
    return {
        "category": "failure",
        "retry_now": False,
        "timed_out": False,
        "cooldown_seconds": 0,
        "summary": "non-retryable failure",
    }


def _record_route_c_result(result: JobResult, route_c_resolved: dict[str, Any]) -> dict[str, Any]:
    state_file = route_c_resolved.get("route_c_profile_state_file")
    account_id = str(route_c_resolved.get("route_c_profile_account_id", "") or "")
    if not state_file or not account_id:
        return {
            "category": "no_profile_state",
            "retry_now": False,
            "timed_out": False,
            "cooldown_seconds": 0,
            "summary": "",
            "cooldown_applied": False,
        }

    import codex_token_monitor_route_c_round_robin as round_robin

    outcome = _classify_route_c_result(result, route_c_resolved)
    if outcome["category"] == "success":
        round_robin.record_account_success(
            state_file=Path(state_file),
            account_id=account_id,
        )
        outcome["cooldown_applied"] = False
        return outcome

    failure_meta = round_robin.record_account_failure(
        state_file=Path(state_file),
        account_id=account_id,
        category=str(outcome["category"]),
        reason=result.reason,
        summary=result.summary,
        timed_out=bool(outcome["timed_out"]),
        cooldown_seconds=int(outcome["cooldown_seconds"]),
        timeout_cooldown_seconds=int(route_c_resolved.get("timeout_cooldown_seconds", 0) or 0),
        timeout_cooldown_after_failures=int(
            route_c_resolved.get("timeout_cooldown_after_failures", 0) or 0
        ),
    )
    outcome.update(failure_meta)
    return outcome


def _run_single_opencode_job(
    task_text: str,
    *,
    config: JobConfig,
    config_root: Path | None = None,
    directory: str | None = None,
    route_c_resolved: dict[str, Any] | None = None,
) -> JobResult:
    job_id = str(uuid.uuid4())
    if route_c_resolved is None:
        route_c_resolved = _resolve_route_c_profile(config)
    provider_id = route_c_resolved["provider_id"]
    model_id = route_c_resolved["model_id"]
    route_c_profile = route_c_resolved["route_c_profile"]
    route_c_profile_account_id = route_c_resolved["route_c_profile_account_id"]
    route_c_profile_account_index = route_c_resolved["route_c_profile_account_index"]

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
    bootstrap_stdout_path = job_dir / "adapter_bootstrap_stdout.log"
    bootstrap_stderr_path = job_dir / "adapter_bootstrap_stderr.log"
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
            route_c_profile=route_c_profile,
            route_c_profile_account_id=route_c_profile_account_id,
            route_c_profile_account_index=route_c_profile_account_index,
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
    uses_builtin_adapter = _command_uses_builtin_adapter(command_tokens)
    _write_wrapper_bootstrap_artifacts(
        job_dir=job_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        command_tokens=command_tokens,
        directory=directory,
        provider_id=provider_id,
        model_id=model_id,
        config=config,
        uses_builtin_adapter=uses_builtin_adapter,
    )
    if uses_builtin_adapter:
        _update_launch_artifact(
            job_dir,
            adapter_bootstrap_stdout_path=str(bootstrap_stdout_path),
            adapter_bootstrap_stderr_path=str(bootstrap_stderr_path),
        )

    stdout_handle = None
    stderr_handle = None
    process_pid: int | None = None
    process_launch_error = ""
    try:
        popen_kwargs: dict[str, Any] = {
            "shell": False,
            "cwd": str(REPO_ROOT),
            # The MCP host itself is stdio-driven. Explicitly detach child stdin
            # so adapter startup does not depend on inherited transport handles.
            "stdin": subprocess.DEVNULL,
        }
        if config.debug_visible_terminal and sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        elif uses_builtin_adapter:
            stdout_handle = open(bootstrap_stdout_path, "a", encoding="utf-8")
            stderr_handle = open(bootstrap_stderr_path, "a", encoding="utf-8")
            popen_kwargs["stdout"] = stdout_handle
            popen_kwargs["stderr"] = stderr_handle
        else:
            stdout_handle = open(stdout_path, "a", encoding="utf-8")
            stderr_handle = open(stderr_path, "a", encoding="utf-8")
            popen_kwargs["stdout"] = stdout_handle
            popen_kwargs["stderr"] = stderr_handle
        process = subprocess.Popen(command_tokens, **popen_kwargs)
        process_pid = process.pid
        _update_launch_artifact(
            job_dir,
            wrapper_launch_status="started",
            wrapper_launch_error="",
            wrapper_process_pid=process_pid,
        )
    except OSError as e:
        process_launch_error = f"Failed to launch process: {e}"
        _append_text(stderr_path, f"[wrapper] {process_launch_error}\n")
        _update_launch_artifact(
            job_dir,
            wrapper_launch_status="launch_failed",
            wrapper_launch_error=process_launch_error,
            wrapper_process_pid=None,
        )
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
            route_c_profile=route_c_profile,
            route_c_profile_account_id=route_c_profile_account_id,
            route_c_profile_account_index=route_c_profile_account_index,
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
    adapter_bootstrap_failed = False
    adapter_bootstrap_reason = ""
    poll_interval = config.poll_interval_ms / 1000.0
    deadline = time.monotonic() + config.timeout_seconds
    bootstrap_deadline = (
        time.monotonic() + min(ADAPTER_BOOTSTRAP_TIMEOUT_SECONDS, max(config.timeout_seconds, 1))
        if uses_builtin_adapter
        else None
    )

    while time.monotonic() < deadline:
        ret = process.poll()
        if ret is not None:
            break
        if bootstrap_deadline is not None and time.monotonic() >= bootstrap_deadline and not _adapter_bootstrap_completed(job_dir):
            adapter_bootstrap_failed = True
            adapter_bootstrap_reason = "adapter_bootstrap_timeout"
            message = (
                f"[wrapper] adapter bootstrap timed out after {ADAPTER_BOOTSTRAP_TIMEOUT_SECONDS}s "
                "before writing adapter launch artifacts.\n"
            )
            _append_text(stderr_path, message)
            _update_launch_artifact(
                job_dir,
                wrapper_launch_status="adapter_bootstrap_timeout",
                wrapper_launch_error=message.strip(),
            )
            _terminate_process_tree(process.pid)
            try:
                process.wait(timeout=30)
            except Exception:
                pass
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

    if adapter_bootstrap_failed:
        _append_bootstrap_capture_excerpt(
            target_path=stdout_path,
            bootstrap_path=bootstrap_stdout_path,
            label="stdout",
            config=config,
        )
        _append_bootstrap_capture_excerpt(
            target_path=stderr_path,
            bootstrap_path=bootstrap_stderr_path,
            label="stderr",
            config=config,
        )
        status = STATUS_FAILED
        reason = adapter_bootstrap_reason
        summary = _derive_summary(status, result_path, stderr_path, stdout_path, config)
        _atomic_write_text(result_path, "# Job Failed\n\n**Reason:** adapter_bootstrap_timeout\n")
    elif protocol_violation:
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
        if uses_builtin_adapter and not _adapter_bootstrap_completed(job_dir):
            _append_bootstrap_capture_excerpt(
                target_path=stdout_path,
                bootstrap_path=bootstrap_stdout_path,
                label="stdout",
                config=config,
            )
            _append_bootstrap_capture_excerpt(
                target_path=stderr_path,
                bootstrap_path=bootstrap_stderr_path,
                label="stderr",
                config=config,
            )
            reason = "adapter_exited_without_bootstrap"
            _append_text(stderr_path, "[wrapper] adapter exited before writing adapter launch artifacts.\n")
            _update_launch_artifact(
                job_dir,
                wrapper_launch_status="adapter_exited_without_bootstrap",
                wrapper_launch_error="Adapter exited before writing adapter launch artifacts.",
            )
        else:
            reason = "process_exited_without_done"
        summary = _derive_summary(status, result_path, stderr_path, stdout_path, config)
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** {reason}\n")
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
        route_c_profile=route_c_profile,
        route_c_profile_account_id=route_c_profile_account_id,
        route_c_profile_account_index=route_c_profile_account_index,
        **debug_metadata,
    )

    _atomic_write_json(done_path, asdict(result))

    return result


def run_opencode_job(
    task_text: str,
    *,
    config: JobConfig,
    config_root: Path | None = None,
    directory: str | None = None,
) -> JobResult:
    route_c_profile = (config.route_c_profile or "").strip()
    if not route_c_profile:
        return _run_single_opencode_job(
            task_text,
            config=config,
            config_root=config_root,
            directory=directory,
            route_c_resolved=None,
        )

    attempts = 0
    retry_limit = 0

    while True:
        route_c_resolved = _resolve_route_c_profile(config)
        retry_limit = int(route_c_resolved.get("immediate_retry_attempts", 0) or 0)
        result = _run_single_opencode_job(
            task_text,
            config=config,
            config_root=config_root,
            directory=directory,
            route_c_resolved=route_c_resolved,
        )
        outcome = _record_route_c_result(result, route_c_resolved)
        attempts += 1

        if not outcome.get("retry_now"):
            return result
        if attempts > retry_limit:
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

    parser.add_argument(
        "--zworker-prompt-pack",
        action="store_true",
        help="Run zworker prompt_pack mode (lightweight, no manifest/checksum contract)",
    )
    parser.add_argument(
        "--zworker-task",
        type=str,
        default=None,
        help="Task text for zworker prompt_pack (or reads from --task-file)",
    )
    parser.add_argument(
        "--zworker-output-dir",
        type=str,
        default=None,
        help="Output directory for zworker prompt_pack",
    )
    parser.add_argument(
        "--zworker-context",
        type=str,
        default="",
        help="Context text for zworker prompt_pack",
    )
    parser.add_argument(
        "--zworker-constraints",
        type=str,
        default="",
        help="Constraints text for zworker prompt_pack",
    )
    parser.add_argument(
        "--zworker-source-urls",
        type=str,
        default=None,
        help="Comma-separated source URLs for zworker prompt_pack",
    )
    parser.add_argument(
        "--zworker-allowed-paths",
        type=str,
        default=None,
        help="Comma-separated allowed path prefixes for zworker prompt_pack",
    )
    parser.add_argument(
        "--zworker-forbidden-paths",
        type=str,
        default=None,
        help="Comma-separated forbidden path prefixes for zworker prompt_pack",
    )
    parser.add_argument(
        "--zworker-expected-outputs",
        type=str,
        default=None,
        help="Comma-separated expected output paths for zworker prompt_pack",
    )
    parser.add_argument(
        "--zworker-result-unpack",
        type=str,
        default=None,
        help="Path to ZIP file for zworker result_unpack mode (safe unpack to inbox)",
    )
    parser.add_argument(
        "--zworker-unpack-request-id",
        type=str,
        default=None,
        help="Request ID for zworker result_unpack",
    )
    parser.add_argument(
        "--zworker-process-result",
        type=str,
        default=None,
        help="Request ID for zworker process_result mode",
    )
    parser.add_argument(
        "--zworker-process-unpack-dir",
        type=str,
        default=None,
        help="Optional explicit unpack directory for zworker process_result",
    )
    parser.add_argument(
        "--zworker-revision-prompt",
        type=str,
        default=None,
        help="Request ID for zworker revision_prompt mode",
    )
    parser.add_argument(
        "--zworker-revision-feedback",
        type=str,
        default="",
        help="Feedback text for zworker revision_prompt",
    )
    parser.add_argument(
        "--zworker-revision-number",
        type=int,
        default=0,
        help="Revision number for zworker revision_prompt (auto-detects if not provided)",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    config_root = config_path.parent if config_path else None

    if args.zworker_prompt_pack:
        task = args.zworker_task or ""
        if not task and args.task_file:
            task_path = Path(args.task_file)
            if task_path.exists():
                task = task_path.read_text(encoding="utf-8")
        if not task:
            print("Error: zworker_prompt_pack requires --zworker-task or --task-file", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        source_urls = None
        if args.zworker_source_urls:
            source_urls = [u.strip() for u in args.zworker_source_urls.split(",") if u.strip()]
        output_dir = Path(args.zworker_output_dir) if args.zworker_output_dir else None
        result = zworker_prompt_pack(
            task,
            output_dir=output_dir,
            context=args.zworker_context,
            constraints=args.zworker_constraints,
            source_urls=source_urls,
            allowed_paths=args.zworker_allowed_paths,
            forbidden_paths=args.zworker_forbidden_paths,
            expected_outputs=args.zworker_expected_outputs,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if args.zworker_result_unpack:
        zip_path = Path(args.zworker_result_unpack)
        if not zip_path.exists():
            print(f"Error: ZIP file not found: {zip_path}", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        target_root = Path(args.directory) if args.directory else REPO_ROOT
        result = zworker_result_unpack(
            zip_path,
            request_id=args.zworker_unpack_request_id or "",
            target_root=target_root,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if args.zworker_process_result:
        request_id = args.zworker_process_result
        unpack_dir = Path(args.zworker_process_unpack_dir) if args.zworker_process_unpack_dir else None
        target_root = Path(args.directory) if args.directory else REPO_ROOT
        result = zworker_process_result(
            request_id,
            unpack_dir=unpack_dir,
            target_root=target_root,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if args.zworker_revision_prompt:
        request_id = args.zworker_revision_prompt
        result = zworker_revision_prompt(
            request_id,
            feedback=args.zworker_revision_feedback,
            revision_number=args.zworker_revision_number,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

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
