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
ZCHAT_MODE_RECEIVE_PACK = "zchat_receive_pack"
ZCHAT_MODE_INSPECT_VERIFICATION_PACK = "zchat_inspect_verification_pack"
ZCHAT_VALID_MODES = frozenset({
    ZCHAT_MODE_PROMPT_PACK,
    ZCHAT_MODE_IMPORT_PACK,
    ZCHAT_MODE_VERIFY_PACK,
    ZCHAT_MODE_DECISION_PACK,
    ZCHAT_MODE_RECEIVE_PACK,
    ZCHAT_MODE_INSPECT_VERIFICATION_PACK,
})

ZCHAT_RESULT_TYPE_ADVICE = "advice"
ZCHAT_RESULT_TYPE_REVIEW = "review"
ZCHAT_RESULT_TYPE_PACKAGE = "package"
ZCHAT_VALID_RESULT_TYPES = frozenset({
    ZCHAT_RESULT_TYPE_ADVICE,
    ZCHAT_RESULT_TYPE_REVIEW,
    ZCHAT_RESULT_TYPE_PACKAGE,
})

ZCHAT_RUN_POLICY_NEVER_AUTO_RUN = "never_auto_run"
ZCHAT_VALID_RUN_POLICIES = frozenset({
    ZCHAT_RUN_POLICY_NEVER_AUTO_RUN,
})

ZCHAT_INSPECT_SAFE = "safe_to_run"
ZCHAT_INSPECT_UNSAFE = "unsafe"
ZCHAT_INSPECT_NEEDS_HUMAN = "needs_human_decision"
ZCHAT_INSPECT_NOT_PRESENT = "not_present"
ZCHAT_VALID_INSPECT_VERDICTS = frozenset({
    ZCHAT_INSPECT_SAFE,
    ZCHAT_INSPECT_UNSAFE,
    ZCHAT_INSPECT_NEEDS_HUMAN,
    ZCHAT_INSPECT_NOT_PRESENT,
})

ZCHAT_DANGEROUS_PATTERNS = [
    (r"\brm\s+-rf?\b", "file_deletion"),
    (r"\bos\.remove\(", "file_deletion"),
    (r"\bshutil\.rmtree\(", "file_deletion"),
    (r"\bPath\([^)]*\)\.unlink\(", "file_deletion"),
    (r"\bdel\s+.*file", "file_deletion"),
    (r"\bwrite.*outside\s+(scope|repo)", "writes_outside_scope"),
    (r"\.env\b.*(read|access|get|load)", "env_secrets_access"),
    (r"\bos\.environ\b", "env_secrets_access"),
    (r"\bdotenv\b", "env_secrets_access"),
    (r"\bgit\s+commit\b", "git_commit"),
    (r"\bgit\s+push\b", "git_push"),
    (r"\bgit\s+add\b", "git_mutation"),
    (r"\b(git\s+checkout|git\s+branch|git\s+reset|git\s+clean|git\s+rebase)\b", "git_mutation"),
    (r"\bpip\s+install\b", "network_install"),
    (r"\bnpm\s+install\b", "network_install"),
    (r"\bapt-get\s+install\b", "network_install"),
    (r"\bchoco\s+install\b", "network_install"),
    (r"\bcurl\b|wget\b", "network_download"),
    (r"\brequests\.(get|post|put|delete|patch)\b", "network_download"),
    (r"\burllib\.request\b", "network_download"),
    (r"\bsubprocess\.(run|call|Popen|check_output|check_call)\b", "shell_subprocess"),
    (r"\bos\.system\(", "shell_subprocess"),
    (r"\bpopen\(", "shell_subprocess"),
    (r"\beval\(", "code_execution"),
    (r"\bexec\(", "code_execution"),
    (r"\bcompile\(", "code_execution"),
    (r"\.git\b.*(read|write|modify|access|delete)", "git_access"),
    (r"\b/\.{1,2}/(etc|var|usr|tmp|home|root|proc|sys|dev)\b", "absolute_path"),
    (r"\b[Cc]:\\.*Windows\b", "absolute_path"),
    (r"\b(open|read|write).*\.\./", "path_traversal"),
]

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
ZCHAT_RUNTIME_QUARANTINE = ZCHAT_RUNTIME_DIR / "quarantine"

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

ZCHAT_PROFILE_SLIM = "slim"
ZCHAT_PROFILE_FULL = "full"
ZCHAT_VALID_PROFILES = frozenset({ZCHAT_PROFILE_SLIM, ZCHAT_PROFILE_FULL})

ZCHAT_CANONICAL_CACHE_DIR = ZCHAT_RUNTIME_DIR / "cache"
ZCHAT_CANONICAL_CACHE_FILE = ZCHAT_CANONICAL_CACHE_DIR / "canonical_docs.json"
ZCHAT_CANONICAL_CACHE_TTL_SECONDS = 7200

ZCHAT_SELF_CHECK_INVARIANTS = {
    "request_name_regex": r"^ZCHAT-\d{8}-\d{6}-[a-z0-9][a-z0-9-]*$",
    "no_advice_review_package_literal_in_package": "advice|review|package",
    "no_payload_in_logical": "payload/",
    "passport_no_full_contract": "Expected ZIP Contract",
    "passport_no_preflight": "Preflight Checklist",
}


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


ZCHAT_STATIC_MANUAL_URL = (
    "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/"
    "docs/zchat_external_agent_static_manual.md"
)
ZCHAT_REPO_NAVIGATION_URL = (
    "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/"
    "docs/zchat_repo_navigation.md"
)


def _zchat_canonical_public_urls() -> tuple[str, str]:
    return (ZCHAT_STATIC_MANUAL_URL, ZCHAT_REPO_NAVIGATION_URL)


_ZCHAT_SKIP_URL_CHECK = False


def _zchat_check_canonical_urls_reachable() -> str:
    if _ZCHAT_SKIP_URL_CHECK:
        return ""
    import urllib.request
    for label, url in [
        ("static manual", ZCHAT_STATIC_MANUAL_URL),
        ("repo navigation", ZCHAT_REPO_NAVIGATION_URL),
    ]:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = getattr(resp, "status", 0)
                if isinstance(status, int) and (status < 200 or status >= 300):
                    return f"{label} URL unreachable (HTTP {status}): {url}"
        except Exception as e:
            return f"{label} URL unreachable: {url} ({e})"
    return ""


def _zchat_slug_id() -> str:
    return _git_utils.zchat_slug_id()


def _zchat_slug_id_is_valid(slug: str) -> bool:
    return _git_utils.zchat_slug_id_is_valid(slug)


def _zchat_request_name(task: str | None = None) -> str:
    return _git_utils.zchat_request_name(task)


def _zchat_request_name_is_valid(name: str) -> bool:
    return _git_utils.zchat_request_name_is_valid(name)


def _zchat_canonical_docs_cache_load() -> dict:
    if not ZCHAT_CANONICAL_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(ZCHAT_CANONICAL_CACHE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _zchat_canonical_docs_cache_save(data: dict) -> None:
    _atomic_write_json(ZCHAT_CANONICAL_CACHE_FILE, data)


def _zchat_canonical_docs_cache_check(*, force_refresh: bool = False) -> tuple[bool, str, int]:
    t_start = time.perf_counter_ns()
    cache = _zchat_canonical_docs_cache_load()

    if not force_refresh and cache:
        now_ts = time.time()
        entries_ok = True
        for url, entry in cache.items():
            if not isinstance(entry, dict):
                entries_ok = False
                break
            checked_ts = entry.get("checked_at", 0)
            ttl = entry.get("ttl_seconds", ZCHAT_CANONICAL_CACHE_TTL_SECONDS)
            if now_ts - checked_ts > ttl:
                entries_ok = False
                break
        if entries_ok:
            elapsed_ms = int((time.perf_counter_ns() - t_start) / 1_000_000)
            return True, "", elapsed_ms

    manual_url, nav_url = _zchat_canonical_public_urls()
    url_check_error = _zchat_check_canonical_urls_reachable()
    if url_check_error:
        if cache:
            elapsed_ms = int((time.perf_counter_ns() - t_start) / 1_000_000)
            return True, f"cache stale, remote check failed: {url_check_error}", elapsed_ms
        elapsed_ms = int((time.perf_counter_ns() - t_start) / 1_000_000)
        return False, url_check_error, elapsed_ms

    now_ts = time.time()
    for label, url in [
        ("static_manual", manual_url),
        ("repo_navigation", nav_url),
    ]:
        cache[url] = {
            "url": url,
            "sha256": "",
            "checked_at": now_ts,
            "ttl_seconds": ZCHAT_CANONICAL_CACHE_TTL_SECONDS,
            "status": "reachable",
        }
    if not _ZCHAT_CACHE_BYPASS_SAVE:
        _zchat_canonical_docs_cache_save(cache)

    _ZCHAT_DID_REMOTE_CHECK = True
    elapsed_ms = int((time.perf_counter_ns() - t_start) / 1_000_000)
    return True, "", elapsed_ms


_ZCHAT_DID_REMOTE_CHECK = False
_ZCHAT_CACHE_BYPASS_SAVE = False


def _zchat_prompt_pack_self_check(
    prompt_text: str,
    passport_text: str,
    request_name: str,
    has_concrete_manifest: bool,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not re.match(ZCHAT_SELF_CHECK_INVARIANTS["request_name_regex"], request_name):
        errors.append(f"request_name does not match regex: {request_name}")

    if "## Canonical" not in prompt_text:
        errors.append("canonical docs section not found in prompt")

    if "## Required Task Source URLs" not in prompt_text:
        errors.append("task sources section not found in prompt")

    if has_concrete_manifest and "Package Manifest Skeleton" not in prompt_text:
        errors.append("concrete manifest skeleton not found in prompt")

    if '"zchat_result_type": "advice|review|package"' in prompt_text:
        errors.append("generic advice|review|package literal found in package prompt")

    if any("payload/" in line for line in prompt_text.splitlines()
           if ('"path":' in line or '"context_readback":' in line
               or '"verification_files":' in line)):
        errors.append("payload/ found in logical manifest/checksum paths")

    if "Expected ZIP Contract" in passport_text:
        errors.append("passport contains full ZIP contract")

    if "Preflight Checklist" in passport_text:
        errors.append("passport contains preflight checklist")

    if "## Expected Outputs" not in prompt_text:
        errors.append("expected outputs not listed in prompt")

    return len(errors) == 0, errors


@dataclass
class ZchatPromptPackResult:
    mode: str = ZCHAT_MODE_PROMPT_PACK
    request_id: str = ""
    output_dir: str = ""
    artifacts: list[str] = field(default_factory=list)
    status: str = ""
    error: str = ""
    profile: str = ZCHAT_PROFILE_SLIM
    timings: dict[str, int] = field(default_factory=dict)
    prompt_lines: int = 0
    passport_lines: int = 0


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
    timings: dict[str, int] = field(default_factory=dict)


@dataclass
class ZchatVerifyPackResult:
    mode: str = ZCHAT_MODE_VERIFY_PACK
    verdict: str = ""
    status: str = ""
    error: str = ""
    report_path: str = ""
    timings: dict[str, int] = field(default_factory=dict)


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


@dataclass
class ZchatReceivePackResult:
    mode: str = ZCHAT_MODE_RECEIVE_PACK
    package_id: str = ""
    verdict: str = ""
    status: str = ""
    error: str = ""
    report_path: str = ""
    quarantine_dir: str = ""
    files_received: int = 0
    timings: dict[str, int] = field(default_factory=dict)


@dataclass
class ZchatInspectVerificationPackResult:
    mode: str = ZCHAT_MODE_INSPECT_VERIFICATION_PACK
    verdict: str = ""
    status: str = ""
    error: str = ""
    report_path: str = ""
    findings: list[dict] = field(default_factory=list)


def _validate_zchat_import_manifest_schema_like(manifest: dict, *, mode_check: str = ZCHAT_MODE_IMPORT_PACK) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]

    mv = manifest.get("manifest_version")
    if mv == "2.0":
        return _validate_zchat_manifest_v2(manifest, mode_check=mode_check)
    if mv != "1.0":
        errors.append(f"manifest_version must be '1.0' or '2.0', got: {mv}")
        return errors

    pid = manifest.get("package_id", "")
    if not isinstance(pid, str) or not pid.strip():
        errors.append("package_id must be non-empty string")

    ca = manifest.get("created_at", "")
    if not isinstance(ca, str) or not ca.strip():
        errors.append("created_at must be non-empty string")

    mode = manifest.get("mode", "")
    if mode != mode_check:
        errors.append(f"mode must be '{mode_check}', got: {mode}")

    pf = manifest.get("payload_files")
    if not isinstance(pf, list):
        errors.append("payload_files must be a list")
    else:
        if mode_check == ZCHAT_MODE_IMPORT_PACK and len(pf) == 0:
            errors.append("payload_files must be non-empty for import pack")
        for i, entry in enumerate(pf):
            if not isinstance(entry, dict):
                errors.append(f"payload_files[{i}] must be a dict")
                continue
            path_val = entry.get("path", "")
            if not isinstance(path_val, str) or not path_val.strip():
                errors.append(f"payload_files[{i}].path must be non-empty string")
            sha_val = entry.get("sha256", "")
            if not isinstance(sha_val, str) or not re.match(r"^[a-f0-9]{64}$", sha_val.lower()):
                errors.append(f"payload_files[{i}].sha256 must be 64-char hex string, got: {sha_val[:20]}...")

    ap = manifest.get("allowed_paths")
    if ap is not None:
        if not isinstance(ap, list) or not all(isinstance(x, str) for x in ap):
            errors.append("allowed_paths must be list[str] if present")

    fp = manifest.get("forbidden_paths")
    if fp is not None:
        if not isinstance(fp, list) or not all(isinstance(x, str) for x in fp):
            errors.append("forbidden_paths must be list[str] if present")

    meta = manifest.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        errors.append("metadata must be dict if present")

    return errors


def _validate_zchat_manifest_v2(manifest: dict, *, mode_check: str = ZCHAT_MODE_IMPORT_PACK) -> list[str]:
    errors: list[str] = []

    pid = manifest.get("package_id", "")
    if not isinstance(pid, str) or not pid.strip():
        errors.append("package_id must be non-empty string")

    ca = manifest.get("created_at", "")
    if not isinstance(ca, str) or not ca.strip():
        errors.append("created_at must be non-empty string")

    mode = manifest.get("mode", "")
    if mode != mode_check:
        errors.append(f"mode must be '{mode_check}', got: {mode}")

    rt = manifest.get("zchat_result_type", "")
    if rt not in ZCHAT_VALID_RESULT_TYPES:
        errors.append(f"zchat_result_type must be one of {sorted(ZCHAT_VALID_RESULT_TYPES)}, got: {rt}")

    rp = manifest.get("run_policy", ZCHAT_RUN_POLICY_NEVER_AUTO_RUN)
    if rp not in ZCHAT_VALID_RUN_POLICIES:
        errors.append(f"run_policy must be one of {sorted(ZCHAT_VALID_RUN_POLICIES)}, got: {rp}")

    context_readback = manifest.get("context_readback", "")
    metadata = manifest.get("metadata")
    if not context_readback:
        if isinstance(metadata, dict) and metadata.get("context_readback"):
            context_readback = metadata["context_readback"]
    if not context_readback:
        errors.append("context_readback is required for v2 manifests (either as top-level field or metadata.context_readback)")

    pf = manifest.get("payload_files")
    if not isinstance(pf, list):
        errors.append("payload_files must be a list")
    else:
        for i, entry in enumerate(pf):
            if not isinstance(entry, dict):
                errors.append(f"payload_files[{i}] must be a dict")
                continue
            path_val = entry.get("path", "")
            if not isinstance(path_val, str) or not path_val.strip():
                errors.append(f"payload_files[{i}].path must be non-empty string")
            sha_val = entry.get("sha256", "")
            if not isinstance(sha_val, str) or not re.match(r"^[a-f0-9]{64}$", sha_val.lower()):
                errors.append(f"payload_files[{i}].sha256 must be 64-char hex string, got: {sha_val[:20]}...")

    vf = manifest.get("verification_files")
    if vf is not None:
        if not isinstance(vf, list):
            errors.append("verification_files must be list[str] if present")

    ap = manifest.get("allowed_paths")
    if ap is not None:
        if not isinstance(ap, list) or not all(isinstance(x, str) for x in ap):
            errors.append("allowed_paths must be list[str] if present")

    fp = manifest.get("forbidden_paths")
    if fp is not None:
        if not isinstance(fp, list) or not all(isinstance(x, str) for x in fp):
            errors.append("forbidden_paths must be list[str] if present")

    meta = manifest.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        errors.append("metadata must be dict if present")

    return errors


def _zchat_check_path_policy(
    file_path: str,
    *,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
) -> str:
    normalized = file_path.replace("\\", "/")
    if forbidden_paths:
        for prefix in forbidden_paths:
            prefix_norm = prefix.replace("\\", "/")
            if normalized.startswith(prefix_norm):
                return f"forbidden path prefix '{prefix}' matched: {file_path}"
    if allowed_paths:
        if not any(normalized.startswith(p.replace("\\", "/")) for p in allowed_paths):
            return f"path not in allowed_paths: {file_path}"
    return ""


def _zchat_normalize_path_list(value: str | list[str] | None) -> list[str] | None:
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
    allowed_paths: str | list[str] | None = None,
    forbidden_paths: str | list[str] | None = None,
    expected_outputs: str | list[str] | None = None,
    profile: str = ZCHAT_PROFILE_SLIM,
    refresh_canonical_docs: bool = False,
    verification_files: list[str] | None = None,
) -> ZchatPromptPackResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    if profile not in ZCHAT_VALID_PROFILES:
        return ZchatPromptPackResult(
            status="failed",
            error=f"Invalid profile: {profile}. Must be one of: {sorted(ZCHAT_VALID_PROFILES)}",
            profile=profile,
        )

    request_name = request_id if request_id else _zchat_request_name(task)
    if output_dir is None:
        output_dir = ZCHAT_RUNTIME_REQUESTS / request_name
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_urls = source_urls or []
    normalized_allowed = _zchat_normalize_path_list(allowed_paths) or []
    normalized_forbidden = _zchat_normalize_path_list(forbidden_paths) or []
    normalized_expected = _zchat_normalize_path_list(expected_outputs) or []

    try:
        now_utc = _utcnow()
        artifacts: list[str] = []

        canonical_ok, canonical_error, canonical_ms = _zchat_canonical_docs_cache_check(
            force_refresh=refresh_canonical_docs
        )
        timings["canonical_docs_check_ms"] = canonical_ms

        manual_url, nav_url = _zchat_canonical_public_urls()
        if not canonical_ok:
            return ZchatPromptPackResult(
                request_id=request_name,
                output_dir=str(output_dir),
                status="blocked",
                error=canonical_error,
                profile=profile,
                timings=timings,
            )
        if canonical_error and not _ZCHAT_DID_REMOTE_CHECK:
            return ZchatPromptPackResult(
                request_id=request_name,
                output_dir=str(output_dir),
                status="blocked",
                error=canonical_error,
                profile=profile,
                timings=timings,
            )

        t_render_start = time.perf_counter_ns()

        required_reading = (
            f"1. Static manual (canonical): {manual_url}\n"
            f"2. Repo navigation (canonical): {nav_url}\n"
            f"3. This task prompt (read in full)\n"
            f"4. Required Task Source URLs (see section below)\n"
            f"5. Optional Task Source URLs / Side Files (if any are listed below)\n"
        )
        missing_information_policy = (
            "If information required to complete the task is missing from all available sources, "
            "stop immediately with status BLOCKED_MISSING_CONTEXT. "
            "Do NOT guess, fabricate, or assume. Do NOT produce a ZIP."
        )
        sources_read_report_requirement = (
            "For ZIP package tasks, you MUST include a Sources Read Report in context_readback.md "
            "covering every provided source URL: what was read, partially read, or not read and why. "
            "Use the canonical Sources Read Report field set from the static manual. "
            "For blocked/conflict responses, include a brief Sources Read Report in the chat response body; no ZIP is produced."
        )
        required_task_source_urls_block = (
            "\n".join(f"- {url}" for url in resolved_urls)
            if resolved_urls
            else "No required task source URLs provided."
        )
        optional_task_source_urls_block = "None specified."
        side_files_block = "None specified."
        authority_order_block = (
            "1. Canonical public docs (static manual, repo navigation) — highest authority.\n"
            "2. This task prompt — overrides only where task is more specific and does not contradict canonical docs.\n"
            "3. Required task source URLs — below canonical docs; above optional sources.\n"
            "4. Optional task source URLs / side files — lowest authority among provided sources.\n"
            "5. External search / web results — never above any provided source.\n"
            "6. Guessing / fabrication — never allowed.\n"
            "\n"
            "If any source below level 1 contradicts a canonical doc, the canonical doc wins. "
            "If the conflict involves response modes, path rules, ZIP contract, trust chain, "
            "stop-if-missing policy, or local/runtime claims, return CONTRACT_CONFLICT."
        )
        derived_context_readback = ""
        derived_verification_files: list[str] = list(verification_files) if verification_files else []
        if normalized_expected:
            for ep in normalized_expected:
                if "context_readback" in ep and not derived_context_readback:
                    derived_context_readback = ep
        has_concrete_manifest = bool(normalized_expected)
        package_manifest_skeleton = (
            "Below is a concrete package manifest skeleton. Fill in values that only you can provide "
            "({ISO8601_UTC}, {64-char hex sha256} per file). "
            "Values the system already knows are filled in for you:\n\n"
            "```json\n"
            "{\n"
            '  "manifest_version": "2.0",\n'
            f'  "package_id": {json.dumps(request_name)},\n'
            '  "created_at": "{ISO8601_UTC}",\n'
            '  "mode": "zchat_import_pack",\n'
            '  "zchat_result_type": "package",\n'
            '  "run_policy": "never_auto_run",\n'
        )
        if derived_context_readback:
            package_manifest_skeleton += (
                f'  "context_readback": {json.dumps(derived_context_readback)},\n'
            )
        if normalized_expected:
            package_manifest_skeleton += '  "payload_files": [\n'
            for ep in normalized_expected:
                package_manifest_skeleton += (
                    f'    {{"path": {json.dumps(ep)}, "sha256": "{{64-char hex sha256}}"}},\n'
                )
            package_manifest_skeleton += '  ],\n'
        else:
            package_manifest_skeleton += (
                '  "payload_files": [\n'
                '    {"path": "{repo_relative_path}", "sha256": "{64-char hex sha256}"}\n'
                '  ],\n'
            )
        if derived_verification_files:
            package_manifest_skeleton += (
                '  "verification_files": ' + json.dumps(derived_verification_files, ensure_ascii=False) + ',\n'
            )
        if normalized_allowed:
            package_manifest_skeleton += (
                '  "allowed_paths": ' + json.dumps(normalized_allowed, ensure_ascii=False) + ',\n'
            )
        if normalized_forbidden:
            package_manifest_skeleton += (
                '  "forbidden_paths": ' + json.dumps(normalized_forbidden, ensure_ascii=False) + ',\n'
            )
        if derived_context_readback:
            package_manifest_skeleton += (
                '  "metadata": {\n'
                f'    "context_readback": {json.dumps(derived_context_readback)}\n'
                '  }\n'
            )
        package_manifest_skeleton += (
            "}\n"
            "```"
        )

        prompt_content = (ZCHAT_TEMPLATE_DIR / "prompt.md").read_text(encoding="utf-8")
        prompt_content = prompt_content.replace("{request_name}", request_name)
        prompt_content = prompt_content.replace("{task}", task)
        prompt_content = prompt_content.replace("{context}", context or "No additional context provided.")
        prompt_content = prompt_content.replace("{constraints}", constraints or "Follow repository conventions.")
        prompt_content = prompt_content.replace("{static_manual_url}", manual_url)
        prompt_content = prompt_content.replace("{repo_navigation_url}", nav_url)
        prompt_content = prompt_content.replace("{required_reading}", required_reading)
        prompt_content = prompt_content.replace("{missing_information_policy}", missing_information_policy)
        prompt_content = prompt_content.replace("{sources_read_report_requirement}", sources_read_report_requirement)
        prompt_content = prompt_content.replace("{required_task_source_urls}", required_task_source_urls_block)
        prompt_content = prompt_content.replace("{optional_task_source_urls}", optional_task_source_urls_block)
        prompt_content = prompt_content.replace("{side_files}", side_files_block)
        prompt_content = prompt_content.replace("{authority_order}", authority_order_block)
        prompt_content = prompt_content.replace("{package_manifest_skeleton}", package_manifest_skeleton)

        allowed_block = "\n".join(f"- {p}" for p in normalized_allowed) if normalized_allowed else "No explicit allowed_paths provided."
        forbidden_block = "\n".join(f"- {p}" for p in normalized_forbidden) if normalized_forbidden else "No explicit forbidden_paths provided."
        expected_block = "\n".join(f"- {o}" for o in normalized_expected) if normalized_expected else "No explicit expected_outputs provided."
        prompt_content = prompt_content.replace("{allowed_paths}", allowed_block)
        prompt_content = prompt_content.replace("{forbidden_paths}", forbidden_block)
        prompt_content = prompt_content.replace("{expected_outputs}", expected_block)

        if profile == ZCHAT_PROFILE_SLIM and has_concrete_manifest:
            zip_contract_section_start = prompt_content.find("## Expected ZIP Contract")
            if zip_contract_section_start >= 0:
                next_section = prompt_content.find("\n## ", zip_contract_section_start + 5)
                if next_section < 0:
                    next_section = len(prompt_content)
                short_ref = (
                    "## ZIP Contract Reference\n\n"
                    "Follow the canonical static manual for the full ZIP contract. "
                    "The concrete package manifest skeleton above provides all required fields. "
                    f"See: {manual_url}\n\n"
                )
                prompt_content = prompt_content[:zip_contract_section_start] + short_ref + prompt_content[next_section:]

        prompt_path = output_dir / "prompt.md"
        _atomic_write_text(prompt_path, prompt_content)
        artifacts.append("prompt.md")

        allowed_passport_block = "\n".join(f"- {p}" for p in normalized_allowed) if normalized_allowed else "- No explicit allowed_paths provided."
        forbidden_passport_block = "\n".join(f"- {p}" for p in normalized_forbidden) if normalized_forbidden else "- No explicit forbidden_paths provided."
        if normalized_expected:
            expected_passport_block = f"{len(normalized_expected)} expected outputs:\n" + "\n".join(f"- {o}" for o in normalized_expected)
        else:
            expected_passport_block = "- No explicit expected_outputs provided."

        passport_content = (ZCHAT_TEMPLATE_DIR / "prompt_passport.md").read_text(encoding="utf-8")
        passport_content = passport_content.replace("{request_name}", request_name)
        passport_content = passport_content.replace("{task}", task)
        passport_content = passport_content.replace("{prompt_path}", str(output_dir / "prompt.md"))
        passport_content = passport_content.replace("{static_manual_url}", manual_url)
        passport_content = passport_content.replace("{repo_navigation_url}", nav_url)
        passport_content = passport_content.replace("{required_task_source_urls}", required_task_source_urls_block)
        passport_content = passport_content.replace("{allowed_paths}", allowed_passport_block)
        passport_content = passport_content.replace("{forbidden_paths}", forbidden_passport_block)
        passport_content = passport_content.replace("{expected_outputs}", expected_passport_block)
        passport_path = output_dir / "prompt_passport.md"
        _atomic_write_text(passport_path, passport_content)
        artifacts.append("prompt_passport.md")

        timings["render_templates_ms"] = int((time.perf_counter_ns() - t_render_start) / 1_000_000)

        t_self_check_start = time.perf_counter_ns()
        self_check_ok, self_check_errors = _zchat_prompt_pack_self_check(
            prompt_content,
            passport_content,
            request_name,
            has_concrete_manifest=has_concrete_manifest,
        )
        timings["self_check_ms"] = int((time.perf_counter_ns() - t_self_check_start) / 1_000_000)

        artifacts.append("request_manifest.json")
        required_reading_list = [
            f"1. Static manual (canonical): {manual_url}",
            f"2. Repo navigation (canonical): {nav_url}",
            f"3. This task prompt (read in full)",
        ]
        if resolved_urls:
            required_reading_list.append(
                "4. Required Task Source URLs: " + ", ".join(resolved_urls)
            )
        required_reading_list.append("5. Optional Task Source URLs / Side Files (if any)")
        manifest = {
            "manifest_version": "1.0",
            "request_name": request_name,
            "request_id": request_name,
            "created_at": now_utc,
            "mode": ZCHAT_MODE_PROMPT_PACK,
            "artifacts": artifacts,
            "profile": profile,
            "static_manual_url": manual_url,
            "repo_navigation_url": nav_url,
            "required_reading": required_reading_list,
            "required_task_source_urls": list(resolved_urls),
            "optional_task_source_urls": [],
            "side_files": [],
            "authority_order": [
                "1. Canonical public docs (static manual, repo navigation) — highest authority.",
                "2. This task prompt — overrides only where more specific and does not contradict canonical docs.",
                "3. Required task source URLs — below canonical docs; above optional sources.",
                "4. Optional task source URLs / side files — lowest authority among provided sources.",
                "5. External search / web results — never above any provided source.",
                "6. Guessing / fabrication — never allowed.",
            ],
            "missing_information_policy": "BLOCKED_MISSING_CONTEXT: stop, do not guess, do not produce ZIP",
            "source_policy": "public_github_raw_first",
            "branch_policy": "temporary_branch_only_if_public_insufficient",
            "dependencies": resolved_urls,
            "source_urls": resolved_urls,
            "allowed_paths": normalized_allowed,
            "forbidden_paths": normalized_forbidden,
            "expected_outputs": normalized_expected,
            "verification_files": derived_verification_files,
            "self_check": {
                "passed": self_check_ok,
                "errors": self_check_errors,
            },
            "metadata": {
                "context_provided": bool(context),
                "constraints_provided": bool(constraints),
                "source_urls_count": len(resolved_urls),
                "has_allowed_paths": bool(normalized_allowed),
                "has_forbidden_paths": bool(normalized_forbidden),
                "has_expected_outputs": bool(normalized_expected),
                "branch_may_be_needed": not resolved_urls,
                "create_branch": False,
            },
        }
        manifest_path = output_dir / "request_manifest.json"
        _atomic_write_json(manifest_path, manifest)

        prompt_lines = prompt_content.count("\n") + 1
        passport_lines = passport_content.count("\n") + 1
        timings["prompt_pack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

        return ZchatPromptPackResult(
            request_id=request_name,
            output_dir=str(output_dir),
            artifacts=artifacts,
            status="completed",
            profile=profile,
            timings=timings,
            prompt_lines=prompt_lines,
            passport_lines=passport_lines,
        )
    except Exception as e:
        timings["prompt_pack_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZchatPromptPackResult(
            request_id=request_name,
            output_dir=str(output_dir),
            status="failed",
            error=f"{type(e).__name__}: {e}",
            profile=profile,
            timings=timings,
        )


def _zchat_validate_import_common(
    *,
    zip_path: Path | None = None,
    pack_dir: Path | None = None,
    zip_entries: list[str] | None = None,
    target_root: Path,
) -> tuple[str, dict, list[str], str]:
    if zip_path is not None:
        if not zip_path.exists():
            return ZCHAT_VERDICT_REJECTED_STRUCTURAL, {}, [], f"ZIP file not found: {zip_path}"
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                entries = [info.filename.replace("\\", "/") for info in zf.infolist()]
        except zipfile.BadZipFile as e:
            return ZCHAT_VERDICT_REJECTED_STRUCTURAL, {}, [], f"Bad ZIP file: {e}"
    elif zip_entries is not None:
        entries = list(zip_entries)
    else:
        return ZCHAT_VERDICT_REJECTED_STRUCTURAL, {}, [], "No ZIP path or entries provided"

    top_level = set()
    for entry in entries:
        parts = entry.split("/")
        if parts and parts[0]:
            if len(parts) > 1:
                top_level.add(parts[0] + "/")
            else:
                top_level.add(parts[0])

    required = {"manifest.json", "checksums.sha256", "payload/"}
    missing = required - top_level
    if missing:
        return ZCHAT_VERDICT_REJECTED_STRUCTURAL, {}, [], f"Missing required top-level entries: {sorted(missing)}"

    if zip_path is not None:
        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest_raw = zf.read("manifest.json")
    else:
        manifest_path_obj = pack_dir / "manifest.json" if pack_dir is not None else None
        if manifest_path_obj is None or not manifest_path_obj.exists():
            return ZCHAT_VERDICT_REJECTED_STRUCTURAL, {}, [], "manifest.json not found"
        manifest_raw = manifest_path_obj.read_bytes()

    try:
        manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    except json.JSONDecodeError as e:
        return ZCHAT_VERDICT_REJECTED_STRUCTURAL, {}, [], f"Invalid manifest JSON: {e}"

    if not isinstance(manifest, dict):
        return ZCHAT_VERDICT_REJECTED_STRUCTURAL, {}, [], "manifest.json must be a JSON object"

    schema_errors = _validate_zchat_import_manifest_schema_like(manifest)
    if schema_errors:
        details = "; ".join(schema_errors[:3])
        return ZCHAT_VERDICT_REJECTED_STRUCTURAL, manifest, schema_errors, f"Manifest schema-like validation failed: {details}"

    payload_files = manifest.get("payload_files", [])
    if not isinstance(payload_files, list) or not payload_files:
        return ZCHAT_VERDICT_REJECTED_STRUCTURAL, manifest, [], "payload_files missing or empty in manifest"

    scope_errors: list[str] = []
    manifest_allowed = manifest.get("allowed_paths")
    manifest_forbidden = manifest.get("forbidden_paths")

    for pf in payload_files:
        if not isinstance(pf, dict):
            scope_errors.append(f"Invalid payload_files entry (not dict): {pf}")
            continue
        file_path = str(pf.get("path", ""))
        global_violation = _zchat_forbidden_path(file_path, target_root)
        if global_violation:
            scope_errors.append(global_violation)
            continue
        policy_violation = _zchat_check_path_policy(
            file_path,
            allowed_paths=manifest_allowed if isinstance(manifest_allowed, list) else None,
            forbidden_paths=manifest_forbidden if isinstance(manifest_forbidden, list) else None,
        )
        if policy_violation:
            scope_errors.append(policy_violation)

    if scope_errors:
        details = "; ".join(scope_errors[:3])
        return ZCHAT_VERDICT_REJECTED_SCOPE, manifest, scope_errors, f"Scope/policy violations: {details}"

    return ZCHAT_VERDICT_ACCEPTED, manifest, [], ""


def zchat_import_pack(
    zip_path: Path,
    *,
    target_root: Path | None = None,
) -> ZchatImportPackResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    if target_root is None:
        target_root = REPO_ROOT
    target_root = target_root.resolve(strict=True)

    import_slug = _zchat_slug_id()
    report_path = ZCHAT_RUNTIME_IMPORTS / import_slug / f"import_report_{uuid.uuid4().hex[:12]}.md"
    ZCHAT_RUNTIME_IMPORTS.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# Zchat Import Report",
        "",
        f"- **ZIP**: `{zip_path}`",
        f"- **Target root**: `{target_root}`",
        f"- **Started at**: {_utcnow()}",
        "",
    ]

    t_manifest_start = time.perf_counter_ns()

    common_verdict, manifest, common_errors, common_error_msg = _zchat_validate_import_common(
        zip_path=zip_path,
        target_root=target_root,
    )
    timings["import_manifest_ms"] = int((time.perf_counter_ns() - t_manifest_start) / 1_000_000)

    if common_verdict != ZCHAT_VERDICT_ACCEPTED:
        verdict_label = common_verdict.replace("_", " ").title()
        report_lines.append(f"## Verdict: {common_verdict}")
        report_lines.append(f"\n**Error**: {common_error_msg}")
        if common_errors:
            report_lines.append("")
            report_lines.append("### Details")
            for err in common_errors:
                report_lines.append(f"- {err}")
        report_lines.append("")
        timings["import_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=common_verdict,
            status="failed",
            error=common_error_msg,
            report_path=str(report_path),
            timings=timings,
        )

    package_id = str(manifest.get("package_id", ""))
    payload_files = manifest.get("payload_files", [])

    report_lines.append(f"- **Package ID**: `{package_id}`")
    report_lines.append(f"- **Payload files**: {len(payload_files)}")
    report_lines.append("")

    t_hash_start = time.perf_counter_ns()

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            checksums_raw = zf.read("checksums.sha256").decode("utf-8-sig")
    except KeyError:
        timings["import_hash_ms"] = int((time.perf_counter_ns() - t_hash_start) / 1_000_000)
        timings["import_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: checksums.sha256 not found in ZIP\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="checksums.sha256 not found in ZIP",
            report_path=str(report_path),
            timings=timings,
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
        timings["import_hash_ms"] = int((time.perf_counter_ns() - t_hash_start) / 1_000_000)
        timings["import_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: checksums.sha256 is empty\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="checksums.sha256 is empty",
            report_path=str(report_path),
            timings=timings,
        )

    with zipfile.ZipFile(zip_path, "r") as zf:
        zip_entries = [info.filename.replace("\\", "/") for info in zf.infolist()]

    manifest_payload_paths = set()
    for pf in payload_files:
        if isinstance(pf, dict):
            manifest_payload_paths.add("payload/" + str(pf.get("path", "")).replace("\\", "/"))

    all_payload_entries = [e for e in zip_entries if e.startswith("payload/") and not e.endswith("/")]
    extra_payload_entries = [e for e in all_payload_entries if e not in manifest_payload_paths]
    if extra_payload_entries:
        timings["import_hash_ms"] = int((time.perf_counter_ns() - t_hash_start) / 1_000_000)
        timings["import_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: Extra payload files not in manifest: {sorted(extra_payload_entries)}")
        report_lines.append("")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"Extra payload files not in manifest: {len(extra_payload_entries)}",
            report_path=str(report_path),
            timings=timings,
        )

    commit_ops: list[tuple[Path, bytes, str, str]] = []
    checksum_errors: list[str] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for pf in payload_files:
            file_path = str(pf.get("path", ""))
            manifest_sha = str(pf.get("sha256", "")).lower()
            zip_member = "payload/" + file_path.replace("\\", "/")

            if zip_member not in zip_entries:
                checksum_errors.append(f"File in manifest but missing in ZIP: {file_path}")
                continue

            file_data = zf.read(zip_member)
            actual_sha = _sha256_hex(file_data)
            expected_sha = expected_checksums.get(file_path, manifest_sha)

            if expected_sha and actual_sha != expected_sha:
                checksum_errors.append(
                    f"Checksum mismatch for {file_path}: expected {expected_sha}, got {actual_sha}"
                )
                continue

            if manifest_sha and actual_sha != manifest_sha:
                checksum_errors.append(
                    f"Manifest checksum mismatch for {file_path}: expected {manifest_sha}, got {actual_sha}"
                )
                continue

            dest_path = target_root / file_path
            commit_ops.append((dest_path, file_data, file_path, actual_sha))

    timings["import_hash_ms"] = int((time.perf_counter_ns() - t_hash_start) / 1_000_000)

    if checksum_errors:
        timings["import_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append("")
        report_lines.append("### Checksum Errors")
        for ce in checksum_errors:
            report_lines.append(f"- {ce}")
        report_lines.append("")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            package_id=package_id,
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="; ".join(checksum_errors),
            report_path=str(report_path),
            files_imported=0,
            files_skipped=len(payload_files),
            timings=timings,
        )

    if not commit_ops:
        timings["import_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\nNo files passed validation.\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            package_id=package_id,
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="No files passed validation",
            report_path=str(report_path),
            timings=timings,
        )

    t_extract_start = time.perf_counter_ns()

    imported = 0
    skipped = 0
    write_errors: list[str] = []
    written_paths: list[Path] = []
    report_lines.append("### Extracted Files")
    report_lines.append("")

    for dest_path, file_data, file_path, actual_sha in commit_ops:
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(file_data)
            written_paths.append(dest_path)
            report_lines.append(f"- `{file_path}` (sha256: `{actual_sha}`)")
            imported += 1
        except OSError as e:
            write_errors.append(f"Failed to write {file_path}: {e}")
            break

    timings["import_extract_ms"] = int((time.perf_counter_ns() - t_extract_start) / 1_000_000)
    timings["import_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

    if write_errors:
        for wp in written_paths:
            try:
                wp.unlink(missing_ok=True)
            except OSError:
                pass
        report_lines.append("")
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append("")
        report_lines.append("### Write Errors")
        for we in write_errors:
            report_lines.append(f"- {we}")
        if written_paths:
            report_lines.append(f"\nRolled back {len(written_paths)} previously written file(s) on write failure.\n")
        report_lines.append("")
        report_lines.append(f"- **Files imported**: 0")
        report_lines.append(f"- **Files skipped**: {len(commit_ops)}")
        report_lines.append("")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatImportPackResult(
            package_id=package_id,
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="; ".join(write_errors),
            report_path=str(report_path),
            files_imported=0,
            files_skipped=len(commit_ops),
            timings=timings,
        )

    report_lines.append("")
    report_lines.append(f"## Verdict: {ZCHAT_VERDICT_ACCEPTED}")
    report_lines.append(f"\nAll {imported} file(s) imported successfully.\n")
    report_lines.append("")
    report_lines.append(f"- **Files imported**: {imported}")
    report_lines.append(f"- **Files skipped**: {skipped}")
    report_lines.append("")

    report_lines.append("### Timings")
    for k in ["import_manifest_ms", "import_hash_ms", "import_extract_ms", "import_zip_open_ms"]:
        report_lines.append(f"- **{k}**: {timings.get(k, 0)} ms")
    report_lines.append("")

    _atomic_write_text(report_path, "\n".join(report_lines))

    return ZchatImportPackResult(
        package_id=package_id,
        verdict=ZCHAT_VERDICT_ACCEPTED,
        status="completed",
        error="",
        report_path=str(report_path),
        files_imported=imported,
        files_skipped=skipped,
        timings=timings,
    )


def zchat_verify_pack(
    pack_dir: Path,
    *,
    repo_root: Path | None = None,
) -> ZchatVerifyPackResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    if repo_root is None:
        repo_root = REPO_ROOT
    repo_root = repo_root.resolve(strict=True)

    pack_dir = pack_dir.resolve(strict=False)
    if not pack_dir.exists():
        timings["verify_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZchatVerifyPackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"Pack directory not found: {pack_dir}",
            timings=timings,
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
    checksums_path = pack_dir / "checksums.sha256"
    payload_dir = pack_dir / "payload"

    t_manifest_start = time.perf_counter_ns()

    if manifest_path.exists():
        manifest_data = _read_json_safe(manifest_path)
        if isinstance(manifest_data, dict):
            schema_errors = _validate_zchat_import_manifest_schema_like(manifest_data)
            if schema_errors:
                structural_issues.extend(schema_errors)
            else:
                mode = str(manifest_data.get("mode", ""))
                if mode not in ZCHAT_VALID_MODES:
                    structural_issues.append(f"Unknown mode in manifest: {mode}")
        else:
            structural_issues.append("manifest.json is not a valid JSON object")
    else:
        structural_issues.append("manifest.json is missing")

    if isinstance(manifest_data, dict) and not structural_issues:
        payload_files = manifest_data.get("payload_files", [])
        if not isinstance(payload_files, list):
            structural_issues.append("payload_files is not a list in manifest")
        else:
            for pf in payload_files:
                if not isinstance(pf, dict):
                    structural_issues.append(f"Invalid payload_files entry: {pf}")
                    continue
                file_path = str(pf.get("path", ""))
                global_violation = _zchat_forbidden_path(file_path, repo_root)
                if global_violation:
                    scope_issues.append(global_violation)
                else:
                    manifest_allowed = manifest_data.get("allowed_paths")
                    manifest_forbidden = manifest_data.get("forbidden_paths")
                    policy_violation = _zchat_check_path_policy(
                        file_path,
                        allowed_paths=manifest_allowed if isinstance(manifest_allowed, list) else None,
                        forbidden_paths=manifest_forbidden if isinstance(manifest_forbidden, list) else None,
                    )
                    if policy_violation:
                        scope_issues.append(policy_violation)
                actual_path = payload_dir / file_path
                if not actual_path.exists():
                    structural_issues.append(f"File referenced in manifest but missing from payload: {file_path}")

    timings["verify_manifest_ms"] = int((time.perf_counter_ns() - t_manifest_start) / 1_000_000)

    t_checksums_start = time.perf_counter_ns()

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
            pfs = manifest_data.get("payload_files", []) if isinstance(manifest_data, dict) else []
            for pf in pfs:
                file_path = str(pf.get("path", ""))
                manifest_sha = str(pf.get("sha256", "")).lower()
                expected_sha = expected.get(file_path, "")
                if expected_sha and manifest_sha and expected_sha != manifest_sha:
                    structural_issues.append(
                        f"Checksum mismatch for {file_path}: manifest={manifest_sha}, checksums={expected_sha}"
                    )

    timings["verify_checksums_ms"] = int((time.perf_counter_ns() - t_checksums_start) / 1_000_000)

    t_payload_start = time.perf_counter_ns()

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
            structural_issues.append(f"Extra payload files not in manifest: {sorted(extra)}")
        missing = manifest_files - payload_files_on_disk
        if missing:
            structural_issues.append(f"Files in manifest but missing from payload/: {sorted(missing)}")

    timings["verify_payload_ms"] = int((time.perf_counter_ns() - t_payload_start) / 1_000_000)

    if structural_issues:
        verdict = ZCHAT_VERDICT_REJECTED_STRUCTURAL
    elif scope_issues:
        verdict = ZCHAT_VERDICT_REJECTED_SCOPE
    elif warnings:
        verdict = ZCHAT_VERDICT_NEEDS_DECISION
    else:
        verdict = ZCHAT_VERDICT_ACCEPTED

    timings["verify_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

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

    report_lines.append("### Timings")
    for k in ["verify_manifest_ms", "verify_checksums_ms", "verify_payload_ms", "verify_ms"]:
        report_lines.append(f"- **{k}**: {timings.get(k, 0)} ms")
    report_lines.append("")

    _atomic_write_text(report_path, "\n".join(report_lines))

    return ZchatVerifyPackResult(
        verdict=verdict,
        status="completed",
        error="",
        report_path=str(report_path),
        timings=timings,
    )


def zchat_receive_pack(
    zip_path: Path,
    *,
    target_root: Path | None = None,
) -> ZchatReceivePackResult:
    t_total_start = time.perf_counter_ns()
    timings: dict[str, int] = {}

    if target_root is None:
        target_root = REPO_ROOT
    target_root = target_root.resolve(strict=True)

    receive_slug = _zchat_slug_id()
    quarantine_dir = ZCHAT_RUNTIME_QUARANTINE / receive_slug
    ZCHAT_RUNTIME_QUARANTINE.mkdir(parents=True, exist_ok=True)

    report_path = quarantine_dir / "receive_report.md"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# Zchat Receive Report",
        "",
        f"- **ZIP**: `{zip_path}`",
        f"- **Quarantine**: `{quarantine_dir}`",
        f"- **Started at**: {_utcnow()}",
        "",
    ]

    t_open = time.perf_counter_ns()

    common_verdict, manifest, common_errors, common_error_msg = _zchat_validate_import_common(
        zip_path=zip_path,
        target_root=target_root,
    )
    timings["receive_manifest_ms"] = int((time.perf_counter_ns() - t_open) / 1_000_000)

    if common_verdict != ZCHAT_VERDICT_ACCEPTED:
        verdict_label = common_verdict.replace("_", " ").title()
        report_lines.append(f"## Verdict: {common_verdict}")
        report_lines.append(f"\n**Error**: {common_error_msg}")
        if common_errors:
            report_lines.append("")
            report_lines.append("### Details")
            for err in common_errors:
                report_lines.append(f"- {err}")
        report_lines.append("")
        _atomic_write_text(report_path, "\n".join(report_lines))
        timings["receive_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZchatReceivePackResult(
            verdict=common_verdict,
            status="failed",
            error=common_error_msg,
            report_path=str(report_path),
            quarantine_dir=str(quarantine_dir),
            timings=timings,
        )

    package_id = str(manifest.get("package_id", ""))
    payload_files = manifest.get("payload_files", [])

    report_lines.append(f"- **Package ID**: `{package_id}`")
    report_lines.append(f"- **Payload files**: {len(payload_files)}")
    report_lines.append("")

    t_hash_start = time.perf_counter_ns()

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            checksums_raw = zf.read("checksums.sha256").decode("utf-8-sig")
    except KeyError:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: checksums.sha256 not found in ZIP\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        timings["receive_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZchatReceivePackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="checksums.sha256 not found in ZIP",
            report_path=str(report_path),
            quarantine_dir=str(quarantine_dir),
            timings=timings,
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
        timings["receive_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZchatReceivePackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="checksums.sha256 is empty",
            report_path=str(report_path),
            quarantine_dir=str(quarantine_dir),
            timings=timings,
        )

    with zipfile.ZipFile(zip_path, "r") as zf:
        zip_entries = [info.filename.replace("\\", "/") for info in zf.infolist()]

    manifest_payload_paths = set()
    for pf in payload_files:
        if isinstance(pf, dict):
            manifest_payload_paths.add("payload/" + str(pf.get("path", "")).replace("\\", "/"))

    all_payload_entries = [e for e in zip_entries if e.startswith("payload/") and not e.endswith("/")]
    extra_payload_entries = [e for e in all_payload_entries if e not in manifest_payload_paths]
    if extra_payload_entries:
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append(f"\n**Error**: Extra payload files not in manifest: {sorted(extra_payload_entries)}")
        report_lines.append("")
        _atomic_write_text(report_path, "\n".join(report_lines))
        timings["receive_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)
        return ZchatReceivePackResult(
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error=f"Extra payload files not in manifest: {len(extra_payload_entries)}",
            report_path=str(report_path),
            quarantine_dir=str(quarantine_dir),
            timings=timings,
        )

    t_extract_start = time.perf_counter_ns()
    extracted = 0
    checksum_errors: list[str] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for pf in payload_files:
            file_path = str(pf.get("path", ""))
            manifest_sha = str(pf.get("sha256", "")).lower()
            zip_member = "payload/" + file_path.replace("\\", "/")

            if zip_member not in zip_entries:
                checksum_errors.append(f"File in manifest but missing in ZIP: {file_path}")
                continue

            file_data = zf.read(zip_member)
            actual_sha = _sha256_hex(file_data)
            expected_sha = expected_checksums.get(file_path, manifest_sha)

            if expected_sha and actual_sha != expected_sha:
                checksum_errors.append(
                    f"Checksum mismatch for {file_path}: expected {expected_sha}, got {actual_sha}"
                )
                continue

            if manifest_sha and actual_sha != manifest_sha:
                checksum_errors.append(
                    f"Manifest checksum mismatch for {file_path}: expected {manifest_sha}, got {actual_sha}"
                )
                continue

            dest_path = quarantine_dir / "payload" / file_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(file_data)
            extracted += 1
            report_lines.append(f"- Extracted to quarantine: `{file_path}` (sha256: `{actual_sha}`)")

    timings["receive_hash_ms"] = int((time.perf_counter_ns() - t_hash_start) / 1_000_000)
    timings["receive_extract_ms"] = int((time.perf_counter_ns() - t_extract_start) / 1_000_000)
    timings["receive_zip_open_ms"] = int((time.perf_counter_ns() - t_total_start) / 1_000_000)

    if checksum_errors:
        report_lines.append("")
        report_lines.append(f"## Verdict: {ZCHAT_VERDICT_REJECTED_STRUCTURAL}")
        report_lines.append("")
        report_lines.append("### Checksum Errors")
        for ce in checksum_errors:
            report_lines.append(f"- {ce}")
        report_lines.append("")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatReceivePackResult(
            package_id=package_id,
            verdict=ZCHAT_VERDICT_REJECTED_STRUCTURAL,
            status="failed",
            error="; ".join(checksum_errors),
            report_path=str(report_path),
            quarantine_dir=str(quarantine_dir),
            files_received=extracted,
            timings=timings,
        )

    report_lines.append("")
    report_lines.append(f"## Verdict: {ZCHAT_VERDICT_ACCEPTED}")
    report_lines.append(f"\nAll {extracted} file(s) received into quarantine.\n")
    report_lines.append("")
    report_lines.append(f"- **Files received**: {extracted}")
    report_lines.append(f"- **Quarantine dir**: `{quarantine_dir}`")
    report_lines.append("")
    report_lines.append("## IMPORTANT: Files are in QUARANTINE only")
    report_lines.append("")
    report_lines.append("- Files are NOT applied to the repository.")
    report_lines.append("- Run `zchat_inspect_verification_pack` to check verification files for dangerous patterns.")
    report_lines.append("- Verify checksums and review contents before any decision.")
    report_lines.append("- Apply is NOT implemented; use `zchat_import_pack` for legacy direct-apply.")
    report_lines.append("")

    report_lines.append("### Timings")
    for k in ["receive_zip_open_ms", "receive_manifest_ms", "receive_hash_ms", "receive_extract_ms"]:
        report_lines.append(f"- **{k}**: {timings.get(k, 0)} ms")
    report_lines.append("")

    _atomic_write_text(report_path, "\n".join(report_lines))

    return ZchatReceivePackResult(
        package_id=package_id,
        verdict=ZCHAT_VERDICT_ACCEPTED,
        status="completed",
        report_path=str(report_path),
        quarantine_dir=str(quarantine_dir),
        files_received=extracted,
        timings=timings,
    )


def zchat_inspect_verification_pack(
    quarantine_dir: Path,
    *,
    verification_files: list[str] | None = None,
) -> ZchatInspectVerificationPackResult:
    quarantine_dir = quarantine_dir.resolve(strict=False)

    inspect_slug = _zchat_slug_id()
    report_path = quarantine_dir / "inspect_report.md"

    report_lines = [
        "# Zchat Inspection Report",
        "",
        f"- **Quarantine dir**: `{quarantine_dir}`",
        f"- **Inspection time**: {_utcnow()}",
        "",
    ]

    if not quarantine_dir.exists():
        report_lines.append(f"## Verdict: {ZCHAT_INSPECT_NOT_PRESENT}")
        report_lines.append(f"\nQuarantine directory not found.\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatInspectVerificationPackResult(
            verdict=ZCHAT_INSPECT_NOT_PRESENT,
            status="completed",
            report_path=str(report_path),
        )

    manifest_path = quarantine_dir / "manifest.json"
    manifest_data = _read_json_safe(manifest_path)

    resolved_vf: list[str] = []
    if verification_files:
        resolved_vf = list(verification_files)
    elif isinstance(manifest_data, dict) and manifest_data.get("manifest_version") == "2.0":
        vf_from_manifest = manifest_data.get("verification_files")
        if isinstance(vf_from_manifest, list):
            resolved_vf = [str(v) for v in vf_from_manifest]

    if not resolved_vf:
        report_lines.append(f"## Verdict: {ZCHAT_INSPECT_NOT_PRESENT}")
        report_lines.append(f"\nNo verification_files specified.\n")
        _atomic_write_text(report_path, "\n".join(report_lines))
        return ZchatInspectVerificationPackResult(
            verdict=ZCHAT_INSPECT_NOT_PRESENT,
            status="completed",
            report_path=str(report_path),
        )

    findings: list[dict] = []
    has_unsafe = False
    has_warning = False

    for vf_path_str in resolved_vf:
        vf_file = quarantine_dir / "payload" / vf_path_str
        if not vf_file.exists():
            findings.append({
                "file": vf_path_str,
                "status": "missing",
                "category": "not_present",
                "details": "Verification file not found in quarantine payload",
            })
            continue

        try:
            content = vf_file.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            findings.append({
                "file": vf_path_str,
                "status": "unreadable",
                "category": "error",
                "details": "Could not read verification file",
            })
            continue

        for pattern, category in ZCHAT_DANGEROUS_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
            if matches:
                for match in matches[:3]:
                    finding = {
                        "file": vf_path_str,
                        "status": "unsafe",
                        "category": category,
                        "details": f"Pattern '{pattern}' matched: {str(match)[:120]}",
                    }
                    findings.append(finding)
                    if category in {"shell_subprocess", "code_execution", "git_push", "env_secrets_access", "network_install", "network_download", "file_deletion", "writes_outside_scope"}:
                        has_unsafe = True
                    elif category in {"git_commit", "git_mutation", "git_access", "absolute_path", "path_traversal"}:
                        has_warning = True

        if not any(f["file"] == vf_path_str for f in findings):
            findings.append({
                "file": vf_path_str,
                "status": "clean",
                "category": "safe",
                "details": "No dangerous patterns detected",
            })

    if has_unsafe:
        verdict = ZCHAT_INSPECT_UNSAFE
    elif has_warning:
        verdict = ZCHAT_INSPECT_NEEDS_HUMAN
    else:
        verdict = ZCHAT_INSPECT_SAFE

    report_lines.append(f"## Verdict: {verdict}")
    report_lines.append("")

    report_lines.append("### Findings")
    report_lines.append("")
    for f in findings:
        report_lines.append(f"- **{f['file']}** [{f['category']}]: {f['details']}")
    report_lines.append("")

    report_lines.append("### Trust Chain Reminder")
    report_lines.append("")
    report_lines.append("- external answer != accepted")
    report_lines.append("- created ZIP != received")
    report_lines.append("- received to quarantine != applied to repo")
    report_lines.append("- verification code exists != safe to run")
    report_lines.append("- verified != accepted")
    report_lines.append("- accepted != committed")
    report_lines.append("")

    _atomic_write_text(report_path, "\n".join(report_lines))

    return ZchatInspectVerificationPackResult(
        verdict=verdict,
        status="completed",
        report_path=str(report_path),
        findings=findings,
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
    parser.add_argument(
        "--zchat-allowed-paths",
        type=str,
        default=None,
        help="Comma-separated allowed path prefixes for zchat prompt_pack",
    )
    parser.add_argument(
        "--zchat-forbidden-paths",
        type=str,
        default=None,
        help="Comma-separated forbidden path prefixes for zchat prompt_pack",
    )
    parser.add_argument(
        "--zchat-expected-outputs",
        type=str,
        default=None,
        help="Comma-separated expected output paths for zchat prompt_pack",
    )
    parser.add_argument(
        "--zchat-receive-pack",
        type=str,
        default=None,
        help="Path to ZIP file for zchat receive_pack (v2: extracts to quarantine only, never to repo)",
    )
    parser.add_argument(
        "--zchat-inspect-verification-pack",
        type=str,
        default=None,
        help="Path to quarantine directory for zchat inspect_verification_pack (reads verification_files, returns safety verdict)",
    )
    parser.add_argument(
        "--zchat-profile",
        type=str,
        default=ZCHAT_PROFILE_SLIM,
        help=f"Prompt-pack profile: {ZCHAT_PROFILE_SLIM} (default) or {ZCHAT_PROFILE_FULL}",
    )
    parser.add_argument(
        "--zchat-refresh-canonical-docs",
        action="store_true",
        help="Force refresh the canonical docs cache instead of using cached values",
    )
    parser.add_argument(
        "--zchat-verification-files",
        type=str,
        default=None,
        help="Comma-separated verification file paths for zchat prompt_pack (optional, default: none)",
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
        verification_files = None
        if args.zchat_verification_files:
            verification_files = [v.strip() for v in args.zchat_verification_files.split(",") if v.strip()]
        result = zchat_prompt_pack(
            task,
            output_dir=output_dir,
            context=args.zchat_context,
            constraints=args.zchat_constraints,
            source_urls=source_urls,
            allowed_paths=args.zchat_allowed_paths,
            forbidden_paths=args.zchat_forbidden_paths,
            expected_outputs=args.zchat_expected_outputs,
            profile=args.zchat_profile,
            refresh_canonical_docs=args.zchat_refresh_canonical_docs,
            verification_files=verification_files,
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

    if args.zchat_receive_pack:
        zip_path = Path(args.zchat_receive_pack)
        if not zip_path.exists():
            print(f"Error: ZIP file not found: {zip_path}", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        target_root = Path(args.directory) if args.directory else REPO_ROOT
        result = zchat_receive_pack(zip_path, target_root=target_root)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(EXIT_COMPLETED if result.status == "completed" else EXIT_FAILED)

    if args.zchat_inspect_verification_pack:
        quarantine_dir = Path(args.zchat_inspect_verification_pack)
        result = zchat_inspect_verification_pack(quarantine_dir)
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
