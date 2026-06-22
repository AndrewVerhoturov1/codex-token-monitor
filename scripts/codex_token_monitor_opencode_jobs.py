import argparse
import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

ALLOWED_PLACEHOLDERS = frozenset({"{task_file}", "{job_dir}", "{provider_id}", "{model_id}"})

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
EXIT_COMPLETED = 0
EXIT_PARTIAL = 10
EXIT_BLOCKED = 20
EXIT_FAILED = 30
EXIT_CONFIG_ERROR = 31
EXIT_PROTOCOL_ERROR = 32


@dataclass
class JobConfig:
    jobs_dir: str = "_local/codex-token-monitor/opencode-jobs"
    timeout_seconds: int = 600
    poll_interval_ms: int = 1000
    provider_id: str = "deepseek"
    model_id: str = "deepseek-v4-flash"
    summary_tail_lines: int = 80
    summary_max_chars: int = 4000
    result_max_chars: int = 0
    command_template: list[str] = field(default_factory=lambda: [
        "opencode", "--model", "{model_id}", "--provider", "{provider_id}",
        "--task-file", "{task_file}", "--job-dir", "{job_dir}",
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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_json_safe(path: Path) -> Any | None:
    try:
        return _read_json(path)
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


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


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


def load_config(config_path: Path | None = None) -> JobConfig:
    if config_path is None:
        config_path = CONFIG_DIR / "opencode_job_defaults.json"
    defaults = JobConfig()
    data = _read_json_safe(config_path)
    if not data:
        return defaults
    kwargs = {k: data.get(k, getattr(defaults, k)) for k in JobConfig.__dataclass_fields__}
    return JobConfig(**kwargs)


def _resolve_jobs_dir(config: JobConfig, config_root: Path | None = None) -> Path:
    jobs_dir = Path(config.jobs_dir)
    if not jobs_dir.is_absolute():
        if config_root is not None:
            jobs_dir = config_root / jobs_dir
        else:
            jobs_dir = REPO_ROOT / jobs_dir
    return jobs_dir


def _extract_summary(stdout_path: Path, config: JobConfig) -> str:
    try:
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    tail = lines[-config.summary_tail_lines:] if config.summary_tail_lines > 0 else lines
    summary = "\n".join(tail)
    if config.summary_max_chars > 0 and len(summary) > config.summary_max_chars:
        summary = summary[:config.summary_max_chars] + "..."
    return summary


def run_opencode_job(task_text: str, *, config: JobConfig, config_root: Path | None = None) -> JobResult:
    job_id = str(uuid.uuid4())
    provider_id = config.provider_id
    model_id = config.model_id

    jobs_dir = _resolve_jobs_dir(config, config_root=config_root)
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    started_at = _utcnow()

    task_file = job_dir / "task.txt"
    task_file.write_text(task_text, encoding="utf-8")

    result_path = job_dir / "result.md"
    done_path = job_dir / "done.json"
    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"

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
            summary="",
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
        )
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** {e}\n")
        _atomic_write_json(done_path, asdict(result))
        return result

    command_tokens = _substitute_placeholders(
        config.command_template,
        task_file=str(task_file),
        job_dir=str(job_dir),
        provider_id=provider_id,
        model_id=model_id,
    )

    try:
        stdout_handle = open(stdout_path, "w", encoding="utf-8")
        stderr_handle = open(stderr_path, "w", encoding="utf-8")
        process = subprocess.Popen(
            command_tokens,
            shell=False,
            stdout=stdout_handle,
            stderr=stderr_handle,
            cwd=str(REPO_ROOT),
        )
        stdout_handle.close()
        stderr_handle.close()
    except OSError as e:
        finished_at = _utcnow()
        duration_ms = 0
        result = JobResult(
            job_id=job_id,
            status=STATUS_FAILED,
            reason=f"Failed to launch process: {e}",
            summary="",
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
        )
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** Failed to launch process: {e}\n")
        _atomic_write_json(done_path, asdict(result))
        return result

    timed_out = False
    protocol_violation = False
    poll_interval = config.poll_interval_ms / 1000.0
    deadline = time.monotonic() + config.timeout_seconds

    while time.monotonic() < deadline:
        ret = process.poll()
        if ret is not None:
            break
        if done_path.exists() and not result_path.exists():
            protocol_violation = True
            _terminate_process_tree(process.pid)
            try:
                process.wait(timeout=30)
            except Exception:
                pass
            break
        time.sleep(poll_interval)
    else:
        timed_out = True
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

    if protocol_violation:
        status = STATUS_FAILED
        reason = "protocol_violation_done_before_result"
        summary = _extract_summary(stdout_path, config)
        _atomic_write_text(result_path, f"# Protocol Violation\n\ndone.json was written before result.md\n")
    elif timed_out:
        status = STATUS_BLOCKED
        reason = "timed_out"
        summary = _extract_summary(stdout_path, config)
        _atomic_write_text(result_path, f"# Job Blocked\n\n**Reason:** timed_out\n")
    elif done_path.exists():
        done_data = _read_json_safe(done_path) or {}
        status = done_data.get("status", STATUS_FAILED)
        reason = done_data.get("reason", "")
        summary = done_data.get("summary", "")
    elif exit_code is not None:
        status = STATUS_FAILED
        reason = "process_exited_without_done"
        summary = _extract_summary(stdout_path, config)
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** process_exited_without_done\n")
    else:
        status = STATUS_FAILED
        reason = "process_exited_without_done"
        summary = ""
        _atomic_write_text(result_path, f"# Job Failed\n\n**Reason:** process_exited_without_done\n")

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
    )

    _atomic_write_json(done_path, asdict(result))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an OpenCode job")
    parser.add_argument("--task-file", required=True, type=str, help="Path to task file")
    parser.add_argument("--config", type=str, default=None, help="Path to config file")
    args = parser.parse_args()

    task_path = Path(args.task_file)
    if not task_path.exists():
        print(f"Error: task file not found: {task_path}", file=sys.stderr)
        sys.exit(EXIT_CONFIG_ERROR)

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    config_root = config_path.parent if config_path else None

    task_text = task_path.read_text(encoding="utf-8")

    try:
        result = run_opencode_job(task_text, config=config, config_root=config_root)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(EXIT_FAILED)

    print(f"job_id: {result.job_id}")
    print(f"status: {result.status}")
    print(f"reason: {result.reason}")
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
