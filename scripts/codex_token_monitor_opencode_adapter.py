import argparse
import json
import subprocess
import sys
from pathlib import Path


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

    original_task = task_file.read_text(encoding="utf-8")

    protocol = (
        f"\n\n=== PROTOCOL INSTRUCTIONS ===\n"
        f"After completing the task, write the final result to {result_md}\n"
        f"Then write completion metadata to {done_json} "
        f'with format: {{"status": "completed|partial|blocked|failed", '
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
        result_md.write_text("Error: opencode CLI not found\n", encoding="utf-8")
        done_json.write_text(
            json.dumps({"status": "failed", "reason": "opencode_not_found", "summary": ""},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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
            result_md.write_text(output or f"OpenCode exit code: {proc.returncode}\n",
                                 encoding="utf-8")
        done_json.write_text(
            json.dumps({"status": status, "reason": reason, "summary": summary},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
