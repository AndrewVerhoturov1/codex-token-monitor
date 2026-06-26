import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codex_token_monitor_opencode_jobs as jobs

SERVER_NAME = "opencode_jobs"
TOOL_NAME = "opencode_job_run_and_wait"
MCP_SUMMARY_MAX_CHARS = 1200
STARTER_ENV = "OPENCODE_JOBS_MCP_STARTED_VIA_STARTER"
STARTER_PATH = SCRIPT_DIR / "start_opencode_jobs_mcp.py"


def _ensure_started_via_starter() -> None:
    if os.environ.get(STARTER_ENV) == "1":
        return
    if not STARTER_PATH.exists():
        return
    env = os.environ.copy()
    env[STARTER_ENV] = "1"
    os.execve(sys.executable, [sys.executable, str(STARTER_PATH)], env)


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    return text or None


def _normalize_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _resolve_repo_path(value: Any) -> Path | None:
    text = _normalize_text(value)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = jobs.REPO_ROOT / path
    return path.resolve(strict=False)


def _compact_summary(text: str) -> str:
    summary = text.strip()
    if len(summary) > MCP_SUMMARY_MAX_CHARS:
        return summary[:MCP_SUMMARY_MAX_CHARS] + "..."
    return summary


def _empty_response(reason: str, summary: str) -> dict[str, Any]:
    return {
        "job_id": "",
        "status": jobs.STATUS_FAILED,
        "reason": reason,
        "summary": _compact_summary(summary),
        "duration_ms": 0,
        "timed_out": False,
        "result_path": "",
        "done_path": "",
        "stdout_path": "",
        "stderr_path": "",
        "launch_path": "",
        "debug_visible_terminal_requested": False,
        "debug_visible_terminal_status": "not_requested",
        "debug_visible_terminal_reason": "",
        "debug_visible_terminal_pid": None,
        "debug_open_session_tui_requested": False,
        "debug_open_session_tui_status": "not_requested",
        "debug_open_session_tui_reason": "",
        "debug_session_id": "",
        "debug_tui_command": "",
        "debug_attach_url": "",
        "export_session_mode": jobs.EXPORT_SESSION_ON_FAILURE,
        "export_session_status": "not_requested",
        "export_session_reason": "",
        "session_export_path": "",
        "session_transcript_path": "",
    }


def job_result_to_mcp_response(result: jobs.JobResult) -> dict[str, Any]:
    done_path = ""
    if result.result_path:
        done_path = str(Path(result.result_path).resolve(strict=False).with_name("done.json"))
    return {
        "job_id": result.job_id,
        "status": result.status,
        "reason": result.reason,
        "summary": _compact_summary(result.summary),
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
        "result_path": str(Path(result.result_path).resolve(strict=False)) if result.result_path else "",
        "done_path": done_path,
        "stdout_path": str(Path(result.stdout_path).resolve(strict=False)) if result.stdout_path else "",
        "stderr_path": str(Path(result.stderr_path).resolve(strict=False)) if result.stderr_path else "",
        "launch_path": str(Path(result.launch_path).resolve(strict=False)) if result.launch_path else "",
        "debug_visible_terminal_requested": result.debug_visible_terminal_requested,
        "debug_visible_terminal_status": result.debug_visible_terminal_status,
        "debug_visible_terminal_reason": result.debug_visible_terminal_reason,
        "debug_visible_terminal_pid": result.debug_visible_terminal_pid,
        "debug_open_session_tui_requested": result.debug_open_session_tui_requested,
        "debug_open_session_tui_status": result.debug_open_session_tui_status,
        "debug_open_session_tui_reason": result.debug_open_session_tui_reason,
        "debug_session_id": result.debug_session_id,
        "debug_tui_command": result.debug_tui_command,
        "debug_attach_url": result.debug_attach_url,
        "export_session_mode": result.export_session_mode,
        "export_session_status": result.export_session_status,
        "export_session_reason": result.export_session_reason,
        "session_export_path": str(Path(result.session_export_path).resolve(strict=False)) if result.session_export_path else "",
        "session_transcript_path": str(Path(result.session_transcript_path).resolve(strict=False)) if result.session_transcript_path else "",
    }


def zchat_prompt_pack_result_to_mcp_response(result: jobs.ZchatPromptPackResult) -> dict[str, Any]:
    return {
        "mode": result.mode,
        "request_id": result.request_id,
        "output_dir": str(Path(result.output_dir).resolve(strict=False)) if result.output_dir else "",
        "artifacts": result.artifacts,
        "status": result.status,
        "error": result.error,
    }


def zchat_import_pack_result_to_mcp_response(result: jobs.ZchatImportPackResult) -> dict[str, Any]:
    return {
        "mode": result.mode,
        "package_id": result.package_id,
        "verdict": result.verdict,
        "status": result.status,
        "error": result.error,
        "report_path": str(Path(result.report_path).resolve(strict=False)) if result.report_path else "",
        "files_imported": result.files_imported,
        "files_skipped": result.files_skipped,
    }


def zchat_verify_pack_result_to_mcp_response(result: jobs.ZchatVerifyPackResult) -> dict[str, Any]:
    return {
        "mode": result.mode,
        "verdict": result.verdict,
        "status": result.status,
        "error": result.error,
        "report_path": str(Path(result.report_path).resolve(strict=False)) if result.report_path else "",
    }


def zchat_decision_pack_result_to_mcp_response(result: jobs.ZchatDecisionPackResult) -> dict[str, Any]:
    return {
        "mode": result.mode,
        "decision_id": result.decision_id,
        "verdict": result.verdict,
        "status": result.status,
        "error": result.error,
        "decision_path": str(Path(result.decision_path).resolve(strict=False)) if result.decision_path else "",
        "manifest_path": str(Path(result.manifest_path).resolve(strict=False)) if result.manifest_path else "",
        "journal_path": str(Path(result.journal_path).resolve(strict=False)) if result.journal_path else "",
    }


def build_effective_job_config(
    *,
    timeout_seconds: Any = None,
    provider_id: Any = None,
    model_id: Any = None,
    debug_visible_terminal: Any = None,
    debug_open_session_tui: Any = None,
    opencode_attach_url: Any = None,
    export_session: Any = None,
    config_path: Any = None,
) -> tuple[jobs.JobConfig, Path | None]:
    config_file = _resolve_repo_path(config_path)
    config = jobs.load_config(config_file)
    timeout = _normalize_positive_int(timeout_seconds)
    provider = _normalize_text(provider_id)
    model = _normalize_text(model_id)
    visible_terminal = _normalize_bool(debug_visible_terminal)
    open_session_tui = _normalize_bool(debug_open_session_tui)
    attach_url = _normalize_text(opencode_attach_url)
    export_mode = _normalize_text(export_session)

    if timeout is not None:
        config.timeout_seconds = timeout
    if provider is not None:
        config.provider_id = provider
    if model is not None:
        config.model_id = model
    if visible_terminal is None:
        config.debug_visible_terminal = True
    else:
        config.debug_visible_terminal = visible_terminal
    if open_session_tui is not None:
        config.debug_open_session_tui = open_session_tui
    if attach_url is not None:
        config.opencode_attach_url = attach_url
    if export_mode is not None:
        config.export_session = jobs._normalize_export_session_mode(export_mode)

    return config, config_file.parent if config_file else None


def opencode_job_run_and_wait_impl(
    *,
    task_text: Any,
    directory: Any = None,
    timeout_seconds: Any = None,
    provider_id: Any = None,
    model_id: Any = None,
    debug_visible_terminal: Any = True,
    debug_open_session_tui: Any = None,
    opencode_attach_url: Any = None,
    export_session: Any = None,
    config_path: Any = None,
) -> dict[str, Any]:
    normalized_task = _normalize_text(task_text)
    if normalized_task is None:
        return _empty_response("invalid_task_text", "task_text must be a non-empty string.")

    working_directory = _resolve_repo_path(directory)
    if directory is not None and working_directory is None:
        return _empty_response("invalid_directory", "directory must be a non-empty string when provided.")
    if working_directory is not None:
        if not working_directory.exists():
            return _empty_response("invalid_directory", f"Directory not found: {working_directory}")
        if not working_directory.is_dir():
            return _empty_response("invalid_directory", f"Path is not a directory: {working_directory}")

    config, config_root = build_effective_job_config(
        timeout_seconds=timeout_seconds,
        provider_id=provider_id,
        model_id=model_id,
        debug_visible_terminal=debug_visible_terminal,
        debug_open_session_tui=debug_open_session_tui,
        opencode_attach_url=opencode_attach_url,
        export_session=export_session,
        config_path=config_path,
    )

    try:
        result = jobs.run_opencode_job(
            normalized_task,
            config=config,
            config_root=config_root,
            directory=str(working_directory) if working_directory else None,
        )
    except Exception as exc:
        return _empty_response("job_wrapper_exception", f"{type(exc).__name__}: {exc}")

    return job_result_to_mcp_response(result)


mcp = FastMCP(
    SERVER_NAME,
    instructions=(
        "Thin MCP server for the file-based OpenCode job wrapper. "
        "Use the single tool to run one OpenCode task and wait outside the model loop."
    ),
)


@mcp.tool(
    name=TOOL_NAME,
    description=(
        "Run one OpenCode job through the existing file-based wrapper and wait for "
        "result.md plus done.json before returning a compact summary and file paths."
    ),
)
def opencode_job_run_and_wait(
    task_text: str,
    directory: str | None = None,
    timeout_seconds: int | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    debug_visible_terminal: bool | None = True,
    debug_open_session_tui: bool | None = None,
    opencode_attach_url: str | None = None,
    export_session: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    return opencode_job_run_and_wait_impl(
        task_text=task_text,
        directory=directory,
        timeout_seconds=timeout_seconds,
        provider_id=provider_id,
        model_id=model_id,
        debug_visible_terminal=debug_visible_terminal,
        debug_open_session_tui=debug_open_session_tui,
        opencode_attach_url=opencode_attach_url,
        export_session=export_session,
        config_path=config_path,
    )


@mcp.tool(
    name="opencode_zchat_prompt_pack",
    description=(
        "Create a zchat prompt artifact pack: prompt.md, prompt_passport.md, request_manifest.json. "
        "Encodes the policy: use public GitHub raw URLs first; create temporary branch only if "
        "public context is insufficient. Supports allowed_paths, forbidden_paths, expected_outputs "
        "as comma-separated strings or plain text."
    ),
)
def opencode_zchat_prompt_pack(
    task_text: str,
    context: str | None = None,
    constraints: str | None = None,
    source_urls: str | None = None,
    output_dir: str | None = None,
    allowed_paths: str | None = None,
    forbidden_paths: str | None = None,
    expected_outputs: str | None = None,
) -> dict[str, Any]:
    normalized_task = _normalize_text(task_text)
    if normalized_task is None:
        return {"mode": jobs.ZCHAT_MODE_PROMPT_PACK, "status": "failed", "error": "task_text is required"}
    url_list = None
    if source_urls:
        url_list = [u.strip() for u in source_urls.split(",") if u.strip()]
    output = None
    if output_dir:
        output = Path(output_dir)
    result = jobs.zchat_prompt_pack(
        normalized_task,
        output_dir=output,
        context=_normalize_text(context) or "",
        constraints=_normalize_text(constraints) or "",
        source_urls=url_list,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        expected_outputs=expected_outputs,
    )
    return zchat_prompt_pack_result_to_mcp_response(result)


@mcp.tool(
    name="opencode_zchat_import_pack",
    description=(
        "Import a zchat ZIP intake package with strict contract validation. "
        "ZIP must contain manifest.json + checksums.sha256 + payload/. "
        "Enforces path traversal protection, secret protection, and scope boundaries. "
        "On success, applies payload to working tree and writes import_report.md."
    ),
)
def opencode_zchat_import_pack(
    zip_path: str,
    target_root: str | None = None,
) -> dict[str, Any]:
    normalized_zip = _normalize_text(zip_path)
    if normalized_zip is None:
        return {"mode": jobs.ZCHAT_MODE_IMPORT_PACK, "status": "failed", "verdict": jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL, "error": "zip_path is required"}
    zip_file = Path(normalized_zip)
    if not zip_file.exists():
        return {"mode": jobs.ZCHAT_MODE_IMPORT_PACK, "status": "failed", "verdict": jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL, "error": f"ZIP file not found: {zip_file}"}
    root = Path(target_root) if target_root else jobs.REPO_ROOT
    result = jobs.zchat_import_pack(zip_file, target_root=root)
    return zchat_import_pack_result_to_mcp_response(result)


@mcp.tool(
    name="opencode_zchat_verify_pack",
    description=(
        "Verify a zchat pack directory and produce verify_report.md with a machine verdict: "
        "accepted_for_review / rejected_structural / rejected_scope / needs_codex_decision."
    ),
)
def opencode_zchat_verify_pack(
    pack_dir: str,
) -> dict[str, Any]:
    normalized_dir = _normalize_text(pack_dir)
    if normalized_dir is None:
        return {"mode": jobs.ZCHAT_MODE_VERIFY_PACK, "status": "failed", "verdict": jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL, "error": "pack_dir is required"}
    dir_path = Path(normalized_dir)
    result = jobs.zchat_verify_pack(dir_path)
    return zchat_verify_pack_result_to_mcp_response(result)


@mcp.tool(
    name="opencode_zchat_decision_pack",
    description=(
        "Final Codex decision stage for a zchat request. Produces codex_decision.md and "
        "decision_manifest.json. Verdicts: accepted / rejected / needs_revision. "
        "Accepted decisions are journaled to accepted/<id>/; rejected to rejected/<id>/; "
        "needs_revision to reviews/<id>/."
    ),
)
def opencode_zchat_decision_pack(
    subject_id: str,
    verdict: str,
    rationale: str | None = None,
    evidence: str | None = None,
    reviewer: str | None = None,
) -> dict[str, Any]:
    normalized_subject = _normalize_text(subject_id)
    if normalized_subject is None:
        return {"mode": jobs.ZCHAT_MODE_DECISION_PACK, "status": "failed", "error": "subject_id is required"}
    normalized_verdict = _normalize_text(verdict)
    if normalized_verdict is None:
        return {"mode": jobs.ZCHAT_MODE_DECISION_PACK, "status": "failed", "error": "verdict is required"}
    result = jobs.zchat_decision_pack(
        subject_id=normalized_subject,
        reviewer=_normalize_text(reviewer) or "codex",
        verdict=normalized_verdict,
        rationale=_normalize_text(rationale) or "",
        evidence=_normalize_text(evidence) or "",
    )
    return zchat_decision_pack_result_to_mcp_response(result)


def main() -> None:
    _ensure_started_via_starter()
    mcp.run()


if __name__ == "__main__":
    main()
