from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.zworker_web_state import ZworkerWebRunState, sha256_text, is_valid_chat_url

REQUEST_ID = "ZWORKER-20260629-000001-test-state"


def test_resume_point_answer_ready(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("ANSWER_READY", chat_url="https://chatgpt.com/c/abc123")

    assert state.is_answer_ready() is True
    assert state.get_resume_point() == "answer_ready"
    assert state.can_skip_prompt_send() is True


def test_resume_point_download_phase(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("ZIP_LINK_FOUND", chat_url="https://chatgpt.com/c/abc123")

    assert state.is_in_download_phase() is True
    assert state.get_resume_point() == "download"


def test_resume_point_prompt_sent(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/c/abc123", prompt_sha256="abc")

    assert state.is_answer_ready() is False
    assert state.is_in_download_phase() is False
    assert state.get_resume_point() == "prompt_sent"
    assert state.can_skip_prompt_send() is True


def test_resume_point_start(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    assert state.get_resume_point() == "start"
    assert state.can_skip_prompt_send() is False


def test_resume_point_no_chat_url(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", prompt_sha256="abc")
    assert state.can_skip_prompt_send() is False


def test_require_prompt_send_allowed_with_chat_url(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/c/abc", prompt_sha256="abc")
    with pytest.raises(RuntimeError, match="already sent"):
        state.require_prompt_send_allowed(force=False)


def test_require_prompt_send_allowed_no_chat_url_allows_resend(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", prompt_sha256="abc")
    state.require_prompt_send_allowed(force=False)


def test_require_prompt_send_allowed_invalid_chat_url_allows_resend(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/", prompt_sha256="abc")
    state.require_prompt_send_allowed(force=False)


def test_state_writes_run_state_and_events(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("BROWSER_READY", browser_channel="chrome", headless=False)

    assert state.run_state_path.exists()
    assert state.events_path.exists()

    data = json.loads(state.run_state_path.read_text(encoding="utf-8"))
    assert data["request_id"] == REQUEST_ID
    assert data["state"] == "BROWSER_READY"
    assert data["metadata"]["browser_channel"] == "chrome"
    assert data["metadata"]["headless"] is False

    events = state.events_path.read_text(encoding="utf-8").splitlines()
    assert events
    assert any("BROWSER_READY" in line for line in events)


def test_prompt_hash_and_prompt_sent_guard(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    prompt_hash = sha256_text("hello")
    state.set_state("PROMPT_SENT", prompt_sha256=prompt_hash)

    assert state.prompt_sha256 == prompt_hash
    assert state.has_prompt_been_sent()

    state.require_prompt_send_allowed(force=False)

    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/c/abc123", prompt_sha256=prompt_hash)
    with pytest.raises(RuntimeError):
        state.require_prompt_send_allowed(force=False)

    state.require_prompt_send_allowed(force=True)


def test_load_existing_state(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("ZIP_VALID", zip_path="out.zip", zip_sha256="abc")

    loaded = ZworkerWebRunState.load(REQUEST_ID, runtime_root=tmp_path)
    assert loaded.state == "ZIP_VALID"
    assert loaded.zip_path == "out.zip"
    assert loaded.zip_sha256 == "abc"


def test_fail_records_machine_error(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.fail("FAILED_LOGIN_REQUIRED", "manual login required", recoverable=True)

    data = json.loads(state.run_state_path.read_text(encoding="utf-8"))
    assert data["state"] == "FAILED"
    assert data["last_error"]["code"] == "FAILED_LOGIN_REQUIRED"
    assert data["last_error"]["recoverable"] is True


def test_attach_mode_state_metadata(tmp_path: Path) -> None:
    cdp_url = "ws://localhost:9222/devtools/browser/abc123"
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state(
        "BROWSER_READY",
        browser_mode="attach",
        cdp_url=cdp_url,
        browser_channel="chrome",
        headless=False,
    )

    data = json.loads(state.run_state_path.read_text(encoding="utf-8"))
    assert data["state"] == "BROWSER_READY"
    assert data["metadata"]["browser_mode"] == "attach"
    assert data["metadata"]["cdp_url"] == cdp_url
    assert data["metadata"]["headless"] is False


def test_update_chat_url_persists_and_logs(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/", prompt_sha256="abc")

    state.update_chat_url("https://chatgpt.com/c/abc123", source="unit_test")

    data = json.loads(state.run_state_path.read_text(encoding="utf-8"))
    assert data["chat_url"] == "https://chatgpt.com/c/abc123"
    events = state.events_path.read_text(encoding="utf-8")
    assert "chat_url_updated" in events
    assert "unit_test" in events


def test_launch_mode_state_metadata(tmp_path: Path) -> None:
    profile_dir = "/path/to/profile"
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state(
        "BROWSER_READY",
        profile_dir=profile_dir,
        browser_channel="chrome",
        headless=False,
    )

    data = json.loads(state.run_state_path.read_text(encoding="utf-8"))
    assert data["state"] == "BROWSER_READY"
    assert data["metadata"]["profile_dir"] == profile_dir
    assert "browser_mode" not in data["metadata"] or data["metadata"].get("browser_mode") != "attach"


def test_cli_cdp_url_parsing() -> None:
    import argparse
    import sys
    from pathlib import Path as P

    runner_path = P(__file__).resolve().parents[1] / "scripts" / "zworker_chatgpt_web_runner.py"
    if not runner_path.exists():
        pytest.skip("web runner script not found")

    import importlib.util
    spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner", runner_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["zworker_chatgpt_web_runner"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)

    args = module.parse_args([
        "--request-id", "TEST-001",
        "--cdp-url", "ws://localhost:9222/devtools/browser/abc",
    ])
    assert args.cdp_url == "ws://localhost:9222/devtools/browser/abc"

    args_no_cdp = module.parse_args([
        "--request-id", "TEST-002",
    ])
    assert args_no_cdp.cdp_url == ""


def test_failed_marker_detection_in_assistant_only(monkeypatch) -> None:
    import importlib.util
    from pathlib import Path as P

    runner_path = P(__file__).resolve().parents[1] / "scripts" / "zworker_chatgpt_web_runner.py"
    if not runner_path.exists():
        pytest.skip("web runner script not found")

    spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner", runner_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class MockLocator:
        def __init__(self, text: str):
            self._text = text

        def inner_text(self, timeout=3000):
            return self._text

        def count(self):
            return 1

        @property
        def last(self):
            return self

        def is_visible(self):
            return True

    class MockPage:
        def __init__(self, body_text: str, assistant_text: str):
            self._body_text = body_text
            self._assistant_text = assistant_text

        def locator(self, selector: str):
            if selector == "body":
                return MockLocator(self._body_text)
            return MockLocator(self._assistant_text)

        def get_by_role(self, *args, **kwargs):
            return MockLocator("")

    user_prompt_with_failed = "Here is my task: ZWORKER_ZIP_FAILED: could not create zip"
    assistant_clean = "I will analyze the code and create a ZIP file with the result."

    page = MockPage(user_prompt_with_failed, assistant_clean)
    result = module.get_last_assistant_message_text(page)
    assert module.FAILED_MARKER[:-1] not in result, "FAILED_MARKER should not be detected in clean assistant response"

    user_prompt_clean = "Here is my task: build a login page"
    assistant_with_failed = f"I cannot create the ZIP. {module.FAILED_MARKER} insufficient permissions"

    page_fail = MockPage(user_prompt_clean, assistant_with_failed)
    result_fail = module.get_last_assistant_message_text(page_fail)
    assert module.FAILED_MARKER[:-1] in result_fail, "FAILED_MARKER should be detected in assistant response"

    user_prompt_clean = "Build a feature"
    assistant_with_ready = f"Here is the result. {module.READY_MARKER} request_id: TEST-001"

    page_ready = MockPage(user_prompt_clean, assistant_with_ready)
    result_ready = module.get_last_assistant_message_text(page_ready)
    assert module.READY_MARKER in result_ready, "READY_MARKER should be detected in assistant response"


def test_is_valid_chat_url_valid() -> None:
    assert is_valid_chat_url("https://chatgpt.com/c/abc123") is True
    assert is_valid_chat_url("https://chatgpt.com/c/xyz789") is True
    assert is_valid_chat_url("chatgpt.com/c/ABC") is True
    assert is_valid_chat_url("/c/abc123") is True


def test_is_valid_chat_url_invalid() -> None:
    assert is_valid_chat_url("https://chatgpt.com/") is False
    assert is_valid_chat_url("https://chatgpt.com") is False
    assert is_valid_chat_url("") is False
    assert is_valid_chat_url("https://chatgpt.com/explore") is False
    assert is_valid_chat_url("https://chatgpt.com/topic/abc") is False


def test_can_skip_prompt_send_rejects_bare_homepage(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/", prompt_sha256="abc")
    assert state.can_skip_prompt_send() is False


def test_can_skip_prompt_send_accepts_valid_chat_url(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/c/abc123", prompt_sha256="abc")
    assert state.can_skip_prompt_send() is True


def test_can_skip_prompt_send_rejects_invalid_chat_url(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/explore", prompt_sha256="abc")
    assert state.can_skip_prompt_send() is False


def test_resume_empty_chat_allows_resend(tmp_path: Path) -> None:
    state = ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)
    state.metadata["prompt_sent_at"] = "2026-06-30T00:00:00.000Z"
    state.set_state("PROMPT_SENT", chat_url="https://chatgpt.com/", prompt_sha256="abc")
    assert state.has_prompt_been_sent() is True
    assert state.can_skip_prompt_send() is False
    state.require_prompt_send_allowed(force=False)


def test_open_new_chat_does_not_store_invalid_url(tmp_path: Path) -> None:
    import importlib.util
    import sys
    from pathlib import Path as P

    runner_path = P(__file__).resolve().parents[1] / "scripts" / "zworker_chatgpt_web_runner.py"
    if not runner_path.exists():
        pytest.skip("web runner script not found")

    spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner", runner_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    state = module.ZworkerWebRunState(REQUEST_ID, runtime_root=tmp_path)

    class MockPage:
        @property
        def url(self):
            return "https://chatgpt.com/"

        def goto(self, *a, **kw):
            pass

        def wait_for_load_state(self, *a, **kw):
            pass

        def get_by_role(self, *a, **kw):
            return _FakeLoc()

        def get_by_text(self, *a, **kw):
            return _FakeLoc()

    class _FakeLoc:
        def count(self):
            return 0

    module.open_new_chat(MockPage(), state, 1000)
    assert state.chat_url == ""
    assert state.state == "CHAT_CREATED"
