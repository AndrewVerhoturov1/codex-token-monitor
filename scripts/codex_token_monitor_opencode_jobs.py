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
DEFAULT_TIMEOUT_SECONDS = 720
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

ZCHAT_MODE_PROMPT_PACK = "zchat_prompt_pack"
ZCHAT_MODE_IMPORT_PACK = "zchat_import_pack"
ZCHAT_MODE_VERIFY_PACK = "zchat_verify_pack"
ZCHAT_MODE_DECISION_PACK = "zchat_decision_pack"
ZCHAT_VALID_MODES = frozenset({
    ZCHAT_MODE_PROMPT_PACK,
    ZCHAT_MODE_IMPORT_PACK,
    ZCHAT_MODE_VERIFY_PACK,
    ZCHAT_MODE_DECISION_PACK,
})

ZCHAT_VERDICT_ACCEPTED = "accepted_for_review"
ZCHAT_VERDICT_REJECTED_STRUCTURAL = "rejected_structural"
ZCHAT_VERDICT_REJECTED_SCOPE = "rejected_scope"
ZCHAT_VERDICT_NEEDS_DECISION = "needs_codex_decision"
ZCHAT_DECISION_ACCEPTED = "accepted"
ZCHAT_DECISION_REJECTED = "rejected"
ZCHAT_DECISION_NEEDS_REVISION = "needs_revision"
ZCHAT_VALID_VERDICTS = frozenset({
    ZCHAT_VERDICT_ACCEPTED,
    ZCHAT_VERDICT_REJECTED_STRUCTURAL,
    ZCHAT_VERDICT_REJECTED_SCOPE,
    ZCHAT_VERDICT_NEEDS_DECISION,
})
ZCHAT_VALID_DECISIONS = frozenset({
    ZCHAT_DECISION_ACCEPTED,
    ZCHAT_DECISION_REJECTED,
    ZCHAT_DECISION_NEEDS_REVISION,
})

ZCHAT_DIR = REPO_ROOT / ".ai" / "zchat"
ZCHAT_TEMPLATE_DIR = ZCHAT_DIR / "templates"
ZCHAT_SCHEMA_DIR = ZCHAT_DIR / "schemas"
ZCHAT_DOCS_DIR = ZCHAT_DIR / "docs"
ZCHAT_SKILLS_DIR = ZCHAT_DIR / "skills"
ZCHAT_RUNTIME_DIR = ZCHAT_DIR / "runtime"
ZCHAT_RUNTIME_REQUESTS = ZCHAT_RUNTIME_DIR / "requests"
ZCHAT_RUNTIME_IMPORTS = ZCHAT_RUNTIME_DIR / "imports"
ZCHAT_RUNTIME_REVIEWS = ZCHAT_RUNTIME_DIR / "reviews"
ZCHAT_RUNTIME_ACCEPTED = ZCHAT_RUNTIME_DIR / "accepted"
ZCHAT_RUNTIME_REJECTED = ZCHAT_RUNTIME_DIR / "rejected"
ZCHAT_RUNTIME_BRANCHES = ZCHAT_RUNTIME_DIR / "branches"

ZCHAT_FORBIDDEN_PATH_PREFIXES = frozenset({
    ".git/",
})
ZCHAT_FORBIDDEN_PATH_PATTERNS = frozenset({
    ".env",
})
ZCHAT_FORBIDDEN_PATH_SEGMENTS = frozenset({
    ".ai/zchat", ".ai\\zchat",
})

ZCHAT_REQUIRED_IMPORT_FILES = frozenset({
    "manifest.json", "checksums.sha256", "payload/",
})

ZCHAT_PROMPT_PACK_ARTIFACTS = frozenset({
    "prompt.md", "prompt_passport.md", "request_manifest.json",
})


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


def _append_text(path: Path, text: str) -> None:
    if not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


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


def _zchat_slug_id() -> str:
    return _git_utils.zchat_slug_id()


def _zchat_slug_id_is_valid(slug: str) -> bool:
    return _git_utils.zchat_slug_id_is_valid(slug)


@dataclass
class ZchatPromptPackResult:
    mode: str = ZCHAT_MODE_PROMPT_PACK
    request_id: str = ""
    output_dir: str = ""
    artifacts: list[str] = field(default_factory=list)
    status: str = ""
    error: str = ""


@dataclass
class ZchatImportPackResult:
    mode: str = ZCHAT_MODE_IMPORT_PACK
    package_id: str = ""
    verdict: str = ""
    status: str = ""
    error: str = ""
    report_path: str = ""
    files_imported: int = 0
    files_skipped: int = 0


@dataclass
class ZchatVerifyPackResult:
    mode: str = ZCHAT_MODE_VERIFY_PACK
    verdict: str = ""
    status: str = ""
    error: str = ""
    report_path: str = ""


@dataclass
class ZchatDecisionPackResult:
    mode: str = ZCHAT_MODE_DECISION_PACK
    decision_id: str = ""
    verdict: str = ""
    status: str = ""
    error: str = ""
    decision_path: str = ""
    manifest_path: str = ""
    journal_path: str = ""


def _zchat_forbidden_path(file_path: str, repo_root: Path) -> str:
    normalized = file_path.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", normalized):
        return f"absolute path forbidden: {file_path}"
    if ".." in Path(normalized).parts:
        return f"path traversal forbidden: {file_path}"
    for prefix in ZCHAT_FORBIDDEN_PATH_PREFIXES:
        if normalized.startswith(prefix):
            return f"forbidden path prefix {prefix}: {file_path}"
    for pattern in ZCHAT_FORBIDDEN_PATH_PATTERNS:
        if Path(normalized).name.startswith(pattern):
            return f"forbidden filename pattern {pattern}: {file_path}"
    for segment in ZCHAT_FORBIDDEN_PATH_SEGMENTS:
        test_path = normalized.casefold()
        if test_path.startswith(segment.casefold()):
            return f"forbidden path segment {segment}: {file_path}"
    resolved = (repo_root / normalized).resolve(strict=False)
    try:
        resolved.relative_to(repo_root.resolve(strict=False))
    except ValueError:
        return f"path escapes repository root: {file_path}"
    return ""


def zchat_prompt_pack(
    task: str,
    *,
    output_dir: Path | None = None,
    context: str = "",
    constraints: str = "",
    request_id: str = "",
    source_urls: list[str] | None = None,
) -> ZchatPromptPackResult:
    if not request_id:
        request_id = _zchat_slug_id()
    if output_dir is None:
        output_dir = ZCHAT_RUNTIME_REQUESTS / request_id
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        now_utc = _utcnow()
        artifacts: list[str] = []

        prompt_content = (ZCHAT_TEMPLATE_DIR / "prompt.md").read_text(encoding="utf-8")
        prompt_content = prompt_content.replace("{task}", task)
        prompt_content = prompt_content.replace("{context}", context or "No additional context provided.")
        prompt_content = prompt_content.replace("{constraints}", constraints or "Follow repository conventions.")
        prompt_path = output_dir / "prompt.md"
        _atomic_write_text(prompt_path, prompt_content)
        artifacts.append("prompt.md")

        resolved_urls = source_urls or []
        sources_block = "\n".join(f"- {url}" for url in resolved_urls) if resolved_urls else "- No external sources resolved."
        branch_decision_info = _git_utils.resolve_branch_decision(source_urls=resolved_urls)
        branch_decision = (
            "Use public GitHub raw URLs only; temporary branch is NOT required."
            if not branch_decision_info["create_branch"]
            else "Public GitHub context insufficient; a temporary branch MAY be created."
        )
        passport_content = (ZCHAT_TEMPLATE_DIR / "prompt_passport.md").read_text(encoding="utf-8")
        passport_content = passport_content.replace("{resolved_sources}", sources_block)
        passport_content = passport_content.replace("{branch_decision}", branch_decision)
        passport_content = passport_content.replace(
            "{artifacts}",
            "\n".join(f"- {a}" for a in artifacts),
        )
        passport_path = output_dir / "prompt_passport.md"
        _atomic_write_text(passport_path, passport_content)
        artifacts.append("prompt_passport.md")

        artifacts.append("request_manifest.json")
        manifest = {
            "manifest_version": "1.0",
            "request_id": request_id,
            "created_at": now_utc,
            "mode": ZCHAT_MODE_PROMPT_PACK,
            "artifacts": artifacts,
            "source_policy": "public_github_raw_first",
            "branch_policy": "temporary_branch_only_if_public_insufficient",
            "dependencies": resolved_urls,
            "metadata": {
                "context_provided": bool(context),
                "constraints_provided": bool(constraints),
                "source_urls_count": len(resolved_urls),
            },
        }
        manifest_path = output_dir / "request_manifest.json"
        _atomic_write_json(manifest_path, manifest)

        return ZchatPromptPackResult(
            request_id=request_id,
            output_dir=str(output_dir),
            artifacts=artifacts,
            status="completed",
        )
    except Exception as e:
        return ZchatPromptPackResult(
            request_id=request_id,
            output_dir=str(output_dir),
            status="failed",
            error=f"{type(e).__name__}: {e}",
        )


def zchat_import_pack(
    zip_path: Path,
    *,
    target_root: Path | None = None,
) -> ZchatImportPackResult:
    if target_root is None:
        target_root = REPO_ROOT
    target_root = target_root.resolve(strict=True)

    import_slug = _zchat_slug_id()
    report_path = ZCHAT_RUNTIME_IMPORTS / import_slug / f"import_report_{uuid.uuid4().hex[:12]}.md"
    ZCHAT_RUNTIME_IMPORTS.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if not zip_path.exists():
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"ZIP file not found: {zip_path}",
            report_path=str(report_path),
        )

    report_lines = [
        "# Zchat Import Report",
        "",
        f"- **ZIP**: `{zip_path}`",
        f"- **Target root**: `{target_root}`",
        f"- **Started at**: {_utcnow()}",
        "",
    ]

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zip_entries = [info.filename.replace("\\", "/") for info in zf.infolist()]
    except zipfile.BadZipFile as e:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: Bad ZIP file: {e}\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"Bad ZIP file: {e}",
            report_path=str(report_path),
        )

    top_level = set()
    for entry in zip_entries:
        parts = entry.split("/")
        if parts[0]:
            if len(parts) > 1:
                top_level.add(parts[0] + "/")
            else:
                top_level.add(parts[0])

    required = {"manifest.json", "checksums.sha256", "payload/"}
    missing = required - top_level
    if missing:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Missing required top-level entries**: {sorted(missing)}\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"Missing required entries: {sorted(missing)}",
            report_path=str(report_path),
        )

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest_raw = zf.read("manifest.json")
    except KeyError:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: manifest.json not found in ZIP\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="manifest.json not found in ZIP",
            report_path=str(report_path),
        )

    try:
        manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    except json.JSONDecodeError as e:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: Invalid manifest JSON: {e}\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"Invalid manifest JSON: {e}",
            report_path=str(report_path),
        )

    if not isinstance(manifest, dict):
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: manifest.json must be a JSON object\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="manifest.json must be a JSON object",
            report_path=str(report_path),
        )

    package_id = str(manifest.get("package_id", ""))
    payload_files = manifest.get("payload_files", [])
    if not isinstance(payload_files, list) or not payload_files:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: payload_files missing or empty in manifest\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="payload_files missing or empty in manifest",
            report_path=str(report_path),
        )

    report_lines.append(f"- **Package ID**: `{package_id}`")
    report_lines.append(f"- **Payload files**: {len(payload_files)}")
    report_lines.append("")

    scope_violations: list[str] = []
    for pf in payload_files:
        if not isinstance(pf, dict):
            scope_violations.append(f"Invalid payload_files entry (not dict): {pf}")
            continue
        file_path = str(pf.get("path", ""))
        violation = _zchat_forbidden_path(file_path, target_root)
        if violation:
            scope_violations.append(violation)

    if scope_violations:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_SCOPE}")
        report_lines.append("")
        report_lines.append("### Scope Violations")
        for v in scope_violations:
            report_lines.append(f"- {v}")
        report_lines.append("")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_SCOPE,
            status="failed",
            error=f"Scope violations: {len(scope_violations)}",
            report_path=str(report_path),
        )

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            checksums_raw = zf.read("checksums.sha256").decode("utf-8-sig")
    except KeyError:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: checksums.sha256 not found in ZIP\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="checksums.sha256 not found in ZIP",
            report_path=str(report_path),
        )

    expected_checksums: dict[str, str] = {}
    for line in checksums_raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            expected_checksums[parts[1].strip()] = parts[0].strip().lower()

    if not expected_checksums:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: checksums.sha256 is empty\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="checksums.sha256 is empty",
            report_path=str(report_path),
        )

    imported = 0
    skipped = 0
    checksum_errors: list[str] = []
    report_lines.append("### Extracted Files")
    report_lines.append("")

    with zipfile.ZipFile(zip_path, "r") as zf:
        for pf in payload_files:
            file_path = str(pf.get("path", ""))
            manifest_sha = str(pf.get("sha256", "")).lower()
            zip_member = "payload/" + file_path.replace("\\", "/")

            if zip_member not in zip_entries:
                checksum_errors.append(f"File in manifest but missing in ZIP: {file_path}")
                skipped += 1
                continue

            file_data = zf.read(zip_member)

            actual_sha = _sha256_hex(file_data)
            expected_sha = expected_checksums.get(file_path, manifest_sha)

            if expected_sha and actual_sha != expected_sha:
                checksum_errors.append(
                    f"Checksum mismatch for {file_path}: expected {expected_sha}, got {actual_sha}"
                )
                skipped += 1
                continue

            if manifest_sha and actual_sha != manifest_sha:
                checksum_errors.append(
                    f"Manifest checksum mismatch for {file_path}: expected {manifest_sha}, got {actual_sha}"
                )
                skipped += 1
                continue

            dest_path = target_root / file_path
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(file_data)
                report_lines.append(f"- `{file_path}` (sha256: `{actual_sha}`)")
                imported += 1
            except OSError as e:
                checksum_errors.append(f"Failed to write {file_path}: {e}")
                skipped += 1

    report_lines.append("")

    if checksum_errors:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append("")
        report_lines.append("### Checksum Errors")
        for ce in checksum_errors:
            report_lines.append(f"- {ce}")
    elif imported == 0:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\nNo files were imported.\n")
    else:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_ACCEPTED}")
        report_lines.append(f"\nAll {imported} file(s) imported successfully.\n")

    report_lines.append("")
    report_lines.append(f"- **Files imported**: {imported}")
    report_lines.append(f"- **Files skipped**: {skipped}")
    report_lines.append("")

    _atomic_write_text(report_path, "\n".join(report_lines))

    verdict = ZCHAT_VERDICT_ACCEPTED if not checksum_errors and imported > 0 else ZCHAT_VERDICT_REJECTED_STRUCTURAL
    return ZchatImportPackResult(
        package_id=package_id,
        verdict=verdict,
        status="completed" if verdict == ZCHAT_VERDICT_ACCEPTED else "failed",
        error="; ".join(checksum_errors) if checksum_errors else "",
        report_path=str(report_path),
        files_imported=imported,
        files_skipped=skipped,
    )


def zchat_verify_pack(
    pack_dir: Path,
    *,
    repo_root: Path | None = None,
) -> ZchatVerifyPackResult:
    if repo_root is None:
        repo_root = REPO_ROOT
    repo_root = repo_root.resolve(strict=True)

    pack_dir = pack_dir.resolve(strict=False)
    if not pack_dir.exists():
        return ZchatVerifyPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"Pack directory not found: {pack_dir}",
        )

    review_slug = _zchat_slug_id()
    report_path = ZCHAT_RUNTIME_REVIEWS / review_slug / f"verify_report_{uuid.uuid4().hex[:12]}.md"
    ZCHAT_RUNTIME_REVIEWS.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# Zchat Verify Report",
        "",
        f"- **Pack directory**: `{pack_dir}`",
        f"- **Verification time**: {_utcnow()}",
        "",
    ]

    structural_issues: list[str] = []
    scope_issues: list[str] = []
    warnings: list[str] = []
    manifest_data: dict[str, Any] | None = None

    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        structural_issues.append("manifest.json is missing")
    else:
        manifest_data = _read_json_safe(manifest_path)
        if not isinstance(manifest_data, dict):
            structural_issues.append("manifest.json is not a valid JSON object")
        else:
            mode = str(manifest_data.get("mode", ""))
            if mode not in ZCHAT_VALID_MODES:
                structural_issues.append(f"Unknown mode in manifest: {mode}")
            payload_files = manifest_data.get("payload_files", [])
            if not isinstance(payload_files, list):
                structural_issues.append("payload_files is not a list in manifest")
            else:
                for pf in payload_files:
                    if not isinstance(pf, dict):
                        structural_issues.append(f"Invalid payload_files entry: {pf}")
                        continue
                    file_path = str(pf.get("path", ""))
                    violation = _zchat_forbidden_path(file_path, repo_root)
                    if violation:
                        scope_issues.append(violation)
                    actual_path = pack_dir / "payload" / file_path
                    if not actual_path.exists():
                        structural_issues.append(f"File referenced in manifest but missing from payload: {file_path}")

    checksums_path = pack_dir / "checksums.sha256"
    if not checksums_path.exists():
        structural_issues.append("checksums.sha256 is missing")
    else:
        try:
            checksums_text = checksums_path.read_text(encoding="utf-8-sig")
        except OSError:
            structural_issues.append("checksums.sha256 could not be read")
            checksums_text = ""
        if not checksums_text.strip():
            structural_issues.append("checksums.sha256 is empty")
        else:
            expected: dict[str, str] = {}
            for line in checksums_text.strip().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    expected[parts[1].strip()] = parts[0].strip().lower()
            for pf in (manifest_data.get("payload_files", []) if isinstance(manifest_data, dict) else []):
                file_path = str(pf.get("path", ""))
                manifest_sha = str(pf.get("sha256", "")).lower()
                expected_sha = expected.get(file_path, "")
                if expected_sha and manifest_sha and expected_sha != manifest_sha:
                    structural_issues.append(
                        f"Checksum mismatch for {file_path}: manifest={manifest_sha}, checksums={expected_sha}"
                    )

    payload_dir = pack_dir / "payload"
    if not payload_dir.exists() or not payload_dir.is_dir():
        structural_issues.append("payload/ directory is missing")
    else:
        payload_files_on_disk = set()
        for f in payload_dir.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(pack_dir)).replace("\\", "/")
                payload_files_on_disk.add(rel)
        manifest_files = set()
        if isinstance(manifest_data, dict):
            for pf in manifest_data.get("payload_files", []):
                if isinstance(pf, dict):
                    manifest_files.add("payload/" + str(pf.get("path", "")).replace("\\", "/"))
        extra = payload_files_on_disk - manifest_files
        if extra:
            warnings.append(f"Files in payload/ but not in manifest: {sorted(extra)}")
        missing = manifest_files - payload_files_on_disk
        if missing:
            structural_issues.append(f"Files in manifest but missing from payload/: {sorted(missing)}")

    if structural_issues:
        verdict = ZCHAT_VERDICT_REJECTED_STRUCTURAL
    elif scope_issues:
        verdict = ZCHAT_VERDICT_REJECTED_SCOPE
    elif warnings:
        verdict = ZCHAT_VERDICT_NEEDS_DECISION
    else:
        verdict = ZCHAT_VERDICT_ACCEPTED

    report_lines.append(f"## Verdict: {verdict}")
    report_lines.append("")

    if structural_issues:
        report_lines.append("### Structural Issues")
        for issue in structural_issues:
            report_lines.append(f"- {issue}")
        report_lines.append("")

    if scope_issues:
        report_lines.append("### Scope Issues")
        for issue in scope_issues:
            report_lines.append(f"- {issue}")
        report_lines.append("")

    if warnings:
        report_lines.append("### Warnings")
        for warning in warnings:
            report_lines.append(f"- {warning}")
        report_lines.append("")

    if not structural_issues and not scope_issues and not warnings:
        report_lines.append("All checks passed.\n")

    report_lines.append("### Summary")
    report_lines.append(f"- Structural issues: {len(structural_issues)}")
    report_lines.append(f"- Scope issues: {len(scope_issues)}")
    report_lines.append(f"- Warnings: {len(warnings)}")
    report_lines.append("")

    _atomic_write_text(report_path, "\n".join(report_lines))

    return ZchatVerifyPackResult(
        verdict=verdict,
        status="completed",
        error="",
        report_path=str(report_path),
    )


def zchat_decision_pack(
    *,
    subject_id: str,
    reviewer: str = "codex",
    verdict: str = "",
    rationale: str = "",
    evidence: str = "",
    decision_id: str = "",
    branch_info: dict | None = None,
) -> ZchatDecisionPackResult:
    if not decision_id:
        decision_id = _zchat_slug_id()
    if not verdict:
        return ZchatDecisionPackResult(
            decision_id=decision_id,
            status="failed",
            error="verdict is required",
        )
    if verdict not in ZCHAT_VALID_DECISIONS:
        return ZchatDecisionPackResult(
            decision_id=decision_id,
            status="failed",
            error=f"Invalid verdict: {verdict}. Must be one of: {sorted(ZCHAT_VALID_DECISIONS)}",
        )

    if verdict == ZCHAT_DECISION_ACCEPTED:
        journal_base = ZCHAT_RUNTIME_ACCEPTED / decision_id
    elif verdict == ZCHAT_DECISION_REJECTED:
        journal_base = ZCHAT_RUNTIME_REJECTED / decision_id
    else:
        journal_base = ZCHAT_RUNTIME_REVIEWS / decision_id

    journal_base.mkdir(parents=True, exist_ok=True)
    now_utc = _utcnow()

    try:
        branch_block = ""
        branch_manifest = {}
        if branch_info:
            branch_block = (
                f"\n## Branch Info\n\n"
                f"- **slug_id**: {branch_info.get('slug_id', '')}\n"
                f"- **branch_name**: {branch_info.get('branch_name', '')}\n"
                f"- **base_branch**: {branch_info.get('base_branch', '')}\n"
                f"- **created**: {branch_info.get('created', False)}\n"
                f"- **pushed**: {branch_info.get('pushed', False)}\n"
                f"- **deleted**: {branch_info.get('deleted', False)}\n"
            )
            if branch_info.get("error"):
                branch_block += f"- **error**: {branch_info['error']}\n"
            branch_manifest = {
                "slug_id": branch_info.get("slug_id", ""),
                "branch_name": branch_info.get("branch_name", ""),
                "base_branch": branch_info.get("base_branch", ""),
                "created": branch_info.get("created", False),
                "pushed": branch_info.get("pushed", False),
                "deleted": branch_info.get("deleted", False),
                "error": branch_info.get("error", ""),
            }

        decision_text = (
            "# Codex Decision\n\n"
            f"- **Decision ID**: {decision_id}\n"
            f"- **Subject ID**: {subject_id}\n"
            f"- **Reviewer**: {reviewer}\n"
            f"- **Verdict**: {verdict}\n"
            f"- **Timestamp**: {now_utc}\n"
            f"\n## Rationale\n\n{rationale or 'No rationale provided.'}\n"
            f"\n## Evidence\n\n{evidence or 'No evidence provided.'}\n"
            f"{branch_block}"
        )
        decision_path = journal_base / "codex_decision.md"
        _atomic_write_text(decision_path, decision_text)

        manifest = {
            "manifest_version": "1.0",
            "decision_id": decision_id,
            "subject_id": subject_id,
            "reviewer": reviewer,
            "verdict": verdict,
            "created_at": now_utc,
            "mode": ZCHAT_MODE_DECISION_PACK,
            "rationale": rationale,
            "evidence": evidence,
            "branch_info": branch_manifest,
        }
        manifest_path = journal_base / "decision_manifest.json"
        _atomic_write_json(manifest_path, manifest)

        return ZchatDecisionPackResult(
            decision_id=decision_id,
            verdict=verdict,
            status="completed",
            decision_path=str(decision_path),
            manifest_path=str(manifest_path),
            journal_path=str(journal_base),
        )
    except Exception as e:
        return ZchatDecisionPackResult(
            decision_id=decision_id,
            verdict=verdict,
            status="failed",
            error=f"{type(e).__name__}: {e}",
            journal_path=str(journal_base),
        )


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
        **debug_metadata,
    )

    _atomic_write_json(done_path, asdict(result))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an OpenCode job or Zchat operation")
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
        "--zchat-prompt-pack",
        action="store_true",
        help="Run zchat prompt_pack mode",
    )
    parser.add_argument(
        "--zchat-import-pack",
        type=str,
        default=None,
        help="Path to ZIP file for zchat import_pack mode",
    )
    parser.add_argument(
        "--zchat-verify-pack",
        type=str,
        default=None,
        help="Path to pack directory for zchat verify_pack mode",
    )
    parser.add_argument(
        "--zchat-output-dir",
        type=str,
        default=None,
        help="Output directory for zchat prompt_pack",
    )
    parser.add_argument(
        "--zchat-task",
        type=str,
        default=None,
        help="Task text for zchat prompt_pack (or reads from --task-file)",
    )
    parser.add_argument(
        "--zchat-context",
        type=str,
        default="",
        help="Context text for zchat prompt_pack",
    )
    parser.add_argument(
        "--zchat-constraints",
        type=str,
        default="",
        help="Constraints text for zchat prompt_pack",
    )
    parser.add_argument(
        "--zchat-source-urls",
        type=str,
        default=None,
        help="Comma-separated source URLs for zchat prompt_pack",
    )
    parser.add_argument(
        "--zchat-decision-pack",
        action="store_true",
        help="Run zchat decision_pack mode (final Codex decision stage)",
    )
    parser.add_argument(
        "--zchat-subject-id",
        type=str,
        default=None,
        help="Subject/request ID for zchat decision_pack",
    )
    parser.add_argument(
        "--zchat-decision-verdict",
        type=str,
        default=None,
        help="Verdict for zchat decision_pack: accepted / rejected / needs_revision",
    )
    parser.add_argument(
        "--zchat-decision-rationale",
        type=str,
        default="",
        help="Rationale for zchat decision_pack",
    )
    parser.add_argument(
        "--zchat-decision-evidence",
        type=str,
        default="",
        help="Evidence for zchat decision_pack",
    )
    parser.add_argument(
        "--zchat-decision-reviewer",
        type=str,
        default="codex",
        help="Reviewer identity for zchat decision_pack",
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

    if args.zchat_prompt_pack:
        task = args.zchat_task or ""
        if not task and args.task_file:
            task_path = Path(args.task_file)
            if task_path.exists():
                task = task_path.read_text(encoding="utf-8")
        if not task:
            print("Error: zchat_prompt_pack requires --zchat-task or --task-file", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        source_urls = None
        if args.zchat_source_urls:
            source_urls = [u.strip() for u in args.zchat_source_urls.split(",") if u.strip()]
        output_dir = Path(args.zchat_output_dir) if args.zchat_output_dir else None
        result = zchat_prompt_pack(
            task,
            output_dir=output_dir,
            context=args.zchat_context,
            constraints=args.zchat_constraints,
            source_urls=source_urls,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if args.zchat_import_pack:
        zip_path = Path(args.zchat_import_pack)
        if not zip_path.exists():
            print(f"Error: ZIP file not found: {zip_path}", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        target_root = Path(args.directory) if args.directory else REPO_ROOT
        result = zchat_import_pack(zip_path, target_root=target_root)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if args.zchat_verify_pack:
        pack_dir = Path(args.zchat_verify_pack)
        result = zchat_verify_pack(pack_dir)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if args.zchat_decision_pack:
        if not args.zchat_subject_id:
            print("Error: zchat_decision_pack requires --zchat-subject-id", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        if not args.zchat_decision_verdict:
            print("Error: zchat_decision_pack requires --zchat-decision-verdict", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        result = zchat_decision_pack(
            subject_id=args.zchat_subject_id,
            reviewer=args.zchat_decision_reviewer,
            verdict=args.zchat_decision_verdict,
            rationale=args.zchat_decision_rationale,
            evidence=args.zchat_decision_evidence,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if not args.task_file:
        print("Error: --task-file is required unless --cleanup-jobs or a zchat mode is used", file=sys.stderr)
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
