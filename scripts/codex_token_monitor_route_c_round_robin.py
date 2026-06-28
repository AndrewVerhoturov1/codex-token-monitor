import json
import os
import platform
import time
from pathlib import Path
from typing import Any

_system = platform.system()

DEFAULT_QUOTA_COOLDOWN_SECONDS = 12 * 60 * 60
DEFAULT_TIMEOUT_COOLDOWN_SECONDS = 30 * 60
DEFAULT_TIMEOUT_FAILURE_THRESHOLD = 2
SUMMARY_SNIPPET_MAX_CHARS = 500


def _atomic_read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


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


def _acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
    if _system == "Windows":
        import msvcrt

        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return fd
            except OSError:
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd


def _release_lock(fd: int, lock_path: Path) -> None:
    try:
        if _system == "Windows":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _utc_timestamp() -> float:
    return time.time()


def _ensure_state_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _get_account_states(state: dict[str, Any]) -> dict[str, Any]:
    account_states = state.get("account_states")
    if isinstance(account_states, dict):
        return account_states
    account_states = {}
    state["account_states"] = account_states
    return account_states


def _get_account_state(state: dict[str, Any], account_id: str) -> dict[str, Any]:
    account_states = _get_account_states(state)
    account_state = account_states.get(account_id)
    if isinstance(account_state, dict):
        return account_state
    account_state = {}
    account_states[account_id] = account_state
    return account_state


def _cooldown_until_ts(account_state: dict[str, Any]) -> float:
    value = account_state.get("cooldown_until_ts", 0)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _cooldown_is_active(account_state: dict[str, Any], now_ts: float) -> bool:
    return _cooldown_until_ts(account_state) > now_ts


def _clear_cooldown(account_state: dict[str, Any]) -> None:
    account_state["cooldown_until_ts"] = 0
    account_state["cooldown_reason"] = ""


def _normalize_summary_snippet(text: str) -> str:
    snippet = (text or "").strip()
    if len(snippet) > SUMMARY_SNIPPET_MAX_CHARS:
        return snippet[:SUMMARY_SNIPPET_MAX_CHARS] + "..."
    return snippet


def reserve_next_account(
    *,
    accounts: list[dict[str, str]],
    state_file: Path,
) -> dict[str, Any]:
    if not accounts:
        raise ValueError("accounts list is empty")

    now_ts = _utc_timestamp()
    lock_path = state_file.parent / (state_file.name + ".lock")
    lock_fd = _acquire_lock(lock_path)
    try:
        state = _ensure_state_dict(_atomic_read_json(state_file))
        last_index = int(state.get("last_index", -1))

        chosen_index = -1
        chosen_account: dict[str, str] | None = None
        chosen_state: dict[str, Any] | None = None

        for offset in range(1, len(accounts) + 1):
            candidate_index = (last_index + offset) % len(accounts)
            candidate = accounts[candidate_index]
            account_id = str(candidate.get("account_id", "") or "")
            candidate_state = _get_account_state(state, account_id)
            if not _cooldown_is_active(candidate_state, now_ts):
                chosen_index = candidate_index
                chosen_account = candidate
                chosen_state = candidate_state
                break

        if chosen_account is None:
            chosen_index = (last_index + 1) % len(accounts)
            chosen_account = accounts[chosen_index]
            chosen_state = _get_account_state(
                state,
                str(chosen_account.get("account_id", "") or ""),
            )

        state["last_index"] = chosen_index
        state["last_account_id"] = chosen_account.get("account_id", "")
        state["last_updated"] = now_ts
        _atomic_write_json(state_file, state)
    finally:
        _release_lock(lock_fd, lock_path)

    assert chosen_account is not None
    assert chosen_state is not None
    return {
        "account_id": chosen_account.get("account_id", ""),
        "provider_id": chosen_account.get("provider_id", ""),
        "model_id": chosen_account.get("model_id", ""),
        "index": chosen_index,
        "cooldown_active": _cooldown_is_active(chosen_state, now_ts),
        "cooldown_until_ts": _cooldown_until_ts(chosen_state),
        "cooldown_reason": str(chosen_state.get("cooldown_reason", "") or ""),
    }


def record_account_success(
    *,
    state_file: Path,
    account_id: str,
) -> None:
    now_ts = _utc_timestamp()
    lock_path = state_file.parent / (state_file.name + ".lock")
    lock_fd = _acquire_lock(lock_path)
    try:
        state = _ensure_state_dict(_atomic_read_json(state_file))
        account_state = _get_account_state(state, account_id)
        account_state["consecutive_timeouts"] = 0
        account_state["last_result"] = "success"
        account_state["last_error_category"] = ""
        account_state["last_error_reason"] = ""
        account_state["last_summary_snippet"] = ""
        account_state["last_updated"] = now_ts
        _clear_cooldown(account_state)
        _atomic_write_json(state_file, state)
    finally:
        _release_lock(lock_fd, lock_path)


def record_account_failure(
    *,
    state_file: Path,
    account_id: str,
    category: str,
    reason: str,
    summary: str,
    timed_out: bool,
    cooldown_seconds: int = 0,
    timeout_cooldown_seconds: int = DEFAULT_TIMEOUT_COOLDOWN_SECONDS,
    timeout_cooldown_after_failures: int = DEFAULT_TIMEOUT_FAILURE_THRESHOLD,
) -> dict[str, Any]:
    now_ts = _utc_timestamp()
    lock_path = state_file.parent / (state_file.name + ".lock")
    lock_fd = _acquire_lock(lock_path)
    try:
        state = _ensure_state_dict(_atomic_read_json(state_file))
        account_state = _get_account_state(state, account_id)

        consecutive_timeouts = int(account_state.get("consecutive_timeouts", 0) or 0)
        if timed_out:
            consecutive_timeouts += 1
        else:
            consecutive_timeouts = 0
        account_state["consecutive_timeouts"] = consecutive_timeouts
        account_state["last_result"] = "failure"
        account_state["last_error_category"] = category
        account_state["last_error_reason"] = reason
        account_state["last_summary_snippet"] = _normalize_summary_snippet(summary)
        account_state["last_updated"] = now_ts

        applied_cooldown_seconds = 0
        cooldown_reason = ""
        if cooldown_seconds > 0:
            applied_cooldown_seconds = int(cooldown_seconds)
            cooldown_reason = category or reason or "failure"
        elif (
            timed_out
            and timeout_cooldown_seconds > 0
            and consecutive_timeouts >= max(int(timeout_cooldown_after_failures), 1)
        ):
            applied_cooldown_seconds = int(timeout_cooldown_seconds)
            cooldown_reason = "timeout_cooldown"

        existing_cooldown_until = _cooldown_until_ts(account_state)
        if applied_cooldown_seconds > 0:
            account_state["cooldown_until_ts"] = now_ts + applied_cooldown_seconds
            account_state["cooldown_reason"] = cooldown_reason
        elif existing_cooldown_until <= now_ts:
            _clear_cooldown(account_state)

        _atomic_write_json(state_file, state)
    finally:
        _release_lock(lock_fd, lock_path)

    return {
        "consecutive_timeouts": consecutive_timeouts,
        "cooldown_applied": applied_cooldown_seconds > 0,
        "cooldown_seconds": applied_cooldown_seconds,
        "cooldown_reason": cooldown_reason,
    }
