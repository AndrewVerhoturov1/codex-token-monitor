#!/usr/bin/env python3
"""ChatGPT Web + Playwright helper runner for future zworker-auto integration.

Scope:
- Google Chrome only;
- headful only;
- manual one-time login in a dedicated profile;
- no password/2FA/CAPTCHA automation;
- no private ChatGPT API usage;
- download a real ZIP from ChatGPT Web and pre-validate it before optional handoff.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from zworker_web_state import ZworkerWebRunState, sha256_text
from zworker_web_zip import validate_zip

CHATGPT_URL = "https://chatgpt.com/"
READY_MARKER = "ZWORKER_ZIP_READY"
FAILED_MARKER = "ZWORKER_ZIP_FAILED:"
MANIFEST_BEGIN = "ZWORKER_ZIP_MANIFEST_BEGIN"
MANIFEST_END = "ZWORKER_ZIP_MANIFEST_END"


class WebRunnerError(RuntimeError):
    def __init__(self, code: str, message: str, *, recoverable: bool = False):
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


def repo_root_from_script() -> Path:
    return _SCRIPT_DIR.parent


def default_runtime_root(repo_root: Path) -> Path:
    return repo_root / ".ai" / "zworker" / "runtime" / "web"


def request_dir(repo_root: Path, request_id: str) -> Path:
    return repo_root / ".ai" / "zworker" / "runtime" / "requests" / request_id


def read_request_prompt(repo_root: Path, request_id: str) -> tuple[str, Path, Path]:
    req_dir = request_dir(repo_root, request_id)
    prompt_path = req_dir / "prompt.md"
    manifest_path = req_dir / "request_manifest.json"
    if not prompt_path.exists():
        raise WebRunnerError("FAILED_REQUEST_NOT_FOUND", f"prompt.md not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8"), prompt_path, manifest_path


def build_automation_contract(request_id: str) -> str:
    zip_name = f"{request_id}-zworker-result.zip"
    return f"""

---

# AUTOMATION ZIP MARKING CONTRACT

You must create and attach a real downloadable ZIP file.

ZIP filename must be exactly:
{zip_name}

ZIP requirements:
- answer.md must be at the ZIP root.
- Any created or modified repo files must be inside the ZIP using repo-relative paths.
- Do not use payload/.
- Do not include manifest.json unless the task explicitly asks.
- Do not include absolute paths.
- Do not include paths with .. traversal.
- Do not include files outside allowed_paths.
- Do not include files inside forbidden_paths.
- If images, HTML, scripts, docs, or code are part of the result, include them in the ZIP.

When the ZIP is attached, write this exact block in the same final assistant message:

{MANIFEST_BEGIN}
request_id: {request_id}
zip_filename: {zip_name}
zip_kind: zworker_result
required_root_file: answer.md
{MANIFEST_END}

Then write exactly one final line:
{READY_MARKER}

Do not write anything after {READY_MARKER}.

If you cannot attach the ZIP, write:
{FAILED_MARKER} <short reason>
"""


def build_final_prompt(prompt_text: str, request_id: str) -> str:
    return prompt_text.rstrip() + build_automation_contract(request_id)


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WebRunnerError(
            "FAILED_PLAYWRIGHT_NOT_INSTALLED",
            "Python package 'playwright' is not installed. Install it locally and ensure Google Chrome is available.",
            recoverable=True,
        ) from exc
    return sync_playwright


def first_visible_locator(page, locators: list[Any], timeout_ms: int = 500) -> Any | None:
    for locator in locators:
        try:
            if locator.count() > 0:
                candidate = locator.first
                candidate.wait_for(state="visible", timeout=timeout_ms)
                return candidate
        except Exception:
            continue
    return None


def save_diagnostics(page, state: ZworkerWebRunState, stem: str) -> None:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)[:80] or "diagnostic"
    try:
        page.screenshot(path=str(state.session_dir / "screenshots" / f"{safe}.png"), full_page=True)
    except Exception:
        pass
    try:
        (state.session_dir / "dom_snapshots" / f"{safe}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def ensure_login(page, state: ZworkerWebRunState, timeout_ms: int) -> None:
    state.set_state("LOGIN_CHECKING")
    page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    login_markers = [re.compile(r"log in", re.I), re.compile(r"sign up", re.I), re.compile(r"войти", re.I)]
    composer_selectors = ['textarea', '[contenteditable="true"]', '[role="textbox"]', '#prompt-textarea']
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for selector in composer_selectors:
            try:
                loc = page.locator(selector)
                if loc.count() > 0 and loc.last.is_visible():
                    state.set_state("LOGIN_OK")
                    return
            except Exception:
                pass
        try:
            text = page.locator("body").inner_text(timeout=1000)
        except Exception:
            text = ""
        if any(p.search(text) for p in login_markers):
            save_diagnostics(page, state, "login_required")
            raise WebRunnerError(
                "FAILED_LOGIN_REQUIRED",
                "ChatGPT login is required. Log in manually in the dedicated Chrome profile, then rerun with --resume.",
                recoverable=True,
            )
        time.sleep(1)
    save_diagnostics(page, state, "login_check_timeout")
    raise WebRunnerError("FAILED_LOGIN_CHECK_TIMEOUT", "Could not confirm ChatGPT login/composer.", recoverable=True)


def open_new_chat(page, state: ZworkerWebRunState, timeout_ms: int) -> None:
    state.set_state("CHAT_OPENING")
    page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    candidates = [
        page.get_by_role("link", name=re.compile(r"new chat|новый чат", re.I)),
        page.get_by_role("button", name=re.compile(r"new chat|новый чат", re.I)),
        page.get_by_text(re.compile(r"new chat|новый чат", re.I)),
    ]
    button = first_visible_locator(page, candidates, timeout_ms=800)
    if button:
        try:
            button.click(timeout=3000)
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
    state.set_state("CHAT_CREATED", chat_url=page.url)


def capture_valid_chat_url(page, state: ZworkerWebRunState, *, source: str) -> bool:
    url = str(getattr(page, "url", "") or "").strip()
    if not is_valid_chat_url(url):
        return False
    state.update_chat_url(url, source=source)
    return True


def wait_for_valid_chat_url(page, state: ZworkerWebRunState, timeout_ms: int, *, source: str) -> bool:
    if capture_valid_chat_url(page, state, source=source):
        return True
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if capture_valid_chat_url(page, state, source=source):
            return True
    state.event("chat_url_still_pending", observed_url=str(getattr(page, "url", "") or ""), source=source)
    return False


def ensure_model(page, state: ZworkerWebRunState, preferred_models: list[str], timeout_ms: int, allow_unverified: bool) -> str:
    state.set_state("MODEL_CHECKING", preferred_models=preferred_models)
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        body_text = ""
    for model in preferred_models:
        if model and model in body_text:
            state.set_state("MODEL_SELECTED", observed_model=model)
            return model

    picker_candidates = [
        page.get_by_role("button", name=re.compile(r"model|модель|chatgpt|gpt", re.I)),
        page.locator("button").filter(has_text=re.compile(r"ChatGPT|GPT|model|модель", re.I)),
    ]
    picker = first_visible_locator(page, picker_candidates, timeout_ms=1000)
    if picker:
        try:
            picker.click(timeout=3000)
            time.sleep(1)
            for model in preferred_models:
                target = page.get_by_text(model, exact=False)
                if target.count() > 0:
                    target.first.click(timeout=5000)
                    time.sleep(1)
                    state.set_state("MODEL_SELECTED", observed_model=model)
                    return model
        except Exception:
            pass

    generic_picker_candidates = [
        page.get_by_role("button", name=re.compile(r"high|standard|fast|auto|low", re.I)),
        page.locator("button").filter(has_text=re.compile(r"high|standard|fast|auto|low", re.I)),
    ]
    generic_picker = first_visible_locator(page, generic_picker_candidates, timeout_ms=1000)
    if generic_picker:
        try:
            observed = generic_picker.inner_text(timeout=1000).strip() or "generic_picker_visible"
        except Exception:
            observed = "generic_picker_visible"
        state.set_state("MODEL_SELECTED", observed_model=observed)
        return observed

    save_diagnostics(page, state, "model_not_verified")
    if allow_unverified:
        state.set_state("MODEL_NOT_VERIFIED_ALLOWED", observed_model="", warning="model_check_soft_failure")
        return ""
    raise WebRunnerError("FAILED_MODEL_NOT_VERIFIED", f"Could not verify/select preferred model: {preferred_models}", recoverable=True)


def find_composer(page):
    selectors = ['#prompt-textarea', '[data-testid="composer-text-input"]', '[contenteditable="true"]', '[role="textbox"]', 'textarea']
    for selector in selectors:
        loc = page.locator(selector)
        try:
            if loc.count() > 0 and loc.last.is_visible():
                return loc.last
        except Exception:
            continue
    raise WebRunnerError("FAILED_COMPOSER_NOT_FOUND", "Could not find ChatGPT prompt composer.", recoverable=True)


def send_prompt(page, state: ZworkerWebRunState, final_prompt: str, force_resend: bool, timeout_ms: int) -> None:
    state.require_prompt_send_allowed(force=force_resend)
    state.set_state("PROMPT_SENDING", prompt_sha256=sha256_text(final_prompt))
    composer = find_composer(page)
    composer.click(timeout=timeout_ms)
    try:
        composer.fill(final_prompt, timeout=timeout_ms)
    except Exception:
        page.evaluate("async (text) => { await navigator.clipboard.writeText(text); }", final_prompt)
        page.keyboard.press("Control+V")

    candidates = [
        page.get_by_role("button", name=re.compile(r"send|отправ", re.I)),
        page.locator('button[data-testid*="send"]'),
        page.locator("button").filter(has_text=re.compile(r"send|отправ", re.I)),
    ]
    button = first_visible_locator(page, candidates, timeout_ms=1500)
    if button:
        button.click(timeout=timeout_ms)
    else:
        page.keyboard.press("Enter")
    state.metadata["prompt_sent_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state.set_state("PROMPT_SENT", chat_url=page.url, prompt_sha256=sha256_text(final_prompt))


def get_body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def get_last_assistant_message_text(page) -> str:
    assistant_selectors = [
        '[data-testid="conversation-turn-assistant"]',
        '[data-role="assistant"]',
        'div[role="presentation"]:has([data-role="assistant"])',
        'div[class*="assistant"]',
        'article[data-role="assistant"]',
    ]
    for selector in assistant_selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0:
                return loc.last.inner_text(timeout=3000)
        except Exception:
            continue
    return ""


def stop_button_visible(page) -> bool:
    try:
        loc = page.get_by_role("button", name=re.compile(r"stop|останов|cancel|отмена", re.I))
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def has_zip_attachment(page, request_id: str) -> bool:
    text = get_body_text(page)
    return f"{request_id}-zworker-result.zip" in text or (request_id in text and ".zip" in text)


def wait_answer_ready(page, state: ZworkerWebRunState, request_id: str, timeout_ms: int, stable_ms: int) -> None:
    state.set_state("ANSWER_STREAMING")
    deadline = time.monotonic() + timeout_ms / 1000
    last_text = ""
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        capture_valid_chat_url(page, state, source="answer_streaming")
        text = get_body_text(page)
        assistant_text = get_last_assistant_message_text(page)
        if FAILED_MARKER in assistant_text:
            idx = assistant_text.find(FAILED_MARKER)
            save_diagnostics(page, state, "zip_failed_marker")
            raise WebRunnerError("FAILED_CHATGPT_COULD_NOT_CREATE_ZIP", assistant_text[idx:idx + 500], recoverable=True)
        if text != last_text:
            last_text = text
            stable_since = time.monotonic()
        stable = (time.monotonic() - stable_since) * 1000 >= stable_ms
        ready_marker = READY_MARKER in assistant_text and request_id in assistant_text
        zip_seen = has_zip_attachment(page, request_id)
        if (ready_marker or zip_seen) and stable and not stop_button_visible(page):
            chat_url = page.url if is_valid_chat_url(page.url) else state.chat_url or page.url
            state.set_state("ANSWER_READY", ready_marker=ready_marker, zip_seen=zip_seen, chat_url=chat_url)
            return
        time.sleep(1)
    save_diagnostics(page, state, "answer_timeout")
    raise WebRunnerError("FAILED_ANSWER_TIMEOUT", "Timed out waiting for ChatGPT answer/ZIP readiness.", recoverable=True)


def find_zip_download_button(page, request_id: str):
    body = get_body_text(page)
    if request_id not in body:
        raise WebRunnerError("FAILED_NO_ZIP_LINK", "Could not find request id in page text.", recoverable=True)

    pattern = re.compile(r"download|скачать|загрузить", re.I)
    candidates = [
        page.get_by_role("button", name=pattern),
        page.get_by_role("link", name=pattern),
        page.locator("button").filter(has_text=pattern),
        page.locator("a").filter(has_text=pattern),
    ]
    visible = []
    for loc in candidates:
        try:
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible():
                    visible.append(item)
        except Exception:
            continue
    if visible:
        return visible[-1]

    zip_name = f"{request_id}.zip"
    fallback_candidates = [
        page.get_by_role("button", name=zip_name),
        page.get_by_role("link", name=zip_name),
        page.locator("button").filter(has_text=zip_name),
        page.locator("a").filter(has_text=zip_name),
        page.get_by_role("button", name=request_id),
        page.get_by_role("link", name=request_id),
        page.locator("button").filter(has_text=request_id),
        page.locator("a").filter(has_text=request_id),
    ]
    visible_fallback = []
    for loc in fallback_candidates:
        try:
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible():
                    visible_fallback.append(item)
        except Exception:
            continue
    if not visible_fallback:
        raise WebRunnerError("FAILED_NO_ZIP_LINK", "ZIP marker found, but no visible Download button/link was found.", recoverable=True)
    return visible_fallback[-1]


def wait_for_zip_in_dir(downloads_dir: Path, request_id: str, timeout_ms: int) -> Path | None:
    deadline = time.monotonic() + timeout_ms / 1000
    sizes: dict[Path, tuple[int, float]] = {}
    while time.monotonic() < deadline:
        candidates = sorted(downloads_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        for candidate in candidates:
            try:
                size = candidate.stat().st_size
            except OSError:
                continue
            old_size, first_seen = sizes.get(candidate, (-1, time.monotonic()))
            if old_size == size and size > 0 and (time.monotonic() - first_seen) >= 2:
                return candidate
            sizes[candidate] = (size, first_seen)
        time.sleep(1)
    return None


def download_zip(page, state: ZworkerWebRunState, request_id: str, timeout_ms: int) -> Path:
    state.set_state("ZIP_LINK_WAITING")
    button = find_zip_download_button(page, request_id)
    state.set_state("ZIP_LINK_FOUND")
    state.output_dir.mkdir(parents=True, exist_ok=True)
    state.downloads_dir.mkdir(parents=True, exist_ok=True)
    target_zip = state.output_dir / f"{request_id}.zip"
    state.set_state("ZIP_DOWNLOAD_STARTING")
    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            button.click(timeout=timeout_ms)
        download = download_info.value
        download.save_as(str(target_zip))
        state.set_state("ZIP_DOWNLOADED", zip_path=str(target_zip), suggested_filename=download.suggested_filename, method="playwright_download_event")
        return target_zip
    except Exception as exc:
        state.event("download_primary_failed", error=str(exc))
    try:
        button.click(timeout=5000)
    except Exception:
        pass
    candidate = wait_for_zip_in_dir(state.downloads_dir, request_id, timeout_ms)
    if candidate:
        shutil.copy2(candidate, target_zip)
        state.set_state("ZIP_DOWNLOADED", zip_path=str(target_zip), method="filesystem_watcher")
        return target_zip
    save_diagnostics(page, state, "download_timeout")
    raise WebRunnerError("FAILED_DOWNLOAD_TIMEOUT", "ZIP download was not detected.", recoverable=True)


def validate_downloaded_zip(state: ZworkerWebRunState, zip_path: Path, manifest_path: Path | None) -> None:
    state.set_state("ZIP_VALIDATING", zip_path=str(zip_path))
    report = validate_zip(zip_path, manifest_path=manifest_path if manifest_path and manifest_path.exists() else None)
    report_path = state.output_dir / "zip_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report.security_reject:
        raise WebRunnerError("FAILED_BAD_ZIP", report.error or "ZIP pre-validation failed.", recoverable=True)
    if report.warnings:
        state.event("zip_validation_warnings", warnings=report.warnings)
    state.set_state("ZIP_VALID", zip_path=str(zip_path), zip_sha256=report.sha256, zip_report=str(report_path), status=report.status)


def run_handoff(repo_root: Path, state: ZworkerWebRunState) -> None:
    state.set_state("HANDOFF_UNPACKING")
    unpack_cmd = [
        sys.executable, str(repo_root / "scripts" / "codex_token_monitor_opencode_jobs.py"),
        "--zworker-result-unpack", state.zip_path,
        "--zworker-unpack-request-id", state.request_id,
    ]
    unpack = subprocess.run(unpack_cmd, cwd=str(repo_root), capture_output=True, text=True)
    state.event("handoff_unpack_finished", returncode=unpack.returncode, stdout=unpack.stdout[-4000:], stderr=unpack.stderr[-4000:])
    if unpack.returncode != 0:
        raise WebRunnerError("FAILED_UNPACK", f"zworker_result_unpack failed with code {unpack.returncode}", recoverable=True)
    state.set_state("HANDOFF_UNPACKED")
    state.set_state("HANDOFF_PROCESSING")
    process_cmd = [sys.executable, str(repo_root / "scripts" / "codex_token_monitor_opencode_jobs.py"), "--zworker-process-result", state.request_id]
    process = subprocess.run(process_cmd, cwd=str(repo_root), capture_output=True, text=True)
    state.event("handoff_process_finished", returncode=process.returncode, stdout=process.stdout[-4000:], stderr=process.stderr[-4000:])
    if process.returncode != 0:
        raise WebRunnerError("FAILED_PROCESS", f"zworker_process_result failed with code {process.returncode}", recoverable=True)
    state.set_state("HANDOFF_DONE")


def is_valid_chat_url(url: str) -> bool:
    if not url:
        return False
    return bool(re.search(r"/c/[a-zA-Z0-9]+", url))


def run_browser_flow(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    runtime_root = Path(args.runtime_root).resolve() if args.runtime_root else default_runtime_root(repo_root)
    state = ZworkerWebRunState.load(args.request_id, runtime_root=runtime_root)
    state.attempt_no = args.attempt_no
    state.revision_no = args.revision_no
    state.persist()

    use_attach_mode = bool(args.cdp_url and args.cdp_url.strip())
    is_zworker_auto_mode = getattr(args, "zworker_auto_mode", False)

    if is_zworker_auto_mode and not use_attach_mode:
        state.fail(
            "FAILED_ATTACH_REQUIRED",
            "zworker-auto web-runner requires --cdp-url for attach-mode. Cannot launch new browser in zworker-auto mode.",
            recoverable=False,
        )
        raise WebRunnerError(
            "FAILED_ATTACH_REQUIRED",
            "zworker-auto web-runner requires --cdp-url for attach-mode. Cannot launch new browser in zworker-auto mode.",
            recoverable=False,
        )

    sync_playwright = require_playwright()

    prompt_text = ""
    manifest_path = None
    if not (args.login_check or args.model_check):
        prompt_text, _, manifest_path = read_request_prompt(repo_root, args.request_id)
    final_prompt = build_final_prompt(prompt_text, args.request_id) if prompt_text else ""
    if final_prompt:
        (state.session_dir / "prompt.final.md").write_text(final_prompt, encoding="utf-8")

    profile_dir = Path(args.profile_dir) if args.profile_dir else runtime_root / "profiles" / "chatgpt-main"
    profile_dir.mkdir(parents=True, exist_ok=True)
    state.downloads_dir.mkdir(parents=True, exist_ok=True)

    state.set_state("BROWSER_STARTING")

    with sync_playwright() as p:
        if use_attach_mode:
            browser = p.chromium.connect_over_cdp(args.cdp_url.strip())
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
            else:
                context = browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            state.set_state(
                "BROWSER_READY",
                browser_mode="attach",
                cdp_url=args.cdp_url.strip(),
                browser_channel="chrome",
                headless=False,
            )
        else:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel="chrome",
                headless=False,
                accept_downloads=True,
                downloads_path=str(state.downloads_dir),
            )
            page = context.pages[0] if context.pages else context.new_page()
            state.set_state("BROWSER_READY", profile_dir=str(profile_dir), browser_channel="chrome", headless=False)
        try:
            ensure_login(page, state, args.login_timeout_ms)
            if args.login_check:
                state.set_state("LOGIN_CHECK_DONE")
                context.close()
                return 0
            open_new_chat(page, state, args.chat_timeout_ms)
            preferred = [m.strip() for m in args.preferred_model if m.strip()]
            ensure_model(page, state, preferred, args.model_timeout_ms, args.allow_unverified_model)
            if args.model_check:
                state.set_state("MODEL_CHECK_DONE")
                context.close()
                return 0
            if args.resume and state.can_skip_prompt_send():
                resume_point = state.get_resume_point()
                state.event("resume_flow_start", resume_point=resume_point, chat_url=state.chat_url)
                if resume_point == "answer_ready":
                    state.event("resume_skip_to_answer_ready", chat_url=state.chat_url)
                    page.goto(state.chat_url, wait_until="domcontentloaded", timeout=args.chat_timeout_ms)
                elif resume_point == "download":
                    state.event("resume_skip_to_download", chat_url=state.chat_url)
                    page.goto(state.chat_url, wait_until="domcontentloaded", timeout=args.chat_timeout_ms)
                else:
                    page.goto(state.chat_url, wait_until="domcontentloaded", timeout=args.chat_timeout_ms)
            else:
                if not final_prompt:
                    raise WebRunnerError("FAILED_REQUEST_NOT_FOUND", "No prompt loaded for request.")
                send_prompt(page, state, final_prompt, args.force_resend, args.prompt_timeout_ms)
                wait_for_valid_chat_url(
                    page,
                    state,
                    min(args.answer_timeout_ms, max(args.chat_timeout_ms, 60_000)),
                    source="post_prompt",
                )
            wait_answer_ready(page, state, args.request_id, args.answer_timeout_ms, args.stable_answer_ms)
            zip_path = download_zip(page, state, args.request_id, args.download_timeout_ms)
            validate_downloaded_zip(state, zip_path, manifest_path)
            context.close()
        except WebRunnerError:
            context.close()
            raise
        except Exception as exc:
            save_diagnostics(page, state, "unexpected_error")
            context.close()
            raise WebRunnerError("FAILED_UNKNOWN", str(exc), recoverable=True) from exc

    if args.handoff:
        run_handoff(repo_root, state)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ChatGPT Web zworker helper via Playwright/Chrome/headful.")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--repo-root", default=str(repo_root_from_script()))
    parser.add_argument("--runtime-root", default="")
    parser.add_argument("--profile-dir", default="")
    parser.add_argument("--cdp-url", default="", help="CDP WebSocket URL for attach-mode (e.g., ws://localhost:9222/devtools/browser/xxx). If provided, use attach-mode instead of launching a new browser.")
    parser.add_argument("--preferred-model", action="append", default=["Pro Extended", "Pro Standard"])
    parser.add_argument("--allow-unverified-model", action="store_true")
    parser.add_argument("--force-resend", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--handoff", action="store_true")
    parser.add_argument("--login-check", action="store_true")
    parser.add_argument("--model-check", action="store_true")
    parser.add_argument("--zworker-auto-mode", action="store_true", help="Run in zworker-auto mode (requires --cdp-url)")
    parser.add_argument("--attempt-no", type=int, default=1)
    parser.add_argument("--revision-no", type=int, default=1)
    parser.add_argument("--login-timeout-ms", type=int, default=30000)
    parser.add_argument("--chat-timeout-ms", type=int, default=30000)
    parser.add_argument("--model-timeout-ms", type=int, default=30000)
    parser.add_argument("--prompt-timeout-ms", type=int, default=30000)
    parser.add_argument("--answer-timeout-ms", type=int, default=60 * 60 * 1000)
    parser.add_argument("--download-timeout-ms", type=int, default=5 * 60 * 1000)
    parser.add_argument("--stable-answer-ms", type=int, default=15000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    runtime_root = Path(args.runtime_root).resolve() if args.runtime_root else default_runtime_root(repo_root)
    state = ZworkerWebRunState.load(args.request_id, runtime_root=runtime_root)
    try:
        return run_browser_flow(args)
    except WebRunnerError as exc:
        state.fail(exc.code, str(exc), recoverable=exc.recoverable)
        print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        state.fail("FAILED_INTERRUPTED", "Interrupted by user.", recoverable=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
