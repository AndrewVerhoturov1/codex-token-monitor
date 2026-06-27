import importlib.util
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_token_monitor_opencode_jobs.py"
SPEC = importlib.util.spec_from_file_location("codex_token_monitor_opencode_jobs", MODULE_PATH)
jobs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(jobs)

_GIT_UTILS_PATH = ROOT / "scripts" / "git_utils.py"
_GIT_SPEC = importlib.util.spec_from_file_location("git_utils", _GIT_UTILS_PATH)
_git_utils_module = importlib.util.module_from_spec(_GIT_SPEC)
assert _GIT_SPEC.loader is not None
_GIT_SPEC.loader.exec_module(_git_utils_module)

_ORIGINAL_ZCHAT_SKIP_URL_CHECK: bool | None = None


def setUpModule() -> None:
    global _ORIGINAL_ZCHAT_SKIP_URL_CHECK
    _ORIGINAL_ZCHAT_SKIP_URL_CHECK = getattr(jobs, "_ZCHAT_SKIP_URL_CHECK", False)
    jobs._ZCHAT_SKIP_URL_CHECK = True


def tearDownModule() -> None:
    if _ORIGINAL_ZCHAT_SKIP_URL_CHECK is not None:
        jobs._ZCHAT_SKIP_URL_CHECK = _ORIGINAL_ZCHAT_SKIP_URL_CHECK


class ZworkerRequestIdTests(unittest.TestCase):

    def test_zworker_request_name_format(self) -> None:
        name = _git_utils_module.zworker_request_name("Add login feature")
        self.assertTrue(_git_utils_module.zworker_request_name_is_valid(name),
                        f"Expected valid ZWORKER name, got: {name}")
        self.assertTrue(name.startswith("ZWORKER-"))
        parts = name.split("-")
        self.assertEqual(parts[0], "ZWORKER")
        self.assertEqual(len(parts[1]), 8)
        self.assertEqual(len(parts[2]), 6)

    def test_zworker_request_name_slug_from_task(self) -> None:
        name = _git_utils_module.zworker_request_name("Fix login bug")
        self.assertIn("fix-login-bug", name)

    def test_zworker_request_name_lowercase(self) -> None:
        name = _git_utils_module.zworker_request_name("ADD LOGIN Feature")
        self.assertNotIn("ADD", name)
        self.assertNotIn("LOGIN", name)

    def test_zworker_request_name_none_task(self) -> None:
        name = _git_utils_module.zworker_request_name(None)
        self.assertTrue(name.endswith("-task"))

    def test_zworker_request_name_empty_task(self) -> None:
        name = _git_utils_module.zworker_request_name("")
        self.assertTrue(name.endswith("-task"))

    def test_zworker_request_name_invalid_rejects(self) -> None:
        self.assertFalse(_git_utils_module.zworker_request_name_is_valid(
            "ZCHAT-20260627-120000-test"
        ))
        self.assertFalse(_git_utils_module.zworker_request_name_is_valid(
            "ZWORKER-abc-def"
        ))
        self.assertFalse(_git_utils_module.zworker_request_name_is_valid(
            ""
        ))
        self.assertFalse(_git_utils_module.zworker_request_name_is_valid(
            "not-a-zworker-id"
        ))

    def test_zworker_request_name_is_valid_accepts(self) -> None:
        self.assertTrue(_git_utils_module.zworker_request_name_is_valid(
            "ZWORKER-20260627-120000-add-login-feature"
        ))
        self.assertTrue(_git_utils_module.zworker_request_name_is_valid(
            "ZWORKER-20260627-120000-fix-bug"
        ))

    def test_zworker_request_name_from_prompt_pack_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Test task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            self.assertTrue(
                _git_utils_module.zworker_request_name_is_valid(result.request_id),
                f"Result request_id should be valid: {result.request_id}",
            )

    def test_zworker_slug_matches_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Build login page", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            self.assertIn("build-login-page", result.request_id)

    def test_zworker_rejects_stale_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Make beautiful tetris",
                output_dir=output_dir,
                request_id="ZWORKER-20260627-191435-stylish-calculator",
            )
            self.assertEqual(result.status, "failed")
            self.assertIn("slug mismatch", result.error.lower())

    def test_zworker_accepts_matching_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            task = "Add login feature"
            name = _git_utils_module.zworker_request_name(task)
            result = jobs.zworker_prompt_pack(
                task,
                output_dir=output_dir,
                request_id=name,
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.request_id, name)

    def test_zworker_accepts_revision_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "stylish tetris",
                output_dir=output_dir,
                request_id="ZWORKER-20260627-191435-stylish-tetris-ver2",
            )
            self.assertEqual(result.status, "completed")

    def test_zworker_revision_name(self) -> None:
        base = "ZWORKER-20260627-120000-add-login-feature"
        rev2 = _git_utils_module.zworker_revision_name(base, 2)
        self.assertEqual(rev2, "ZWORKER-20260627-120000-add-login-feature-ver2")
        rev3 = _git_utils_module.zworker_revision_name(base, 3)
        self.assertEqual(rev3, "ZWORKER-20260627-120000-add-login-feature-ver3")

    def test_zworker_revision_name_invalid_revision(self) -> None:
        with self.assertRaises(ValueError):
            _git_utils_module.zworker_revision_name("ZWORKER-20260627-120000-test", 1)

    def test_zworker_revision_name_is_valid(self) -> None:
        self.assertTrue(_git_utils_module.zworker_revision_name_is_valid(
            "ZWORKER-20260627-120000-add-login-feature-ver2"
        ))
        self.assertTrue(_git_utils_module.zworker_revision_name_is_valid(
            "ZWORKER-20260627-120000-test-ver3"
        ))
        self.assertFalse(_git_utils_module.zworker_revision_name_is_valid(
            "ZWORKER-20260627-120000-test"
        ))
        self.assertFalse(_git_utils_module.zworker_revision_name_is_valid(
            "ZCHAT-20260627-120000-test-ver2"
        ))


class ZworkerManualDocsTests(unittest.TestCase):

    def test_manual_exists_and_is_readable(self) -> None:
        manual_path = ROOT / "docs" / "zworker_external_agent_manual.md"
        self.assertTrue(manual_path.exists(), f"Manual not found: {manual_path}")
        content = manual_path.read_text(encoding="utf-8")
        self.assertIn("external agent", content.lower())
        self.assertIn("answer.md", content)

    def test_manual_no_strict_response_modes(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("Strict Response Modes", content)

    def test_manual_no_package_ready(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("PACKAGE_READY", content)

    def test_manual_no_contract_conflict(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("CONTRACT_CONFLICT", content)

    def test_manual_no_blocked_missing_context(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("BLOCKED_MISSING_CONTEXT", content)

    def test_manual_no_bad_zip_worse_than_no_zip(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("A bad ZIP is worse than no ZIP", content)

    def test_manual_says_zip_always_contains_answer_md(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertIn("answer.md", content.lower())
        self.assertIn("always required", content.lower())

    def test_manual_missing_info_ask_not_fabricate(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertIn("do not fabricate", content.lower())


class ZworkerNavigationDocsTests(unittest.TestCase):

    def test_navigation_exists_and_readable(self) -> None:
        nav_path = ROOT / "docs" / "zworker_repo_navigation.md"
        self.assertTrue(nav_path.exists(), f"Navigation not found: {nav_path}")
        content = nav_path.read_text(encoding="utf-8")
        self.assertIn("ZWORKER-", content)

    def test_navigation_no_strict_zip_contract(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("Strict ZIP Contract", content)
        self.assertNotIn("strict workflow", content)

    def test_navigation_no_auto_apply_as_external_contract(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("auto-apply as part of the external contract", content.lower())

    def test_navigation_no_package_ready(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("PACKAGE_READY", content)

    def test_navigation_no_blocked_missing_context(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("BLOCKED_MISSING_CONTEXT", content)


class ZworkerTemplatesTests(unittest.TestCase):

    def test_prompt_template_exists(self) -> None:
        tmpl = (ROOT / ".ai" / "zworker" / "templates" / "prompt.md")
        self.assertTrue(tmpl.exists(), f"Template not found: {tmpl}")
        content = tmpl.read_text(encoding="utf-8")
        self.assertIn("{request_id}", content)
        self.assertIn("{task}", content)
        self.assertIn("answer.md", content)

    def test_passport_template_exists(self) -> None:
        tmpl = (ROOT / ".ai" / "zworker" / "templates" / "prompt_passport.md")
        self.assertTrue(tmpl.exists(), f"Template not found: {tmpl}")
        content = tmpl.read_text(encoding="utf-8")
        self.assertIn("{request_id}", content)
        self.assertIn("{task}", content)

    def test_request_manifest_template_exists(self) -> None:
        tmpl = (ROOT / ".ai" / "zworker" / "templates" / "request_manifest.json")
        self.assertTrue(tmpl.exists(), f"Template not found: {tmpl}")
        manifest = json.loads(tmpl.read_text(encoding="utf-8"))
        self.assertEqual(manifest["strict_zip_contract"], False)
        self.assertEqual(manifest["requires_answer_md"], True)

    def test_runtime_gitkeep_exists(self) -> None:
        gitkeep = ROOT / ".ai" / "zworker" / "runtime" / ".gitkeep"
        self.assertTrue(gitkeep.exists(), f"Gitkeep not found: {gitkeep}")

    def test_gitignore_covers_zworker_runtime(self) -> None:
        gi = ROOT / ".gitignore"
        content = gi.read_text(encoding="utf-8")
        self.assertIn(".ai/zworker/runtime/", content)

    def test_readme_exists(self) -> None:
        readme_path = ROOT / ".ai" / "zworker" / "readme.md"
        self.assertTrue(readme_path.exists(), f"Readme not found: {readme_path}")
        content = readme_path.read_text(encoding="utf-8")
        self.assertIn("Zworker", content)
        self.assertIn("strict_zip_contract", content)


class ZworkerPromptPackShortPromptTests(unittest.TestCase):

    def _pack(self, task: str, **kwargs) -> tuple:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(task, output_dir=output_dir, **kwargs)
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8") if result.status == "completed" else ""
            return result, prompt_text

    def test_prompt_creates_all_artifacts(self) -> None:
        result, _ = self._pack("Test task")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.request_id)
        self.assertEqual(len(result.artifacts), 3)
        self.assertIn("prompt.md", result.artifacts)
        self.assertIn("prompt_passport.md", result.artifacts)
        self.assertIn("request_manifest.json", result.artifacts)

    def test_prompt_is_short(self) -> None:
        _, prompt_text = self._pack("Build login page", context="Use React")
        lines = [l for l in prompt_text.splitlines() if l.strip()]
        self.assertLess(len(lines), 50, f"Prompt is too long: {len(lines)} lines")

    def test_prompt_contains_request_id(self) -> None:
        result, prompt_text = self._pack("Task one")
        self.assertIn(result.request_id, prompt_text)

    def test_prompt_contains_manual_url(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertIn("zworker_external_agent_manual.md", prompt_text)

    def test_prompt_contains_navigation_url(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertIn("zworker_repo_navigation.md", prompt_text)

    def test_prompt_contains_task(self) -> None:
        _, prompt_text = self._pack("Build login page")
        self.assertIn("Build login page", prompt_text)

    def test_prompt_contains_zip_and_answer_md(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertIn("answer.md", prompt_text)
        self.assertIn("ZIP", prompt_text)

    def test_prompt_contains_files_to_read_with_urls(self) -> None:
        _, prompt_text = self._pack("Task", source_urls=["https://example.com/file.py"])
        self.assertIn("https://example.com/file.py", prompt_text)
        self.assertIn("Files to read", prompt_text)

    def test_prompt_no_specific_files_when_no_urls(self) -> None:
        _, prompt_text = self._pack("Standalone task")
        self.assertIn("No specific repository files are required", prompt_text)

    def test_prompt_does_NOT_contain_authority_hierarchy(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("Authority / Conflict Hierarchy", prompt_text)
        self.assertNotIn("authority_order", prompt_text)

    def test_prompt_does_NOT_contain_stop_if_missing(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("Stop-if-Missing-Information Policy", prompt_text)
        self.assertNotIn("BLOCKED_MISSING_CONTEXT", prompt_text)

    def test_prompt_does_NOT_contain_sources_read_report_requirement(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("Sources Read Report Requirement", prompt_text)

    def test_prompt_does_NOT_contain_response_format(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("Response Format", prompt_text)

    def test_prompt_does_NOT_contain_package_ready(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("PACKAGE_READY", prompt_text)

    def test_prompt_does_NOT_contain_contract_conflict(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("CONTRACT_CONFLICT", prompt_text)

    def test_prompt_does_NOT_contain_preflight_checklist(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("Preflight Checklist", prompt_text)

    def test_prompt_does_NOT_contain_manifest_json(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("manifest.json", prompt_text)

    def test_prompt_does_NOT_contain_checksums(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("checksums.sha256", prompt_text)

    def test_prompt_does_NOT_contain_payload(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("payload/", prompt_text)

    def test_prompt_does_NOT_contain_bad_zip(self) -> None:
        _, prompt_text = self._pack("Task")
        self.assertNotIn("A bad ZIP is worse than no ZIP", prompt_text)


class ZworkerBranchBlockTests(unittest.TestCase):

    def test_no_branch_block_when_branch_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task without sources",
                output_dir=output_dir,
            )
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertNotIn("Temporary Context Branch", prompt_text)
            self.assertNotIn("Branch status: Not yet created", prompt_text)
            self.assertNotIn("create_branch=false", prompt_text.lower())

    def test_no_contradictory_branch_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task without sources",
                output_dir=output_dir,
            )
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertNotIn("available", prompt_text.lower())

    def test_no_branch_when_sources_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task with sources",
                output_dir=output_dir,
                source_urls=["https://example.com/file.py"],
            )
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertNotIn("Temporary Context Branch", prompt_text)


class ZworkerManifestTests(unittest.TestCase):

    def test_manifest_has_internal_accounting_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("request_id", manifest)
            self.assertIn("slug", manifest)
            self.assertIn("task_summary", manifest)
            self.assertIn("manual_url", manifest)
            self.assertIn("repo_navigation_url", manifest)
            self.assertIn("files_to_read", manifest)
            self.assertEqual(manifest["strict_zip_contract"], False)
            self.assertEqual(manifest["requires_answer_md"], True)
            self.assertIn("created_at", manifest)

    def test_manifest_no_legacy_zchat_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("manifest_version", manifest)
            self.assertNotIn("zip_layout", manifest)
            self.assertNotIn("required_reading", manifest)
            self.assertNotIn("authority_order", manifest)
            self.assertNotIn("missing_information_policy", manifest)
            self.assertNotIn("source_policy", manifest)

    def test_manifest_files_to_read_empty_for_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files_to_read"], [])

    def test_manifest_files_to_read_populated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                source_urls=["https://example.com/a.py", "https://example.com/b.py"],
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files_to_read"], ["https://example.com/a.py", "https://example.com/b.py"])


class ZworkerPassportTests(unittest.TestCase):

    def test_passport_contains_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Build feature X", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            passport_text = (output_dir / "prompt_passport.md").read_text(encoding="utf-8")
            self.assertIn(result.request_id, passport_text)
            self.assertIn("Build feature X", passport_text)

    def test_passport_contains_manual_nav_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            passport_text = (output_dir / "prompt_passport.md").read_text(encoding="utf-8")
            self.assertIn("zworker_external_agent_manual.md", passport_text)
            self.assertIn("zworker_repo_navigation.md", passport_text)

    def test_passport_has_human_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            passport_text = (output_dir / "prompt_passport.md").read_text(encoding="utf-8")
            self.assertIn("Copy prompt.md", passport_text)
            self.assertIn("download ZIP", passport_text)


class ZworkerUnpackTests(unittest.TestCase):

    def _make_zip(self, dir_path: Path, files: dict) -> Path:
        import zipfile
        zip_path = dir_path / "result.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return zip_path

    def test_unpack_valid_zip_with_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "answer.md": "# Answer\n\nDone.\n",
                "src/file.py": "print('hello')\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-001", target_root=root)
            self.assertEqual(output.status, "completed")
            self.assertTrue(output.answer_found)
            self.assertEqual(output.files_extracted, 2)
            self.assertEqual(output.files_rejected, 0)
            self.assertIn("accepted", output.verdict)

            inbox = Path(output.unpack_dir)
            self.assertTrue((inbox / "answer.md").exists())
            self.assertTrue((inbox / "src" / "file.py").exists())

    def test_unpack_no_answer_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "src/file.py": "print('hello')\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-002", target_root=root)
            self.assertEqual(output.status, "completed")
            self.assertFalse(output.answer_found)
            self.assertEqual(output.verdict, "accepted_missing_answer")

    def test_unpack_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "/etc/passwd": "hack\n",
                "answer.md": "# ok\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-003", target_root=root)
            self.assertGreater(output.files_rejected, 0)
            self.assertTrue(any("Absolute path" in d for d in output.rejection_details),
                            f"Rejection details: {output.rejection_details}")

    def test_unpack_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "../escape.py": "bad\n",
                "answer.md": "# ok\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-004", target_root=root)
            self.assertGreater(output.files_rejected, 0)
            self.assertIn("Path traversal", str(output.rejection_details))

    def test_unpack_rejects_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                ".git/config": "bad\n",
                "answer.md": "# ok\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-005", target_root=root)
            self.assertGreater(output.files_rejected, 0)
            self.assertTrue(any(".git/" in d for d in output.rejection_details))

    def test_unpack_rejects_zworker_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                ".ai/zworker/runtime/bad": "bad\n",
                "answer.md": "# ok\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-006", target_root=root)
            self.assertGreater(output.files_rejected, 0)

    def test_unpack_rejects_zchat_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                ".ai/zchat/runtime/bad": "bad\n",
                "answer.md": "# ok\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-007", target_root=root)
            self.assertGreater(output.files_rejected, 0)

    def test_unpack_bad_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_zip = root / "bad.zip"
            bad_zip.write_text("not a zip", encoding="utf-8")
            output = jobs.zworker_result_unpack(bad_zip, request_id="TEST-008", target_root=root)
            self.assertEqual(output.status, "failed")
            self.assertIn("Bad ZIP", output.error)

    def test_unpack_nonexistent_zip(self) -> None:
        output = jobs.zworker_result_unpack(Path("/nonexistent/zip.zip"), request_id="TEST-009")
        self.assertEqual(output.status, "failed")
        self.assertIn("ZIP file not found", output.error)

    def test_unpack_does_not_write_to_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "answer.md": "# Answer\n",
                "src/file.py": "print('hello')\n",
            })
            output = jobs.zworker_result_unpack(zip_path, request_id="TEST-010", target_root=root)
            self.assertEqual(output.status, "completed")
            self.assertFalse((root / "src" / "file.py").exists(),
                             "Unpack should NOT write directly to repo root")
            inbox = Path(output.unpack_dir)
            self.assertTrue((inbox / "src" / "file.py").exists())


class ZworkerProcessResultTests(unittest.TestCase):

    def _make_unpack_dir(self, base: Path, request_id: str, files: dict) -> Path:
        inbox = base / "inbox" / request_id
        inbox.mkdir(parents=True, exist_ok=True)
        for rel_path, content in files.items():
            dest = inbox / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        return inbox

    def _make_request_dir(self, base: Path, request_id: str, manifest_overrides: dict | None = None) -> Path:
        req_dir = base / "requests" / request_id
        req_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "request_id": request_id,
            "slug": "test",
            "task_summary": "test",
            "manual_url": "",
            "repo_navigation_url": "",
            "files_to_read": [],
            "strict_zip_contract": False,
            "requires_answer_md": True,
            "created_at": "2026-06-27T12:00:00Z",
            "allowed_paths": ["src/"],
            "forbidden_paths": [],
            "auto_apply_enabled": True,
        }
        if manifest_overrides:
            manifest.update(manifest_overrides)
        (req_dir / "request_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return req_dir

    def test_process_result_with_answer_and_report_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test"
            self._make_request_dir(base, request_id)
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- doc1\n\n"
                    "### Read partially\n- doc2\n\n"
                    "### Not read\n- doc3\n\n"
                    "### External search used\nYes\n\n"
                ),
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.status, "completed")
            self.assertTrue(output.answer_read)
            self.assertTrue(output.sources_report_found)
            self.assertTrue(output.sources_report_valid)
            self.assertEqual(output.decision, "accepted")
            self.assertTrue(output.auto_applied)

    def test_process_result_missing_answer_requires_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test2"
            self._make_request_dir(base, request_id)
            self._make_unpack_dir(base, request_id, {
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertFalse(output.answer_read)
            self.assertTrue(output.requires_revision)
            self.assertFalse(output.auto_applied)
            self.assertIn("answer.md not found", output.human_readable_summary.lower())

    def test_process_result_missing_sources_report_not_hard_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test3"
            self._make_request_dir(base, request_id)
            self._make_unpack_dir(base, request_id, {
                "answer.md": "# Answer\n\nJust an answer, no report.\n",
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.status, "completed")
            self.assertFalse(output.sources_report_found)
            self.assertEqual(output.decision, "accepted")
            self.assertTrue(output.auto_applied)
            self.assertIn("Note", output.human_readable_summary)

    def test_process_result_partial_sources_report_not_hard_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test4"
            self._make_request_dir(base, request_id)
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- doc1\n\n"
                ),
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.status, "completed")
            self.assertFalse(output.sources_report_valid)
            self.assertEqual(output.decision, "accepted")
            self.assertTrue(output.auto_applied)
            self.assertIn("Note", output.human_readable_summary)

    def test_process_result_out_of_scope_files_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test5"
            self._make_request_dir(base, request_id, {"allowed_paths": ["src/"]})
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- doc1\n\n"
                    "### Read partially\n- none\n\n"
                    "### Not read\n- none\n\n"
                    "### External search used\nNo\n\n"
                ),
                "src/file.py": "print('in-scope')\n",
                "secrets/keys.txt": "BAD\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertFalse(output.auto_applied)
            self.assertTrue(output.requires_clarification)
            self.assertEqual(output.repo_files_out_of_scope, 1)

    def test_process_result_auto_applies_in_scope_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test6"
            (base / "src").mkdir(parents=True, exist_ok=True)
            self._make_request_dir(base, request_id, {"allowed_paths": ["src/"]})
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- doc1\n\n"
                    "### Read partially\n- doc2\n\n"
                    "### Not read\n- none\n\n"
                    "### External search used\nNo\n\n"
                ),
                "src/file.py": "print('auto-applied')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertTrue(output.auto_applied)
            self.assertEqual(output.auto_apply_files, 1)
            self.assertTrue((base / "src" / "file.py").exists())
            self.assertIn("print('auto-applied')", (base / "src" / "file.py").read_text())

    def test_process_result_no_request_manifest_default_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test7"
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- doc1\n\n"
                    "### Read partially\n- doc2\n\n"
                    "### Not read\n- doc3\n\n"
                    "### External search used\nNo\n\n"
                ),
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.status, "completed")
            self.assertTrue(output.auto_applied)


class ZworkerRevisionPromptTests(unittest.TestCase):

    def test_revision_prompt_creates_ver2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revisions = base / "revisions"
            revisions.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REVISIONS", base / "revisions"):
                output = jobs.zworker_revision_prompt(
                    "ZWORKER-20260627-120000-test",
                    feedback="Missing answer.md",
                    revision_number=2,
                )
            self.assertEqual(output.status, "completed")
            self.assertEqual(output.revision_name, "ZWORKER-20260627-120000-test-ver2")
            self.assertEqual(output.revision_number, 2)
            self.assertEqual(len(output.artifacts), 2)

            rev_dir = Path(output.revision_dir)
            self.assertTrue(rev_dir.exists())
            self.assertTrue((rev_dir / "revision_prompt.md").exists())
            self.assertTrue((rev_dir / "revision_manifest.json").exists())

    def test_revision_prompt_includes_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revisions = base / "revisions"
            revisions.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REVISIONS", base / "revisions"):
                output = jobs.zworker_revision_prompt(
                    "ZWORKER-20260627-120000-test",
                    feedback="Fix the answer.md",
                    revision_number=2,
                )
            rev_dir = Path(output.revision_dir)
            prompt_text = (rev_dir / "revision_prompt.md").read_text(encoding="utf-8")
            self.assertIn("Fix the answer.md", prompt_text)
            self.assertIn("answer.md", prompt_text)

    def test_revision_prompt_uses_relaxed_sources_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revisions = base / "revisions"
            revisions.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REVISIONS", base / "revisions"):
                output = jobs.zworker_revision_prompt(
                    "ZWORKER-20260627-120000-test",
                    feedback="Fix something",
                    revision_number=2,
                )
            rev_dir = Path(output.revision_dir)
            prompt_text = (rev_dir / "revision_prompt.md").read_text(encoding="utf-8")
            self.assertNotIn("Sources Read Report inside answer.md (REQUIRED)", prompt_text)

    def test_revision_prompt_auto_detects_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revisions = base / "revisions"
            revisions.mkdir(parents=True, exist_ok=True)
            (revisions / "ZWORKER-20260627-120000-test-ver2").mkdir(parents=True, exist_ok=True)
            (revisions / "ZWORKER-20260627-120000-test-ver3").mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REVISIONS", base / "revisions"):
                output = jobs.zworker_revision_prompt(
                    "ZWORKER-20260627-120000-test",
                    feedback="Another revision",
                )
            self.assertEqual(output.revision_number, 4)
            self.assertEqual(output.revision_name, "ZWORKER-20260627-120000-test-ver4")

    def test_revision_prompt_requires_request_id(self) -> None:
        output = jobs.zworker_revision_prompt("", feedback="test")
        self.assertEqual(output.status, "failed")


class ZworkerModeConstantsTests(unittest.TestCase):

    def test_new_mode_constants(self) -> None:
        self.assertEqual(jobs.ZWORKER_MODE_PROMPT_PACK, "zworker_prompt_pack")
        self.assertEqual(jobs.ZWORKER_MODE_RESULT_UNPACK, "zworker_result_unpack")
        self.assertEqual(jobs.ZWORKER_MODE_PROCESS_RESULT, "zworker_process_result")
        self.assertEqual(jobs.ZWORKER_MODE_REVISION_PROMPT, "zworker_revision_prompt")
        self.assertIn(jobs.ZWORKER_MODE_PROMPT_PACK, jobs.ZWORKER_VALID_MODES)
        self.assertIn(jobs.ZWORKER_MODE_RESULT_UNPACK, jobs.ZWORKER_VALID_MODES)
        self.assertIn(jobs.ZWORKER_MODE_PROCESS_RESULT, jobs.ZWORKER_VALID_MODES)
        self.assertIn(jobs.ZWORKER_MODE_REVISION_PROMPT, jobs.ZWORKER_VALID_MODES)


class ZworkerGiTests(unittest.TestCase):

    def test_zworker_request_name_from_jobs(self) -> None:
        name = jobs._zworker_request_name("Test feature")
        self.assertTrue(jobs._zworker_request_name_is_valid(name))

    def test_zworker_revision_name_from_jobs(self) -> None:
        base = "ZWORKER-20260627-120000-test"
        rev = jobs._zworker_revision_name(base, 2)
        self.assertEqual(rev, "ZWORKER-20260627-120000-test-ver2")

    def test_zworker_task_to_slug(self) -> None:
        self.assertEqual(jobs._zworker_task_to_slug("Build login page"), "build-login-page")
        self.assertEqual(jobs._zworker_task_to_slug("  ADD LOGIN Feature  "), "add-login-feature")
        self.assertEqual(jobs._zworker_task_to_slug("Stylish Tetris!"), "stylish-tetris")
        self.assertEqual(jobs._zworker_task_to_slug(""), "task")


if __name__ == "__main__":
    unittest.main()
