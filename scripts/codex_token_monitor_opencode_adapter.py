import argparse
import json
import subprocess
import sys
from pathlib import Path


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


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCode CLI adapter")
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--model-id", required=True)
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

    model_str = f"{args.provider_id}/{args.model_id}"

    try:
        proc = subprocess.run(
            ["opencode", "run", "--model", model_str],
            input=augmented_task,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        _atomic_write_text(result_md, "Error: opencode CLI not found\n")
        _atomic_write_json(done_json, {"status": "failed", "reason": "opencode_not_found", "summary": ""})
        sys.exit(1)

    if not done_json.exists():
        output = proc.stdout or proc.stderr or ""
        lines = output.splitlines()
        tail = lines[-80:] if lines else []
        summary = "\n".join(tail)[:4000] if tail else ""
        if proc.returncode == 0:
            status, reason = "completed", "completed"
        else:
            status, reason = "failed", f"opencode_exit_{proc.returncode}"
        if not result_md.exists():
            _atomic_write_text(result_md, output or f"OpenCode exit code: {proc.returncode}\n")
        _atomic_write_json(done_json, {"status": status, "reason": reason, "summary": summary})

    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
