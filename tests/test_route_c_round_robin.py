import json
import sys
import tempfile
import threading
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import codex_token_monitor_route_c_round_robin as rr


def _make_accounts(count: int, provider: str = "ollama") -> list[dict[str, str]]:
    return [
        {
            "account_id": f"ollama{i+1}",
            "provider_id": provider,
            "model_id": f"model-{i+1}",
        }
        for i in range(count)
    ]


def test_reserve_cycles_through_accounts():
    accounts = _make_accounts(3)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        r1 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r1["index"] == 0
        assert r1["account_id"] == "ollama1"
        assert r1["provider_id"] == "ollama"
        assert r1["model_id"] == "model-1"

        r2 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r2["index"] == 1
        assert r2["account_id"] == "ollama2"

        r3 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r3["index"] == 2
        assert r3["account_id"] == "ollama3"

        r4 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r4["index"] == 0
        assert r4["account_id"] == "ollama1"
    finally:
        state_file.unlink(missing_ok=True)


def test_state_file_persists_between_calls():
    accounts = _make_accounts(5)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        r1 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r1["index"] == 0

        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["last_index"] == 0
        assert raw["last_account_id"] == "ollama1"
    finally:
        state_file.unlink(missing_ok=True)


def test_empty_state_file_starts_at_zero():
    accounts = _make_accounts(2)
    state_file = Path(tempfile.mktemp(suffix=".json"))
    state_file.write_text("{}", encoding="utf-8")

    try:
        r = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r["index"] == 0
        assert r["account_id"] == "ollama1"
    finally:
        state_file.unlink(missing_ok=True)


def test_corrupt_state_file_starts_fresh():
    accounts = _make_accounts(2)
    state_file = Path(tempfile.mktemp(suffix=".json"))
    state_file.write_text("not json", encoding="utf-8")

    try:
        r = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r["index"] == 0
        assert r["account_id"] == "ollama1"
    finally:
        state_file.unlink(missing_ok=True)


def test_single_account_always_returns_same():
    accounts = _make_accounts(1)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        for i in range(5):
            r = rr.reserve_next_account(accounts=accounts, state_file=state_file)
            assert r["index"] == 0
            assert r["account_id"] == "ollama1"
    finally:
        state_file.unlink(missing_ok=True)


def test_empty_accounts_raises():
    state_file = Path(tempfile.mktemp(suffix=".json"))
    try:
        rr.reserve_next_account(accounts=[], state_file=state_file)
        assert False, "should have raised"
    except ValueError:
        pass
    finally:
        state_file.unlink(missing_ok=True)


def test_non_existent_state_dir_created():
    accounts = _make_accounts(2)
    tmpdir = Path(tempfile.mkdtemp())
    nested = tmpdir / "sub" / "nested" / "state.json"

    try:
        r = rr.reserve_next_account(accounts=accounts, state_file=nested)
        assert r["index"] == 0
        assert nested.exists()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_full_5_account_round_robin_cycles():
    accounts = _make_accounts(5)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        seen_indices = []
        for _ in range(10):
            r = rr.reserve_next_account(accounts=accounts, state_file=state_file)
            seen_indices.append(r["index"])

        assert seen_indices == [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    finally:
        state_file.unlink(missing_ok=True)


def test_account_ids_are_distinct():
    accounts = _make_accounts(5)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        seen_ids = set()
        for _ in range(5):
            r = rr.reserve_next_account(accounts=accounts, state_file=state_file)
            seen_ids.add(r["account_id"])
        assert seen_ids == {f"ollama{i+1}" for i in range(5)}
    finally:
        state_file.unlink(missing_ok=True)


def test_concurrent_reservations_no_duplicates():
    accounts = _make_accounts(5)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    results = []
    errors = []
    lock = threading.Lock()

    def reserve():
        try:
            r = rr.reserve_next_account(accounts=accounts, state_file=state_file)
            with lock:
                results.append(r["index"])
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=reserve) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert not errors, f"Unexpected errors: {errors}"
        assert len(results) == 5
        assert sorted(results) == [0, 1, 2, 3, 4], (
            f"Expected one of each index 0-4, got {sorted(results)}"
        )
    finally:
        state_file.unlink(missing_ok=True)
        lock_file = state_file.parent / (state_file.name + ".lock")
        lock_file.unlink(missing_ok=True)


def test_reserve_skips_account_on_cooldown():
    accounts = _make_accounts(3)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        r1 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r1["account_id"] == "ollama1"

        failure = rr.record_account_failure(
            state_file=state_file,
            account_id="ollama2",
            category="quota_exhausted",
            reason="quota",
            summary="429 quota exceeded",
            timed_out=False,
            cooldown_seconds=3600,
        )
        assert failure["cooldown_applied"] is True

        r2 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r2["account_id"] == "ollama3"

        r3 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r3["account_id"] == "ollama1"
    finally:
        state_file.unlink(missing_ok=True)
        lock_file = state_file.parent / (state_file.name + ".lock")
        lock_file.unlink(missing_ok=True)


def test_timeout_cooldown_applies_after_threshold():
    accounts = _make_accounts(2)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        r1 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r1["account_id"] == "ollama1"

        f1 = rr.record_account_failure(
            state_file=state_file,
            account_id="ollama1",
            category="timed_out",
            reason="timed_out",
            summary="timed_out",
            timed_out=True,
            timeout_cooldown_seconds=900,
            timeout_cooldown_after_failures=2,
        )
        assert f1["cooldown_applied"] is False
        assert f1["consecutive_timeouts"] == 1

        f2 = rr.record_account_failure(
            state_file=state_file,
            account_id="ollama1",
            category="timed_out",
            reason="timed_out",
            summary="timed_out",
            timed_out=True,
            timeout_cooldown_seconds=900,
            timeout_cooldown_after_failures=2,
        )
        assert f2["cooldown_applied"] is True
        assert f2["consecutive_timeouts"] == 2

        r2 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r2["account_id"] == "ollama2"
    finally:
        state_file.unlink(missing_ok=True)
        lock_file = state_file.parent / (state_file.name + ".lock")
        lock_file.unlink(missing_ok=True)


def test_success_clears_existing_cooldown():
    accounts = _make_accounts(2)
    state_file = Path(tempfile.mktemp(suffix=".json"))

    try:
        rr.record_account_failure(
            state_file=state_file,
            account_id="ollama1",
            category="quota_exhausted",
            reason="quota",
            summary="429",
            timed_out=False,
            cooldown_seconds=3600,
        )
        rr.record_account_success(state_file=state_file, account_id="ollama1")

        r1 = rr.reserve_next_account(accounts=accounts, state_file=state_file)
        assert r1["account_id"] == "ollama1"
    finally:
        state_file.unlink(missing_ok=True)
        lock_file = state_file.parent / (state_file.name + ".lock")
        lock_file.unlink(missing_ok=True)


if __name__ == "__main__":
    passed = 0
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS {name}")
            except Exception as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
