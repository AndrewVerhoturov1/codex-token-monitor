import argparse
import json
import re
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.resolve(strict=False)
DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
SERVER_HEADER = "[mcp_servers.opencode_jobs]"
SERVER_BLOCK_PATTERN = re.compile(
    r"(?ms)^\[mcp_servers\.opencode_jobs\]\n.*?(?=^\[|\Z)"
)


def build_server_block(repo_root: Path) -> str:
    return (
        f"{SERVER_HEADER}\n"
        'command = "python"\n'
        'args = ["scripts/start_opencode_jobs_mcp.py"]\n'
        f"cwd = '{repo_root}'\n"
        "startup_timeout_sec = 30.0\n"
        "tool_timeout_sec = 900.0\n"
    )


def replace_or_append_server_block(text: str, block: str) -> tuple[str, bool, bool]:
    normalized = text.replace("\r\n", "\n")
    if SERVER_BLOCK_PATTERN.search(normalized):
        updated = SERVER_BLOCK_PATTERN.sub(lambda _: block + "\n", normalized, count=1)
        return updated, updated != normalized, True

    prefix = normalized
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    updated = prefix + block + "\n"
    return updated, True, False


def build_backup_path(config_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config_path.with_name(f"{config_path.name}.{stamp}.bak")


def install_opencode_jobs_mcp(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    repo_root: Path = REPO_ROOT,
    dry_run: bool = False,
) -> dict[str, object]:
    config_path = config_path.expanduser().resolve(strict=False)
    repo_root = repo_root.resolve(strict=False)
    block = build_server_block(repo_root)

    original = ""
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8")

    updated, changed, had_existing = replace_or_append_server_block(original, block)
    result: dict[str, object] = {
        "config_path": str(config_path),
        "repo_root": str(repo_root),
        "had_existing_block": had_existing,
        "changed": changed,
        "dry_run": dry_run,
        "backup_path": "",
        "restart_required": changed,
    }

    if dry_run or not changed:
        return result

    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if config_path.exists():
        backup_path = build_backup_path(config_path)
        backup_path.write_text(original, encoding="utf-8")
    config_path.write_text(updated, encoding="utf-8")
    result["backup_path"] = str(backup_path) if backup_path else ""
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install or update the user-level opencode_jobs MCP block in Codex config."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to Codex config.toml. Defaults to ~/.codex/config.toml",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root that contains scripts/start_opencode_jobs_mcp.py",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing config.toml",
    )
    args = parser.parse_args()

    result = install_opencode_jobs_mcp(
        config_path=Path(args.config),
        repo_root=Path(args.repo_root),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
