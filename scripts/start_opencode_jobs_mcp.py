import atexit
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.resolve(strict=False)
STATE_DIR = REPO_ROOT / "_local" / "codex-token-monitor"
PID_PATH = STATE_DIR / "opencode-jobs-mcp.pid.json"
STARTUP_LOG_PATH = STATE_DIR / "opencode-jobs-mcp-startup.log"
STARTER_ENV = "OPENCODE_JOBS_MCP_STARTED_VIA_STARTER"
MANAGED_MARKERS = (
    "codex_token_monitor_opencode_jobs_mcp",
    "start_opencode_jobs_mcp.py",
)
PYTHON_PROCESS_NAMES = frozenset({"python.exe", "python", "py.exe", "py"})
SCRIPT_REPO_PATTERN = re.compile(
    r"([A-Za-z]:[\\/][^\"\r\n]*?)[\\/]scripts[\\/](?:start_opencode_jobs_mcp\.py|codex_token_monitor_opencode_jobs_mcp\.py)",
    re.IGNORECASE,
)
LEGACY_MODULE_ENTRY_PATTERN = re.compile(
    r"(^|\s)-m\s+scripts\.codex_token_monitor_opencode_jobs_mcp(\s|$)",
    re.IGNORECASE,
)
LEGACY_SCRIPT_ENTRY_PATTERN = re.compile(
    r"(^|\s)(?:-[A-Za-z][A-Za-z0-9-]*\s+)*"
    r"(?:\"[^\"]*[\\/]scripts[\\/]codex_token_monitor_opencode_jobs_mcp\.py\"|"
    r"scripts[\\/]codex_token_monitor_opencode_jobs_mcp\.py)"
    r"(\s|$)",
    re.IGNORECASE,
)
STARTER_SCRIPT_ENTRY_PATTERN = re.compile(
    r"(^|\s)(?:-[A-Za-z][A-Za-z0-9-]*\s+)*"
    r"(?:\"[^\"]*[\\/]scripts[\\/]start_opencode_jobs_mcp\.py\"|"
    r"scripts[\\/]start_opencode_jobs_mcp\.py)"
    r"(\s|$)",
    re.IGNORECASE,
)


def _utcnow() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:3] + "Z"


def _normalize_path_text(value: str | None) -> str:
    if not value:
        return ""
    return str(Path(value).resolve(strict=False)).casefold()


def _current_command_line() -> str:
    return subprocess.list2cmdline([sys.executable, *sys.argv])


def _read_json_safe(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _append_startup_log(payload: dict[str, Any]) -> None:
    STARTUP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STARTUP_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _extract_repo_root_from_command_line(command_line: str) -> Path | None:
    match = SCRIPT_REPO_PATTERN.search(command_line)
    if not match:
        return None
    return Path(match.group(1)).resolve(strict=False)


def _is_managed_command_line(command_line: str) -> bool:
    if not command_line:
        return False
    return any(marker in command_line for marker in MANAGED_MARKERS)


def _is_python_entrypoint_process(process_name: str, command_line: str) -> bool:
    if Path(process_name).name.casefold() not in PYTHON_PROCESS_NAMES:
        return False
    if not _is_managed_command_line(command_line):
        return False
    return _managed_process_kind(command_line) is not None


def _managed_process_kind(command_line: str) -> str | None:
    command_norm = command_line.replace("/", "\\")
    if LEGACY_MODULE_ENTRY_PATTERN.search(command_norm):
        return "legacy_mcp"
    if LEGACY_SCRIPT_ENTRY_PATTERN.search(command_norm):
        return "legacy_mcp"
    if STARTER_SCRIPT_ENTRY_PATTERN.search(command_norm):
        return "starter"
    return None


def _normalize_process_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _classify_process_record(
    record: dict[str, Any],
    *,
    current_pid: int,
    repo_root: Path,
) -> tuple[bool, dict[str, Any]]:
    pid = _normalize_process_pid(record.get("pid"))
    command_line = str(record.get("command_line", "") or "")
    details = {
        "pid": pid,
        "name": str(record.get("name", "") or ""),
        "command_line": command_line,
        "source": str(record.get("source", "") or ""),
    }
    if pid is None:
        details["reason"] = "invalid_pid"
        return False, details
    if pid == current_pid:
        details["reason"] = "current_process"
        return False, details
    if not _is_managed_command_line(command_line):
        details["reason"] = "marker_missing"
        return False, details
    if not _is_python_entrypoint_process(details["name"], command_line):
        details["reason"] = "not_entrypoint_process"
        return False, details
    kind = _managed_process_kind(command_line)
    if kind is None:
        details["reason"] = "unknown_managed_kind"
        return False, details
    hinted_repo = _extract_repo_root_from_command_line(command_line)
    if hinted_repo is not None and hinted_repo.resolve(strict=False) != repo_root.resolve(strict=False):
        details["reason"] = "different_repo"
        details["repo_hint"] = str(hinted_repo)
        return False, details
    details["reason"] = "managed_match"
    details["kind"] = kind
    if hinted_repo is not None:
        details["repo_hint"] = str(hinted_repo)
    return True, details


def _parse_process_query_output(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if not text:
        return []
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    result: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "pid": item.get("ProcessId"),
                "parent_pid": item.get("ParentProcessId"),
                "name": item.get("Name") or "",
                "command_line": item.get("CommandLine") or "",
                "source": "process_scan",
            }
        )
    return result


def _list_candidate_process_records() -> list[dict[str, Any]]:
    query = (
        "$items = Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -like '*codex_token_monitor_opencode_jobs_mcp*' -or "
        "$_.CommandLine -like '*start_opencode_jobs_mcp.py*' "
        "} | Select-Object ProcessId, ParentProcessId, Name, CommandLine; "
        "if ($items) { $items | ConvertTo-Json -Compress }"
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", query],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "unknown PowerShell error").strip()
        raise RuntimeError(f"Failed to query processes: {message}")
    return _parse_process_query_output(proc.stdout)


def _is_pid_alive(pid: int) -> bool:
    proc = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return False
    output = proc.stdout.strip()
    if not output:
        return False
    return not output.startswith("INFO:")


def _stop_process(pid: int) -> tuple[bool, str]:
    proc = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    detail = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, detail or f"taskkill exit {proc.returncode}"
    for _ in range(20):
        if not _is_pid_alive(pid):
            return True, detail
        time.sleep(0.1)
    return False, detail or "process still alive after taskkill"


def _load_pid_record() -> dict[str, Any]:
    payload = _read_json_safe(PID_PATH)
    if not payload:
        return {}
    payload["source"] = "pid_file"
    return payload


def _build_cleanup_plan(
    *,
    current_pid: int,
    repo_root: Path,
    pid_record: dict[str, Any],
    scanned_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    kill_map: dict[int, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    stale_pid_file = False

    pid_value = _normalize_process_pid(pid_record.get("pid"))
    if pid_value is not None:
        if not _is_pid_alive(pid_value):
            stale_pid_file = True
            skipped.append(
                {
                    "pid": pid_value,
                    "command_line": str(pid_record.get("command_line", "") or ""),
                    "source": "pid_file",
                    "reason": "stale_pid_file",
                }
            )
        else:
            managed, details = _classify_process_record(
                pid_record,
                current_pid=current_pid,
                repo_root=repo_root,
            )
            if managed and details.get("kind") == "legacy_mcp":
                kill_map[pid_value] = details
            elif managed:
                details["reason"] = "sibling_starter_best_effort"
                skipped.append(details)
            else:
                skipped.append(details)

    for record in scanned_records:
        managed, details = _classify_process_record(
            record,
            current_pid=current_pid,
            repo_root=repo_root,
        )
        pid = details.get("pid")
        if managed and details.get("kind") == "legacy_mcp" and isinstance(pid, int):
            kill_map[pid] = details
        elif managed:
            details["reason"] = "sibling_starter_best_effort"
            skipped.append(details)
        else:
            skipped.append(details)

    kill_list = sorted(kill_map.values(), key=lambda item: int(item["pid"]))
    return kill_list, skipped, stale_pid_file


def _write_pid_record(*, current_pid: int, killed_pids: list[int]) -> None:
    _atomic_write_json(
        PID_PATH,
        {
            "pid": current_pid,
            "started_at": _utcnow(),
            "repo_root": str(REPO_ROOT),
            "command_line": _current_command_line(),
            "cleanup_killed_pids": killed_pids,
        },
    )


def _cleanup_pid_record() -> None:
    payload = _read_json_safe(PID_PATH)
    if _normalize_process_pid(payload.get("pid")) == os.getpid():
        PID_PATH.unlink(missing_ok=True)


def main() -> None:
    started_at = _utcnow()
    current_pid = os.getpid()
    cleanup_warnings: list[str] = []
    os.environ[STARTER_ENV] = "1"

    try:
        pid_record: dict[str, Any] = {}
        kill_list: list[dict[str, Any]] = []
        skipped_records: list[dict[str, Any]] = []
        stale_pid_file = False
        try:
            pid_record = _load_pid_record()
            scanned_records = _list_candidate_process_records()
            kill_list, skipped_records, stale_pid_file = _build_cleanup_plan(
                current_pid=current_pid,
                repo_root=REPO_ROOT,
                pid_record=pid_record,
                scanned_records=scanned_records,
            )
        except Exception as exc:
            cleanup_warnings.append(f"Cleanup scan failed: {type(exc).__name__}: {exc}")

        killed_pids: list[int] = []
        for record in kill_list:
            pid = int(record["pid"])
            stopped, detail = _stop_process(pid)
            if stopped:
                killed_pids.append(pid)
            else:
                cleanup_warnings.append(f"Failed to stop legacy pid {pid}: {detail}")

        if stale_pid_file and PID_PATH.exists():
            try:
                PID_PATH.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_warnings.append(f"Failed to remove stale pid file: {exc}")

        audit = {
            "started_at": started_at,
            "current_pid": current_pid,
            "repo_root": str(REPO_ROOT),
            "found_pids": [int(item["pid"]) for item in kill_list],
            "killed_pids": killed_pids,
            "skipped_pids": skipped_records,
            "errors": cleanup_warnings,
        }
        _append_startup_log(audit)

        _write_pid_record(current_pid=current_pid, killed_pids=killed_pids)
        atexit.register(_cleanup_pid_record)

        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        import codex_token_monitor_opencode_jobs_mcp as jobs_mcp

        jobs_mcp.main()
    except Exception as exc:
        failure_audit = {
            "started_at": started_at,
            "current_pid": current_pid,
            "repo_root": str(REPO_ROOT),
            "found_pids": [],
            "killed_pids": [],
            "skipped_pids": [],
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
        _append_startup_log(failure_audit)
        print(f"opencode_jobs MCP startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
