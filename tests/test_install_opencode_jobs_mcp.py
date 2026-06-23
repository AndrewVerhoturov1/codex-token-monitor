import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "install_opencode_jobs_mcp.py"
SPEC = importlib.util.spec_from_file_location("install_opencode_jobs_mcp", MODULE_PATH)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class InstallOpenCodeJobsMcpTests(unittest.TestCase):

    def test_replace_existing_block(self) -> None:
        original = (
            'model = "gpt-5.5"\n\n'
            "[mcp_servers.opencode_jobs]\n"
            'command = "python"\n'
            'args = ["-m", "scripts.codex_token_monitor_opencode_jobs_mcp"]\n'
            "cwd = 'D:\\old'\n"
            "\n"
            "[mcp_servers.playwright]\n"
            'command = "npx"\n'
        )
        block = installer.build_server_block(Path(r"D:\repo"))
        updated, changed, had_existing = installer.replace_or_append_server_block(original, block)

        self.assertTrue(changed)
        self.assertTrue(had_existing)
        self.assertIn('args = ["scripts/start_opencode_jobs_mcp.py"]', updated)
        self.assertNotIn('args = ["-m", "scripts.codex_token_monitor_opencode_jobs_mcp"]', updated)
        self.assertIn("[mcp_servers.playwright]", updated)

    def test_replace_existing_block_handles_windows_repo_path_with_backslashes(self) -> None:
        original = (
            "[mcp_servers.opencode_jobs]\n"
            'command = "python"\n'
            'args = ["-m", "scripts.codex_token_monitor_opencode_jobs_mcp"]\n'
            "cwd = 'D:\\old'\n"
        )
        repo_root = Path(r"D:\Codex+opencode_new\Proect_C_O\codex-token-monitor")
        block = installer.build_server_block(repo_root)
        updated, changed, had_existing = installer.replace_or_append_server_block(original, block)

        self.assertTrue(changed)
        self.assertTrue(had_existing)
        self.assertIn(str(repo_root), updated)

    def test_append_missing_block(self) -> None:
        original = 'model = "gpt-5.5"\n'
        block = installer.build_server_block(Path(r"D:\repo"))
        updated, changed, had_existing = installer.replace_or_append_server_block(original, block)

        self.assertTrue(changed)
        self.assertFalse(had_existing)
        self.assertIn("[mcp_servers.opencode_jobs]", updated)
        self.assertTrue(updated.endswith("\n"))

    def test_install_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config_path = tmpdir / "config.toml"
            config_path.write_text('model = "gpt-5.5"\n', encoding="utf-8")

            result = installer.install_opencode_jobs_mcp(
                config_path=config_path,
                repo_root=Path(r"D:\repo"),
                dry_run=True,
            )
            config_text = config_path.read_text(encoding="utf-8")

        self.assertTrue(result["changed"])
        self.assertTrue(result["dry_run"])
        self.assertNotIn("[mcp_servers.opencode_jobs]", config_text)

    def test_install_creates_backup_when_rewriting_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config_path = tmpdir / "config.toml"
            config_path.write_text(
                "[mcp_servers.opencode_jobs]\n"
                'command = "python"\n'
                'args = ["-m", "scripts.codex_token_monitor_opencode_jobs_mcp"]\n',
                encoding="utf-8",
            )

            result = installer.install_opencode_jobs_mcp(
                config_path=config_path,
                repo_root=Path(r"D:\repo"),
                dry_run=False,
            )

            backup_path = Path(str(result["backup_path"]))
            self.assertTrue(backup_path.exists())
            self.assertIn("codex_token_monitor_opencode_jobs_mcp", backup_path.read_text(encoding="utf-8"))
            self.assertIn("scripts/start_opencode_jobs_mcp.py", config_path.read_text(encoding="utf-8"))
            self.assertTrue(result["restart_required"])


if __name__ == "__main__":
    unittest.main()
