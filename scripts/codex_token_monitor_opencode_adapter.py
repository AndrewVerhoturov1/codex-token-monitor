import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

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


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_text(path, text)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _resolve_opencode_command(opencode_command: str | None = None) -> tuple[str | None, str]:
    configured = (opencode_command or "").strip()
    if configured:
        return configured, "config"

    candidates = ["opencode.cmd", "opencode.exe", "opencode"] if sys.platform == "win32" else ["opencode"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved, f"which:{candidate}"
    return None, "not_found"


def _build_opencode_command(
    *,
    opencode_command: str,
    provider_id: str,
    model_id: str,
    directory: str | None,
    opencode_input_path: Path,
    job_title: str | None,
    attach_url: str | None,
) -> list[str]:
    command = [
        opencode_command,
        "run",
        "--model",
        f"{provider_id}/{model_id}",
        "--file",
        str(opencode_input_path),
    ]
    if job_title:
        command.extend(["--title", job_title])
    if attach_url:
        command.extend(["--attach", attach_url])
    if directory:
        command.extend(["--dir", directory])
    command.append("Read the attached task file and follow its instructions exactly.")
    return command


def _format_manual_powershell_command(*, opencode_input_path: Path, command_tokens: list[str]) -> str:
    quoted_tokens = " ".join(_ps_quote(token) for token in command_tokens)
    return f"& {quoted_tokens}"


def _read_json_safe(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_export_session_mode(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in VALID_EXPORT_SESSION_MODES:
        return normalized
    return EXPORT_SESSION_ON_FAILURE


def _read_done_payload(path: Path) -> dict[str, object]:
    return _read_json_safe(path)


def _update_launch_artifact(job_dir: Path, **updates: object) -> None:
    launch_path = job_dir / "opencode_launch.json"
    payload = _read_json_safe(launch_path)
    payload.update(updates)
    _atomic_write_json(launch_path, payload)


def _normalize_match_path(value: str | None) -> str:
    if not value:
        return ""
    return str(Path(value).resolve(strict=False)).casefold()


def _find_session_id_by_title(sessions_json: str, *, title: str, directory: str | None) -> str | None:
    try:
        payload = json.loads(sessions_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None

    target_directory = _normalize_match_path(directory)
    for item in payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("title", "")).strip() != title:
            continue
        session_id = str(item.get("id", "")).strip()
        if not session_id:
            continue
        if target_directory:
            item_directory = _normalize_match_path(str(item.get("directory", "")).strip())
            if item_directory != target_directory:
                continue
        return session_id
    return None


def _lookup_session_id(
    *,
    job_dir: Path,
    opencode_command: str,
    job_title: str,
    directory: str | None,
    attempts: int,
    delay_seconds: float,
) -> str | None:
    _update_launch_artifact(
        job_dir,
        session_lookup_attempted=True,
        session_lookup_status="running",
        session_lookup_error="",
        session_id_found=False,
        session_id="",
    )

    session_id = None
    last_lookup_error = ""
    for _ in range(max(attempts, 1)):
        try:
            proc = subprocess.run(
                [opencode_command, "session", "list", "--format", "json", "-n", "20"],
                capture_output=True,
                text=True,
                cwd=directory or None,
            )
        except OSError as exc:
            _update_launch_artifact(
                job_dir,
                session_lookup_status="lookup_failed",
                session_lookup_error=f"{type(exc).__name__}: {exc}",
                session_id_found=False,
                session_id="",
            )
            return None
        if proc.returncode == 0:
            session_id = _find_session_id_by_title(
                proc.stdout or "",
                title=job_title,
                directory=directory,
            )
            if session_id:
                _update_launch_artifact(
                    job_dir,
                    session_lookup_status="session_found",
                    session_lookup_error="",
                    session_id_found=True,
                    session_id=session_id,
                )
                return session_id
            last_lookup_error = ""
        else:
            last_lookup_error = (proc.stderr or proc.stdout or f"session list exit {proc.returncode}").strip()
        time.sleep(delay_seconds)

    _update_launch_artifact(
        job_dir,
        session_lookup_status="session_not_found",
        session_lookup_error=last_lookup_error,
        session_id_found=False,
        session_id="",
    )
    return None


def _build_session_tui_command(
    *,
    opencode_command: str,
    session_id: str,
    directory: str | None,
    attach_url: str | None,
) -> list[str]:
    if attach_url:
        command = [
            opencode_command,
            "attach",
            attach_url,
            "--session",
            session_id,
        ]
        if directory:
            command.extend(["--dir", directory])
        return command

    command = [
        opencode_command,
    ]
    if directory:
        command.append(directory)
    command.extend(["--session", session_id])
    return command


def _build_terminal_open_command(*, command_tokens: list[str], window_title: str) -> tuple[list[str], str]:
    inner_command = _format_manual_powershell_command(
        opencode_input_path=Path("."),
        command_tokens=command_tokens,
    )


def _build_export_command(*, opencode_command: str, session_id: str) -> list[str]:
    return [opencode_command, "export", session_id]
    wt_path = shutil.which("wt.exe")
    if wt_path:
        return (
            [
                wt_path,
                "new-tab",
                "--title",
                window_title,
                "powershell.exe",
                "-NoExit",
                "-Command",
                inner_command,
            ],
            "wt.exe",
        )
    return (
        [
            "powershell.exe",
            "-NoExit",
            "-Command",
            inner_command,
        ],
        "powershell.exe",
    )


def _write_launch_artifacts(
    *,
    job_dir: Path,
    opencode_input: str,
    command_tokens: list[str],
    launch_payload: dict[str, object],
) -> None:
    opencode_input_path = job_dir / "opencode_input.md"
    manual_command_path = job_dir / "opencode_manual_command.txt"
    launch_path = job_dir / "opencode_launch.json"
    manual_command = _format_manual_powershell_command(
        opencode_input_path=opencode_input_path,
        command_tokens=command_tokens,
    )

    _atomic_write_text(opencode_input_path, opencode_input)
    _atomic_write_text(manual_command_path, manual_command + "\n")
    payload = dict(launch_payload)
    payload.update({
        "command_tokens": command_tokens,
        "command_display": subprocess.list2cmdline(command_tokens),
        "manual_powershell_command": manual_command,
        "opencode_input_path": str(opencode_input_path),
        "manual_command_path": str(manual_command_path),
    })
    _atomic_write_json(launch_path, payload)


def _write_log_preamble(path: Path, *, mode: str, cwd: str | None, command_tokens: list[str]) -> None:
    preamble = (
        f"[adapter] mode={mode}\n"
        f"[adapter] cwd={cwd or ''}\n"
        f"[adapter] command={subprocess.list2cmdline(command_tokens)}\n\n"
    )
    _atomic_write_text(path, preamble)


def _append_text(path: Path, text: str) -> None:
    if not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _collect_plain_text(value: Any, parts: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            parts.append(text)
        return
    if isinstance(value, list):
        for item in value:
            _collect_plain_text(item, parts)
        return
    if not isinstance(value, dict):
        return

    if isinstance(value.get("text"), str):
        text = value["text"].strip()
        if text:
            parts.append(text)

    for key in ("content", "parts", "input", "output", "reasoning", "reasoning_content", "message"):
        nested = value.get(key)
        if nested is not None and nested is not value:
            _collect_plain_text(nested, parts)


def _render_session_transcript_markdown(*, session_id: str, export_payload: Any) -> str:
    lines = [
        "# OpenCode Session Transcript",
        "",
        f"- session_id: `{session_id}`",
        "",
    ]

    if isinstance(export_payload, dict) and isinstance(export_payload.get("messages"), list):
        entries = export_payload["messages"]
    elif isinstance(export_payload, list):
        entries = export_payload
    else:
        entries = [export_payload]

    for index, entry in enumerate(entries, 1):
        role = "entry"
        if isinstance(entry, dict):
            role = str(
                entry.get("role")
                or entry.get("type")
                or entry.get("kind")
                or entry.get("name")
                or role
            )
        parts: list[str] = []
        _collect_plain_text(entry, parts)
        lines.append(f"## {index}. {role}")
        lines.append("")
        if parts:
            lines.append("\n\n".join(parts))
        else:
            lines.append("_No plain text extracted from this entry._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_session_export_files(
    *,
    job_dir: Path,
    session_id: str,
    export_stdout: str,
) -> tuple[Path, Path]:
    export_json_path = job_dir / "opencode_session_export.json"
    transcript_path = job_dir / "opencode_session_transcript.md"
    try:
        export_payload = json.loads(export_stdout)
    except json.JSONDecodeError as exc:
        export_payload = {
            "session_id": session_id,
            "raw_export": export_stdout,
            "parse_error": f"{type(exc).__name__}: {exc}",
        }

    _atomic_write_json(export_json_path, export_payload)
    transcript = _render_session_transcript_markdown(
        session_id=session_id,
        export_payload=export_payload,
    )
    _atomic_write_text(transcript_path, transcript)
    return export_json_path, transcript_path


def _should_export_session(
    export_mode: str,
    *,
    status: str,
    timed_out: bool,
    debug_visible_terminal: bool,
) -> bool:
    normalized = _normalize_export_session_mode(export_mode)
    if normalized == EXPORT_SESSION_OFF:
        return False
    if normalized == EXPORT_SESSION_ALWAYS:
        return True
    if normalized == EXPORT_SESSION_ON_DEBUG:
        return debug_visible_terminal
    return timed_out or status in {"failed", "blocked"}


def _maybe_export_session(
    *,
    job_dir: Path,
    opencode_command: str,
    export_mode: str,
    debug_visible_terminal: bool,
    job_title: str | None,
    directory: str | None,
    status: str,
    timed_out: bool,
) -> None:
    normalized_mode = _normalize_export_session_mode(export_mode)
    requested = _should_export_session(
        normalized_mode,
        status=status,
        timed_out=timed_out,
        debug_visible_terminal=debug_visible_terminal,
    )
    _update_launch_artifact(
        job_dir,
        export_session=normalized_mode,
        export_session_requested=requested,
        export_session_attempted=False,
        export_session_status="not_requested" if not requested else "pending",
        export_session_reason="",
        session_export_path="",
        session_transcript_path="",
    )
    if not requested:
        return

    launch_data = _read_json_safe(job_dir / "opencode_launch.json")
    session_id = str(launch_data.get("session_id", "")).strip()
    if not session_id and job_title:
        session_id = _lookup_session_id(
            job_dir=job_dir,
            opencode_command=opencode_command,
            job_title=job_title,
            directory=directory,
            attempts=4,
            delay_seconds=0.25,
        ) or ""
    if not session_id:
        _update_launch_artifact(
            job_dir,
            export_session_attempted=False,
            export_session_status="session_unavailable",
            export_session_reason="OpenCode session id was not found for export.",
        )
        return

    try:
        proc = subprocess.run(
            _build_export_command(opencode_command=opencode_command, session_id=session_id),
            capture_output=True,
            text=True,
            cwd=directory or None,
        )
    except OSError as exc:
        _update_launch_artifact(
            job_dir,
            export_session_attempted=True,
            export_session_status="export_failed",
            export_session_reason=f"{type(exc).__name__}: {exc}",
        )
        return

    if proc.returncode != 0:
        _update_launch_artifact(
            job_dir,
            export_session_attempted=True,
            export_session_status="export_failed",
            export_session_reason=(proc.stderr or proc.stdout or f"opencode export exit {proc.returncode}").strip(),
        )
        return

    export_json_path, transcript_path = _write_session_export_files(
        job_dir=job_dir,
        session_id=session_id,
        export_stdout=proc.stdout or "",
    )
    _update_launch_artifact(
        job_dir,
        export_session_attempted=True,
        export_session_status="exported",
        export_session_reason="",
        session_export_path=str(export_json_path),
        session_transcript_path=str(transcript_path),
    )


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _stream_pipe_to_console_and_log(pipe: TextIO, console: TextIO, log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        for line in iter(pipe.readline, ""):
            handle.write(line)
            handle.flush()
            console.write(line)
            console.flush()
    pipe.close()


def _hold_debug_terminal_open(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input("Press Enter to close debug window...")
    except EOFError:
        pass


def _lookup_and_open_session_tui(
    *,
    job_dir: Path,
    opencode_command: str,
    job_title: str,
    directory: str | None,
    attach_url: str | None,
) -> None:
    _update_launch_artifact(
        job_dir,
        tui_open_attempted=False,
        tui_open_status="pending",
        tui_open_command="",
        tui_open_error="",
        attach_url=attach_url or "",
    )

    session_id = _lookup_session_id(
        job_dir=job_dir,
        opencode_command=opencode_command,
        job_title=job_title,
        directory=directory,
        attempts=16,
        delay_seconds=0.5,
    )
    if not session_id:
        _update_launch_artifact(
            job_dir,
            tui_open_status="launch_not_attempted",
        )
        return

    session_command = _build_session_tui_command(
        opencode_command=opencode_command,
        session_id=session_id,
        directory=directory,
        attach_url=attach_url,
    )
    terminal_command, launcher = _build_terminal_open_command(
        command_tokens=session_command,
        window_title=job_title,
    )

    try:
        popen_kwargs: dict[str, object] = {"cwd": directory or None}
        if sys.platform == "win32" and launcher != "wt.exe":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(terminal_command, **popen_kwargs)
        _update_launch_artifact(
            job_dir,
            session_lookup_status="session_found",
            session_lookup_error="",
            session_id_found=True,
            session_id=session_id,
            tui_open_attempted=True,
            tui_open_status="launched_not_confirmed",
            tui_open_command=subprocess.list2cmdline(terminal_command),
            tui_open_error="",
        )
    except OSError as exc:
        _update_launch_artifact(
            job_dir,
            session_lookup_status="session_found",
            session_lookup_error="",
            session_id_found=True,
            session_id=session_id,
            tui_open_attempted=True,
            tui_open_status="launch_failed",
            tui_open_command=subprocess.list2cmdline(terminal_command),
            tui_open_error=f"{type(exc).__name__}: {exc}",
        )


def _run_opencode(
    *,
    command_tokens: list[str],
    cwd: str | None,
    stdout_path: Path,
    stderr_path: Path,
    debug_visible_terminal: bool,
    job_dir: Path,
    opencode_command: str,
    debug_open_session_tui: bool,
    job_title: str | None,
    attach_url: str | None,
) -> tuple[int, str, str]:
    if not debug_visible_terminal:
        proc = subprocess.Popen(
            command_tokens,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd or None,
        )
        session_thread = None
        if debug_open_session_tui and job_title:
            session_thread = threading.Thread(
                target=_lookup_and_open_session_tui,
                kwargs={
                    "job_dir": job_dir,
                    "opencode_command": opencode_command,
                    "job_title": job_title,
                    "directory": cwd,
                    "attach_url": attach_url,
                },
                daemon=True,
            )
            session_thread.start()
        stdout_text, stderr_text = proc.communicate()
        if session_thread is not None:
            session_thread.join(timeout=1)
        _append_text(stdout_path, stdout_text or "")
        _append_text(stderr_path, stderr_text or "")
        return proc.returncode or 0, stdout_text or "", stderr_text or ""

    process = subprocess.Popen(
        command_tokens,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd or None,
        bufsize=1,
    )
    session_thread = None
    if debug_open_session_tui and job_title:
        session_thread = threading.Thread(
            target=_lookup_and_open_session_tui,
            kwargs={
                "job_dir": job_dir,
                "opencode_command": opencode_command,
                "job_title": job_title,
                "directory": cwd,
                "attach_url": attach_url,
            },
            daemon=True,
        )
        session_thread.start()

    threads: list[threading.Thread] = []
    if process.stdout is not None:
        threads.append(
            threading.Thread(
                target=_stream_pipe_to_console_and_log,
                args=(process.stdout, sys.stdout, stdout_path),
                daemon=True,
            )
        )
    if process.stderr is not None:
        threads.append(
            threading.Thread(
                target=_stream_pipe_to_console_and_log,
                args=(process.stderr, sys.stderr, stderr_path),
                daemon=True,
            )
        )
    for thread in threads:
        thread.start()

    return_code = process.wait()
    for thread in threads:
        thread.join(timeout=5)
    if session_thread is not None:
        session_thread.join(timeout=1)

    return return_code, _read_text_safe(stdout_path), _read_text_safe(stderr_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCode CLI adapter")
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--directory", default=None)
    parser.add_argument("--stdout-log", default=None)
    parser.add_argument("--stderr-log", default=None)
    parser.add_argument("--opencode-command", default=None)
    parser.add_argument("--debug-visible-terminal", action="store_true")
    parser.add_argument("--debug-open-session-tui", action="store_true")
    parser.add_argument("--opencode-attach-url", default=None)
    parser.add_argument("--export-session", default=EXPORT_SESSION_ON_FAILURE)
    args = parser.parse_args()

    task_file = Path(args.task_file)
    job_dir = Path(args.job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    result_md = job_dir / "result.md"
    done_json = job_dir / "done.json"
    result_md_display = result_md.as_posix()
    done_json_display = done_json.as_posix()

    original_task = task_file.read_text(encoding="utf-8")

    protocol = (
        f"\n\n=== PROTOCOL INSTRUCTIONS ===\n"
        f"After completing the task, write the final result atomically:\n"
        f"  1. Write to {result_md_display}.tmp, then rename to {result_md_display}\n"
        f"  2. Write completion metadata to {done_json_display}.tmp, then rename to {done_json_display}\n"
        f"{done_json_display} must be written strictly after {result_md_display}.\n"
        f'{done_json_display} format: {{"status": "completed|partial|blocked|failed", '
        f'"reason": "...", "summary": "..."}}\n'
    )
    augmented_task = original_task + protocol

    stdout_log = Path(args.stdout_log) if args.stdout_log else (job_dir / "stdout.log")
    stderr_log = Path(args.stderr_log) if args.stderr_log else (job_dir / "stderr.log")
    opencode_input_path = job_dir / "opencode_input.md"
    resolved_command, found_by = _resolve_opencode_command(args.opencode_command)
    opencode_command = resolved_command or "opencode"
    export_mode = _normalize_export_session_mode(args.export_session)
    needs_session_tracking = args.debug_open_session_tui or export_mode != EXPORT_SESSION_OFF
    job_title = f"codex-job-{job_dir.name}" if needs_session_tracking else ""
    command_tokens = _build_opencode_command(
        opencode_command=opencode_command,
        provider_id=args.provider_id,
        model_id=args.model_id,
        directory=args.directory,
        opencode_input_path=opencode_input_path,
        job_title=job_title or None,
        attach_url=args.opencode_attach_url,
    )

    _write_launch_artifacts(
        job_dir=job_dir,
        opencode_input=augmented_task,
        command_tokens=command_tokens,
        launch_payload={
            "provider_id": args.provider_id,
            "model_id": args.model_id,
            "working_directory": args.directory or "",
            "cwd": str(Path.cwd()),
            "debug_visible_terminal": args.debug_visible_terminal,
            "debug_open_session_tui": args.debug_open_session_tui,
            "opencode_resolved_command": resolved_command or "",
            "opencode_found_by": found_by,
            "path_env": os.environ.get("PATH", ""),
            "opencode_run_title": job_title,
            "session_lookup_attempted": False,
            "session_lookup_status": "not_requested" if not args.debug_open_session_tui else "pending",
            "session_lookup_error": "",
            "session_id_found": False,
            "session_id": "",
            "tui_open_attempted": False,
            "tui_open_status": "not_requested" if not args.debug_open_session_tui else "pending",
            "tui_open_command": "",
            "tui_open_error": "",
            "attach_url": args.opencode_attach_url or "",
            "export_session": export_mode,
            "export_session_requested": False,
            "export_session_attempted": False,
            "export_session_status": "not_requested" if export_mode == EXPORT_SESSION_OFF else "pending",
            "export_session_reason": "",
            "session_export_path": "",
            "session_transcript_path": "",
        },
    )
    mode = "visible_terminal" if args.debug_visible_terminal else "silent"
    _write_log_preamble(stdout_log, mode=mode, cwd=args.directory, command_tokens=command_tokens)
    _write_log_preamble(stderr_log, mode=mode, cwd=args.directory, command_tokens=command_tokens)

    if resolved_command is None:
        message = "Error: opencode CLI not found\n"
        _append_text(stderr_log, message)
        _atomic_write_text(result_md, message)
        _atomic_write_json(done_json, {"status": "failed", "reason": "opencode_not_found", "summary": ""})
        if args.debug_visible_terminal:
            _hold_debug_terminal_open("Error: opencode CLI not found")
        sys.exit(1)

    try:
        exit_code, stdout_text, stderr_text = _run_opencode(
            command_tokens=command_tokens,
            cwd=args.directory,
            stdout_path=stdout_log,
            stderr_path=stderr_log,
            debug_visible_terminal=args.debug_visible_terminal,
            job_dir=job_dir,
            opencode_command=opencode_command,
            debug_open_session_tui=args.debug_open_session_tui,
            job_title=job_title or None,
            attach_url=args.opencode_attach_url,
        )
    except FileNotFoundError:
        _atomic_write_text(result_md, "Error: opencode CLI not found\n")
        _atomic_write_json(done_json, {"status": "failed", "reason": "opencode_not_found", "summary": ""})
        if args.debug_visible_terminal:
            _hold_debug_terminal_open("Error: opencode CLI not found")
        sys.exit(1)

    if not done_json.exists():
        output = stdout_text or stderr_text or ""
        lines = output.splitlines()
        tail = lines[-80:] if lines else []
        summary = "\n".join(tail)[:4000] if tail else ""
        if exit_code == 0:
            status, reason = "completed", "completed"
        else:
            status, reason = "failed", f"opencode_exit_{exit_code}"
        if not result_md.exists():
            _atomic_write_text(result_md, output or f"OpenCode exit code: {exit_code}\n")
        _atomic_write_json(done_json, {"status": status, "reason": reason, "summary": summary})

    done_payload = _read_done_payload(done_json)
    final_status = str(done_payload.get("status", "failed")).strip() or "failed"
    final_timed_out = bool(done_payload.get("timed_out")) or (
        final_status == "blocked" and str(done_payload.get("reason", "")).strip() == "timed_out"
    )
    _maybe_export_session(
        job_dir=job_dir,
        opencode_command=opencode_command,
        export_mode=export_mode,
        debug_visible_terminal=args.debug_visible_terminal,
        job_title=job_title or None,
        directory=args.directory,
        status=final_status,
        timed_out=final_timed_out,
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
