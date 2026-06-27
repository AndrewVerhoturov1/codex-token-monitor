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


class ZworkerDocsTests(unittest.TestCase):

    def test_manual_exists(self) -> None:
        manual_path = ROOT / "docs" / "zworker_external_agent_manual.md"
        self.assertTrue(manual_path.exists(), f"Manual not found: {manual_path}")
        content = manual_path.read_text(encoding="utf-8")
        self.assertIn("external agent", content.lower())
        self.assertIn("PACKAGE_READY", content)
        self.assertIn("BLOCKED_MISSING_CONTEXT", content)
        self.assertIn("answer.md", content)

    def test_navigation_exists(self) -> None:
        nav_path = ROOT / "docs" / "zworker_repo_navigation.md"
        self.assertTrue(nav_path.exists(), f"Navigation not found: {nav_path}")
        content = nav_path.read_text(encoding="utf-8")
        self.assertIn("ZWORKER-", content)
        self.assertIn("answer.md", content)

    def test_readme_exists(self) -> None:
        readme_path = ROOT / ".ai" / "zworker" / "readme.md"
        self.assertTrue(readme_path.exists(), f"Readme not found: {readme_path}")
        content = readme_path.read_text(encoding="utf-8")
        self.assertIn("Zworker", content)
        self.assertIn("strict_zip_contract", content)

    def test_prompt_template_exists(self) -> None:
        tmpl = (ROOT / ".ai" / "zworker" / "templates" / "prompt.md")
        self.assertTrue(tmpl.exists(), f"Template not found: {tmpl}")
        content = tmpl.read_text(encoding="utf-8")
        self.assertIn("{request_name}", content)
        self.assertIn("{task}", content)
        self.assertIn("answer.md", content)
        self.assertIn("root_repo_paths", content)

    def test_passport_template_exists(self) -> None:
        tmpl = (ROOT / ".ai" / "zworker" / "templates" / "prompt_passport.md")
        self.assertTrue(tmpl.exists(), f"Template not found: {tmpl}")
        content = tmpl.read_text(encoding="utf-8")
        self.assertIn("{request_name}", content)
        self.assertIn("{task}", content)
        self.assertIn("strict_zip_contract", content)

    def test_request_manifest_template_exists(self) -> None:
        tmpl = (ROOT / ".ai" / "zworker" / "templates" / "request_manifest.json")
        self.assertTrue(tmpl.exists(), f"Template not found: {tmpl}")
        manifest = json.loads(tmpl.read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], "1.0")
        self.assertFalse(manifest["strict_zip_contract"])
        self.assertEqual(manifest["zip_layout"], "root_repo_paths")
        self.assertEqual(manifest["mode"], "zworker_prompt_pack")

    def test_runtime_gitkeep_exists(self) -> None:
        gitkeep = ROOT / ".ai" / "zworker" / "runtime" / ".gitkeep"
        self.assertTrue(gitkeep.exists(), f"Gitkeep not found: {gitkeep}")

    def test_gitignore_covers_zworker_runtime(self) -> None:
        gi = ROOT / ".gitignore"
        content = gi.read_text(encoding="utf-8")
        self.assertIn(".ai/zworker/runtime/", content)


class ZworkerPromptPackTests(unittest.TestCase):

    def test_prompt_pack_creates_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Test task for zworker",
                output_dir=output_dir,
                context="Test context",
                constraints="Test constraint",
                source_urls=["https://example.com/file.py"],
            )
            self.assertEqual(result.status, "completed")
            self.assertTrue(result.request_id)
            self.assertEqual(len(result.artifacts), 3)

            prompt_path = output_dir / "prompt.md"
            passport_path = output_dir / "prompt_passport.md"
            manifest_path = output_dir / "request_manifest.json"

            self.assertTrue(prompt_path.exists())
            self.assertTrue(passport_path.exists())
            self.assertTrue(manifest_path.exists())

    def test_prompt_md_contains_task_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Build login page",
                output_dir=output_dir,
                context="Use React",
                constraints="Follow existing patterns",
            )
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Build login page", prompt_text)
            self.assertIn("Use React", prompt_text)
            self.assertIn("Follow existing patterns", prompt_text)

    def test_prompt_md_contains_required_elements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("external agent", prompt_text.lower())
            self.assertIn("no authority", prompt_text.lower())
            self.assertIn("PACKAGE_READY", prompt_text)
            self.assertIn("BLOCKED_MISSING_CONTEXT", prompt_text)
            self.assertIn("CONTRACT_CONFLICT", prompt_text)
            self.assertIn("answer.md", prompt_text)
            self.assertIn("No ZIP produced.", prompt_text)

    def test_prompt_md_contains_zip_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("root_repo_paths", prompt_text)

    def test_prompt_md_contains_sources_read_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Sources Read Report", prompt_text)

    def test_prompt_md_contains_stop_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Stop-if-Missing", prompt_text)
            self.assertIn("missing from all available sources", prompt_text)

    def test_prompt_passport_contains_request_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Build feature X", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            passport_text = (output_dir / "prompt_passport.md").read_text(encoding="utf-8")
            self.assertIn(result.request_id, passport_text)
            self.assertIn("Build feature X", passport_text)

    def test_request_manifest_strict_zip_contract_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["strict_zip_contract"])
            self.assertEqual(manifest["zip_layout"], "root_repo_paths")

    def test_request_manifest_contains_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                source_urls=["https://example.com/a.py"],
                allowed_paths=["src/"],
                forbidden_paths=["secrets/"],
                expected_outputs=["answer.md", "src/file.py"],
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["manifest_version"], "1.0")
            self.assertEqual(manifest["mode"], "zworker_prompt_pack")
            self.assertEqual(manifest["source_urls"], ["https://example.com/a.py"])
            self.assertEqual(manifest["allowed_paths"], ["src/"])
            self.assertEqual(manifest["forbidden_paths"], ["secrets/"])
            self.assertEqual(manifest["expected_outputs"], ["answer.md", "src/file.py"])
            self.assertIn("request_name", manifest)
            self.assertIn("created_at", manifest)
            self.assertIn("metadata", manifest)

    def test_prompt_pack_with_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                request_id="ZWORKER-20260627-120000-custom-id",
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.request_id, "ZWORKER-20260627-120000-custom-id")

    def test_prompt_pack_source_urls_appear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                source_urls=["https://example.com/file.py", "https://example.com/other.py"],
            )
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("https://example.com/file.py", prompt_text)

    def test_prompt_pack_result_dataclass_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.mode, "zworker_prompt_pack")
            self.assertTrue(result.request_id)
            self.assertTrue(result.output_dir)
            self.assertTrue(len(result.artifacts) > 0)
            self.assertGreater(result.prompt_lines, 0)
            self.assertGreater(result.passport_lines, 0)
            self.assertIn("prompt_pack_ms", result.timings)

    def test_prompt_pack_allowed_forbidden_expected_outputs_string_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                allowed_paths="src/,tests/",
                forbidden_paths="secrets/",
                expected_outputs="answer.md,src/main.py",
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["allowed_paths"], ["src/", "tests/"])
            self.assertEqual(manifest["forbidden_paths"], ["secrets/"])
            self.assertEqual(manifest["expected_outputs"], ["answer.md", "src/main.py"])

    def test_prompt_pack_empty_paths_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                allowed_paths="",
                forbidden_paths="  ,  ",
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["allowed_paths"], [])
            self.assertEqual(manifest["forbidden_paths"], [])

    def test_zworker_mode_constant(self) -> None:
        self.assertEqual(jobs.ZWORKER_MODE_PROMPT_PACK, "zworker_prompt_pack")
        self.assertIn("zworker_prompt_pack", jobs.ZWORKER_VALID_MODES)


class ZworkerBranchMetadataTests(unittest.TestCase):

    def test_prompt_pack_with_source_urls_disables_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task with sources",
                output_dir=output_dir,
                source_urls=["https://example.com/file.py"],
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["branch_may_be_needed"])
            self.assertEqual(manifest["branch_slug_id"], "")
            self.assertEqual(manifest["branch_name"], "")
            self.assertFalse(manifest["create_branch"])
            self.assertEqual(manifest["branch_policy"], "temporary_branch_only_if_public_insufficient")

    def test_prompt_pack_without_source_urls_sets_branch_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task without sources",
                output_dir=output_dir,
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["branch_may_be_needed"])
            self.assertNotEqual(manifest["branch_name"], "")
            self.assertNotEqual(manifest["branch_slug_id"], "")
            if manifest["branch_name"]:
                self.assertIn("zworker/context/", manifest["branch_name"])
                self.assertIn(result.request_id, manifest["branch_name"])
            self.assertFalse(manifest["create_branch"])

    def test_prompt_pack_without_sources_prompt_contains_branch_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task without sources",
                output_dir=output_dir,
            )
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Temporary Context Branch", prompt_text)
            self.assertIn("zworker/context/", prompt_text)
            self.assertIn("temporary_branch_only_if_public_insufficient", prompt_text)
            self.assertIn("create_branch=false", prompt_text.lower())

    def test_prompt_pack_without_sources_passport_contains_branch_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task without sources",
                output_dir=output_dir,
            )
            self.assertEqual(result.status, "completed")
            passport_text = (output_dir / "prompt_passport.md").read_text(encoding="utf-8")
            self.assertIn("Temporary Context Branch", passport_text)
            self.assertIn("zworker/context/", passport_text)

    def test_prompt_pack_with_sources_prompt_has_no_branch_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task with sources",
                output_dir=output_dir,
                source_urls=["https://example.com/file.py"],
            )
            self.assertEqual(result.status, "completed")
            prompt_text = (output_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("No temporary context branch is needed", prompt_text)

    def test_request_manifest_contains_all_branch_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                source_urls=["https://example.com/a.py"],
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("branch_policy", manifest)
            self.assertIn("branch_may_be_needed", manifest)
            self.assertIn("create_branch", manifest)
            self.assertIn("branch_slug_id", manifest)
            self.assertIn("branch_name", manifest)

    def test_manifest_metadata_contains_branch_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            metadata = manifest.get("metadata", {})
            self.assertIn("branch_may_be_needed", metadata)
            self.assertIn("create_branch", metadata)
            self.assertIn("branch_slug_id", metadata)
            self.assertIn("branch_name", metadata)
            self.assertTrue(metadata["branch_may_be_needed"])
            self.assertFalse(metadata["create_branch"])

    def test_resolve_branch_decision_no_sources(self) -> None:
        decision = _git_utils_module.resolve_branch_decision(source_urls=None)
        self.assertEqual(decision["decision"], "branch_may_be_needed")
        self.assertFalse(decision["create_branch"])

    def test_resolve_branch_decision_empty_sources(self) -> None:
        decision = _git_utils_module.resolve_branch_decision(source_urls=[])
        self.assertEqual(decision["decision"], "branch_may_be_needed")

    def test_resolve_branch_decision_with_sources(self) -> None:
        decision = _git_utils_module.resolve_branch_decision(
            source_urls=["https://example.com/file.py"]
        )
        self.assertEqual(decision["decision"], "no_branch_needed")

    def test_resolve_branch_decision_public_context(self) -> None:
        decision = _git_utils_module.resolve_branch_decision(
            has_public_github_context=True
        )
        self.assertEqual(decision["decision"], "no_branch_needed")

    def test_zworker_context_branch_name(self) -> None:
        name = _git_utils_module.zworker_context_branch_name("ZWORKER-20260627-120000-test")
        self.assertEqual(name, "zworker/context/ZWORKER-20260627-120000-test")


class ZworkerGiTests(unittest.TestCase):

    def test_zworker_request_name_is_valid_from_jobs(self) -> None:
        name = jobs._zworker_request_name("Test feature")
        self.assertTrue(jobs._zworker_request_name_is_valid(name))

    def test_zworker_revision_name_from_jobs(self) -> None:
        base = "ZWORKER-20260627-120000-test"
        rev = jobs._zworker_revision_name(base, 2)
        self.assertEqual(rev, "ZWORKER-20260627-120000-test-ver2")


class ZworkerStage2UnpackTests(unittest.TestCase):

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
                "answer.md": "# Answer\n\nSources Read Report: yes\n",
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


class ZworkerStage2ProcessResultTests(unittest.TestCase):

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
            "manifest_version": "1.0",
            "request_name": request_id,
            "request_id": request_id,
            "created_at": "2026-06-27T12:00:00Z",
            "mode": "zworker_prompt_pack",
            "strict_zip_contract": False,
            "zip_layout": "root_repo_paths",
            "allowed_paths": ["src/"],
            "forbidden_paths": [],
            "auto_apply_enabled": True,
        }
        if manifest_overrides:
            manifest.update(manifest_overrides)
        (req_dir / "request_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return req_dir

    def test_process_result_reads_answer_first(self) -> None:
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

    def test_process_result_requires_sources_read_report_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test2"
            self._make_request_dir(base, request_id)
            self._make_unpack_dir(base, request_id, {
                "answer.md": "# Answer\n\nJust an answer, no report.\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertFalse(output.sources_report_found)
            self.assertTrue(output.requires_revision)
            self.assertEqual(output.decision, "needs_revision")

    def test_process_result_blocks_out_of_scope_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test3"
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
            request_id = "ZWORKER-20260627-120000-test4"
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

    def test_process_result_missing_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test5"
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

    def test_process_result_partial_sources_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260627-120000-test6"
            self._make_request_dir(base, request_id)
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- doc1\n\n"
                    "# Missing Read partially and Not read sections\n"
                ),
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertFalse(output.sources_report_valid)
            self.assertTrue(output.requires_revision)

    def test_process_result_no_request_manifest(self) -> None:
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


class ZworkerStage2RevisionPromptTests(unittest.TestCase):

    def test_revision_prompt_creates_ver2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revisions = base / "revisions"
            revisions.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REVISIONS", base / "revisions"):
                output = jobs.zworker_revision_prompt(
                    "ZWORKER-20260627-120000-test",
                    feedback="Missing Sources Read Report",
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
                    feedback="Fix the Sources Read Report",
                    revision_number=2,
                )
            rev_dir = Path(output.revision_dir)
            prompt_text = (rev_dir / "revision_prompt.md").read_text(encoding="utf-8")
            self.assertIn("Fix the Sources Read Report", prompt_text)
            self.assertIn("answer.md", prompt_text)
            self.assertIn("Sources Read Report", prompt_text)

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


class ZworkerStage2ModeConstantsTests(unittest.TestCase):

    def test_new_mode_constants(self) -> None:
        self.assertEqual(jobs.ZWORKER_MODE_RESULT_UNPACK, "zworker_result_unpack")
        self.assertEqual(jobs.ZWORKER_MODE_PROCESS_RESULT, "zworker_process_result")
        self.assertEqual(jobs.ZWORKER_MODE_REVISION_PROMPT, "zworker_revision_prompt")
        self.assertIn(jobs.ZWORKER_MODE_RESULT_UNPACK, jobs.ZWORKER_VALID_MODES)
        self.assertIn(jobs.ZWORKER_MODE_PROCESS_RESULT, jobs.ZWORKER_VALID_MODES)
        self.assertIn(jobs.ZWORKER_MODE_REVISION_PROMPT, jobs.ZWORKER_VALID_MODES)


if __name__ == "__main__":
    unittest.main()
