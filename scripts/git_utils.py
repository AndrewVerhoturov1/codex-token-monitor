import hashlib
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def zchat_slug_id() -> str:
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    short_hash = hashlib.sha256(now.isoformat().encode()).hexdigest()[:8]
    return f"ZCHAT-{ts}-{short_hash}"


def zchat_slug_id_is_valid(slug: str) -> bool:
    import re
    return bool(re.match(r"^ZCHAT-\d{8}-\d{6}-[a-f0-9]{8}$", slug))


def zchat_request_name(task: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    slug = _zchat_task_to_slug(task) if task else "task"
    return f"ZCHAT-{ts}-{slug}"


def _zchat_task_to_slug(task: str) -> str:
    import re
    raw = task.strip().casefold()
    raw = re.sub(r"[^a-z0-9\s-]", "", raw)
    raw = re.sub(r"\s+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw)
    raw = raw.strip("-")
    if len(raw) > 48:
        raw = raw[:48].rstrip("-")
    if not raw:
        raw = "task"
    return raw


def zchat_request_name_is_valid(name: str) -> bool:
    import re
    return bool(re.match(r"^ZCHAT-\d{8}-\d{6}-[a-z0-9][a-z0-9-]*$", name))


@dataclass
class BranchMetadata:
    slug_id: str = ""
    branch_name: str = ""
    base_branch: str = ""
    repo_path: str = ""
    created: bool = False
    pushed: bool = False
    deleted: bool = False
    error: str = ""


def _git_cmd(repo_path: Path, *args: str, capture: bool = True, timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(repo_path),
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def get_current_branch(repo_path: Path) -> str:
    code, stdout, _ = _git_cmd(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    if code == 0:
        return stdout.strip()
    return ""


def get_default_branch(repo_path: Path) -> str:
    code, stdout, _ = _git_cmd(repo_path, "remote", "show", "origin", timeout=15)
    if code != 0:
        return "main"
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("HEAD branch:"):
            return line.split(":", 1)[1].strip()
    return "main"


def create_temp_branch(repo_path: Path, branch_name: str, base_branch: str = "") -> BranchMetadata:
    if not base_branch:
        base_branch = get_current_branch(repo_path) or get_default_branch(repo_path)
    code, _, stderr = _git_cmd(repo_path, "checkout", "-b", branch_name, base_branch)
    if code != 0:
        return BranchMetadata(
            branch_name=branch_name,
            base_branch=base_branch,
            repo_path=str(repo_path),
            created=False,
            error=f"git checkout -b failed: {stderr.strip()}",
        )
    return BranchMetadata(
        branch_name=branch_name,
        base_branch=base_branch,
        repo_path=str(repo_path),
        created=True,
    )


def push_temp_branch(repo_path: Path, branch_name: str) -> BranchMetadata:
    code, _, stderr = _git_cmd(repo_path, "push", "-u", "origin", branch_name, timeout=60)
    if code != 0:
        return BranchMetadata(
            branch_name=branch_name,
            repo_path=str(repo_path),
            pushed=False,
            error=f"git push failed: {stderr.strip()}",
        )
    return BranchMetadata(
        branch_name=branch_name,
        repo_path=str(repo_path),
        pushed=True,
    )


def delete_temp_branch(repo_path: Path, branch_name: str, *, return_to: str = "") -> BranchMetadata:
    if not return_to:
        return_to = get_default_branch(repo_path)
    _git_cmd(repo_path, "checkout", return_to)
    code, _, stderr = _git_cmd(repo_path, "branch", "-D", branch_name)
    local_ok = code == 0
    error = ""
    if not local_ok:
        error = f"local delete failed: {stderr.strip()}"
    code2, _, stderr2 = _git_cmd(repo_path, "push", "origin", "--delete", branch_name, timeout=60)
    remote_ok = code2 == 0
    if not remote_ok:
        if error:
            error += "; "
        error += f"remote delete failed: {stderr2.strip()}"
    return BranchMetadata(
        branch_name=branch_name,
        repo_path=str(repo_path),
        deleted=local_ok,
        error=error,
    )


def resolve_branch_decision(
    *,
    source_urls: list[str] | None = None,
    has_public_github_context: bool = False,
) -> dict:
    if source_urls:
        has_public_github_context = True
    if has_public_github_context:
        return {
            "decision": "no_branch_needed",
            "reason": "Public GitHub context is sufficient; no temporary branch required.",
            "create_branch": False,
        }
    return {
        "decision": "branch_may_be_needed",
        "reason": "Public GitHub context insufficient; a temporary branch MAY be created.",
        "create_branch": False,
    }


def can_create_branch(repo_path: Path) -> bool:
    code, _, _ = _git_cmd(repo_path, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        return False
    code2, _, _ = _git_cmd(repo_path, "remote", "get-url", "origin")
    if code2 != 0:
        return False
    return True


def branch_metadata_to_passport(meta: BranchMetadata) -> str:
    lines = [
        f"- **slug_id**: {meta.slug_id}" if meta.slug_id else "",
        f"- **branch_name**: {meta.branch_name}",
        f"- **base_branch**: {meta.base_branch}" if meta.base_branch else "",
        f"- **created**: {meta.created}",
        f"- **pushed**: {meta.pushed}",
        f"- **deleted**: {meta.deleted}",
    ]
    if meta.error:
        lines.append(f"- **error**: {meta.error}")
    return "\n".join(line for line in lines if line)
