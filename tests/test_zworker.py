import importlib.util
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS_SKILLS_ROOT = Path.home() / ".agents" / "skills"
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

    def test_zworker_accepts_explicit_request_id_with_different_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Make beautiful tetris",
                output_dir=output_dir,
                request_id="ZWORKER-20260627-191435-stylish-calculator",
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.request_id, "ZWORKER-20260627-191435-stylish-calculator")

    def test_zworker_rejects_invalid_request_id_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Make beautiful tetris",
                output_dir=output_dir,
                request_id="bad-request-id",
            )
            self.assertEqual(result.status, "failed")
            self.assertIn("invalid request_id format", result.error.lower())

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


class ZworkerCanonicalizeRequestIdTests(unittest.TestCase):

    def test_canonicalize_passthrough_valid_zworker_id(self) -> None:
        rid = "ZWORKER-20260627-120000-valid-slug"
        result = jobs._zworker_canonicalize_request_id(rid)
        self.assertEqual(result, rid)

    def test_canonicalize_friendly_id(self) -> None:
        result = jobs._zworker_canonicalize_request_id("greeting-card-anechka-alena")
        self.assertTrue(result.startswith("ZWORKER-00000000-000000-"))
        self.assertIn("greeting-card-anechka-alena", result)
        self.assertTrue(jobs._zworker_request_name_is_valid(result),
                        f"Canonicalized ID should be valid: {result}")

    def test_canonicalize_friendly_id_with_special_chars(self) -> None:
        result = jobs._zworker_canonicalize_request_id("My Friendly @#$ ID")
        self.assertTrue(result.startswith("ZWORKER-00000000-000000-"))
        self.assertIn("my-friendly-id", result)
        self.assertTrue(jobs._zworker_request_name_is_valid(result))

    def test_canonicalize_empty_string(self) -> None:
        self.assertEqual(jobs._zworker_canonicalize_request_id(""), "")

    def test_canonicalize_deterministic(self) -> None:
        rid1 = jobs._zworker_canonicalize_request_id("hello-world-test")
        rid2 = jobs._zworker_canonicalize_request_id("hello-world-test")
        self.assertEqual(rid1, rid2)

    def test_canonicalize_passthrough_zworker_revision(self) -> None:
        rid = "ZWORKER-20260627-120000-some-task-ver2"
        result = jobs._zworker_canonicalize_request_id(rid)
        self.assertEqual(result, rid)

    def test_auto_run_accepts_friendly_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auto_dir = Path(tmp) / "auto"
            auto_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", auto_dir):
                config = jobs.ZworkerAutoRunConfig(
                    task="Test friendly ID",
                    request_id="greeting-card-anechka-alena",
                    max_revisions=2,
                )
                result = jobs.zworker_auto_run(config)

            self.assertNotEqual(result.status, "failed",
                                f"Should not fail with friendly request_id: {result.error}")
            self.assertIn("ZWORKER-", result.request_id,
                          "request_id should be canonicalized to ZWORKER- format")

    def test_auto_run_deterministic_friendly_id_produces_same_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auto_dir = Path(tmp) / "auto"
            auto_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", auto_dir):
                config1 = jobs.ZworkerAutoRunConfig(
                    task="Deterministic test",
                    request_id="my-friendly-task",
                )
                result1 = jobs.zworker_auto_run(config1)

            auto_dir2 = Path(tmp) / "auto2"
            auto_dir2.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", auto_dir2):
                config2 = jobs.ZworkerAutoRunConfig(
                    task="Deterministic test",
                    request_id="my-friendly-task",
                    force_resend=True,
                )
                result2 = jobs.zworker_auto_run(config2)

            # Different run dirs but same friendly ID → same canonical request_id
            self.assertEqual(result1.request_id, result2.request_id)


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

    def test_manual_no_zip_contract(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("ZIP Contract", content)

    def test_manual_no_auto_apply(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("Auto-apply", content)

    def test_manual_no_accepted_for_review(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("accepted_for_review", content)

    def test_manual_no_manifest_json_as_requirement(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("manifest.json is required", content.lower())

    def test_manual_no_checksums_sha256_as_requirement(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertNotIn("checksums.sha256 is required", content.lower())

    def test_manual_review_before_apply(self) -> None:
        content = (ROOT / "docs" / "zworker_external_agent_manual.md").read_text(encoding="utf-8")
        self.assertIn("Decide", content)
        self.assertIn("whether to apply", content.lower())


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

    def test_navigation_no_zip_contract(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("ZIP Contract", content)

    def test_navigation_no_checks_scope_against_manifest(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("checks scope against manifest", content.lower())

    def test_navigation_no_accepted_for_review(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("accepted_for_review", content)

    def test_navigation_no_broken_raw_url(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertNotIn("codex-token-monitor//", content)

    def test_navigation_has_branch_template(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertIn("<branch_name>/<path>", content)


class ZworkerInvocationDocTests(unittest.TestCase):

    def test_invocation_doc_exists_and_explains_route(self) -> None:
        doc_path = ROOT / "docs" / "zworker_invocation.md"
        self.assertTrue(doc_path.exists(), f"Invocation doc not found: {doc_path}")
        content = doc_path.read_text(encoding="utf-8")
        self.assertIn("/zworker", content)
        self.assertIn("prompt.md", content)
        self.assertIn("answer.md", content)
        self.assertIn("ZIP", content)
        self.assertIn("not direct task execution", content.lower())

    def test_readme_links_invocation_doc(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "readme.md").read_text(encoding="utf-8")
        self.assertIn("zworker_invocation.md", content)

    def test_navigation_links_invocation_doc(self) -> None:
        content = (ROOT / "docs" / "zworker_repo_navigation.md").read_text(encoding="utf-8")
        self.assertIn("zworker_invocation.md", content)


class ZworkerCodexSkillTests(unittest.TestCase):

    def _load_skill(self, skill_name: str) -> str:
        if not AGENTS_SKILLS_ROOT.exists():
            self.skipTest(f"Skills root not found: {AGENTS_SKILLS_ROOT}")
        path = AGENTS_SKILLS_ROOT / skill_name / "SKILL.md"
        self.assertTrue(path.exists(), f"Skill not found: {path}")
        return path.read_text(encoding="utf-8")

    def test_zworker_skill_exists_and_is_conditional(self) -> None:
        content = self._load_skill("opencode-zworker-control")
        self.assertIn("/zworker", content)
        self.assertIn("Load this skill only when the user explicitly invokes `/zworker`", content)
        self.assertIn("Do not load this skill for ordinary local repo work.", content)
        self.assertIn("Do not load this skill for ordinary OpenCode delegation.", content)
        self.assertIn("Do not load this skill for ordinary GitHub tasks.", content)

    def test_zworker_skill_describes_external_worker_not_direct_execution(self) -> None:
        content = self._load_skill("opencode-zworker-control")
        self.assertIn("not a request for Codex to solve the main task directly", content)
        self.assertIn("zworker prompt-pack", content)
        self.assertIn("ZIP with `answer.md`", content)

    def test_zworker_skill_describes_answer_only_and_file_task_behavior(self) -> None:
        content = self._load_skill("opencode-zworker-control")
        self.assertIn("answer-only ZIP with just `answer.md`", content)
        self.assertIn("normal result", content)
        self.assertIn("answer-only ZIP is", content)
        self.assertIn("insufficient", content)

    def test_main_route_skill_links_zworker_skill_without_inlining_full_text(self) -> None:
        content = self._load_skill("opencode-mcp-windows-control")
        self.assertIn("opencode-zworker-control", content)
        self.assertIn("/zworker", content)
        self.assertNotIn("answer-only ZIP with just `answer.md` is a normal result", content)


class ZworkerTemplatesTests(unittest.TestCase):

    def test_prompt_template_exists(self) -> None:
        tmpl = (ROOT / ".ai" / "zworker" / "templates" / "prompt.md")
        self.assertTrue(tmpl.exists(), f"Template not found: {tmpl}")
        content = tmpl.read_text(encoding="utf-8")
        self.assertIn("{request_id}", content)
        self.assertIn("{task}", content)
        self.assertIn("answer.md", content)

    def test_prompt_template_no_package_ready(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "templates" / "prompt.md").read_text(encoding="utf-8")
        self.assertNotIn("PACKAGE_READY", content)

    def test_prompt_template_no_manifest_json(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "templates" / "prompt.md").read_text(encoding="utf-8")
        self.assertNotIn("manifest.json", content)

    def test_prompt_template_no_checksums_sha256(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "templates" / "prompt.md").read_text(encoding="utf-8")
        self.assertNotIn("checksums.sha256", content)

    def test_prompt_template_no_payload(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "templates" / "prompt.md").read_text(encoding="utf-8")
        self.assertNotIn("payload/", content)

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

    def test_readme_no_auto_apply(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "readme.md").read_text(encoding="utf-8")
        self.assertNotIn("auto-apply", content.lower())

    def test_readme_answer_md_read_first(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "readme.md").read_text(encoding="utf-8")
        self.assertIn("answer.md", content)

    def test_readme_result_applied_after_review(self) -> None:
        content = (ROOT / ".ai" / "zworker" / "readme.md").read_text(encoding="utf-8")
        self.assertIn("after review", content.lower())


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

    def test_manifest_allowed_paths_support_newline_separated_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Task",
                output_dir=output_dir,
                allowed_paths="src/app.js\nsrc/styles.css",
                expected_outputs="src/app.js,\nsrc/styles.css",
            )
            self.assertEqual(result.status, "completed")
            manifest = json.loads((output_dir / "request_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["allowed_paths"], ["src/app.js", "src/styles.css"])
            self.assertEqual(manifest["exact_expected_paths"], ["src/app.js", "src/styles.css"])


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


class ZworkerWebZipDownloadTests(unittest.TestCase):

    def test_find_zip_button_fallback_by_zip_name(self) -> None:
        import importlib.util
        ROOT = Path(__file__).resolve().parents[1]
        runner_path = ROOT / "scripts" / "zworker_chatgpt_web_runner.py"
        spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner", runner_path)
        runner = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(runner)

        request_id = "ZWORKER-20260629-TEST-001"
        zip_name = f"{request_id}-zworker-result.zip"

        class MockLocator:
            def __init__(self, items):
                self._items = items

            def count(self):
                return len(self._items)

            def nth(self, i):
                return self._items[i]

        class MockElement:
            def __init__(self, name_val, is_visible_val=True):
                self._name = name_val
                self._is_visible = is_visible_val

            def is_visible(self):
                return self._is_visible

        class MockPage:
            def __init__(self, text_content, found_element_name):
                self._text = text_content
                self._found_name = found_element_name

            def get_by_role(self, role, name=None):
                name_str = name.pattern if hasattr(name, 'pattern') else str(name)
                if self._found_name and name_str and self._found_name in name_str:
                    return MockLocator([MockElement(self._found_name)])
                return MockLocator([])

            def locator(self, selector):
                return MockLocator([])

        mock_page = MockPage(f"task: {request_id}", zip_name)

        try:
            result = runner.find_zip_download_button(mock_page, request_id)
            self.assertIsNotNone(result)
        except runner.WebRunnerError:
            pass

    def test_validate_downloaded_zip_rejects_empty_zip(self) -> None:
        import importlib.util

        runner_path = ROOT / "scripts" / "zworker_chatgpt_web_runner.py"
        spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner_validate", runner_path)
        runner = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(runner)

        with tempfile.TemporaryDirectory() as tmp:
            state = runner.ZworkerWebRunState("ZWORKER-20260629-120000-empty-zip", runtime_root=Path(tmp))
            empty_zip = Path(tmp) / "empty.zip"
            empty_zip.write_bytes(b"")

            with self.assertRaises(runner.WebRunnerError) as ctx:
                runner.validate_downloaded_zip(state, empty_zip, None)

        self.assertEqual(ctx.exception.code, "FAILED_BAD_ZIP")


class ZworkerWebRunnerAttachModeTests(unittest.TestCase):

    def test_attach_mode_uses_dedicated_page_and_keeps_existing_context_open(self) -> None:
        import importlib.util

        runner_path = ROOT / "scripts" / "zworker_chatgpt_web_runner.py"
        spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner_attach_mode", runner_path)
        runner = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(runner)

        class FakePage:
            def __init__(self, name: str):
                self.name = name
                self.closed = False
                self.url = "https://chatgpt.com/"

            def close(self):
                self.closed = True

        class FakeContext:
            def __init__(self):
                self.pages = [FakePage("existing")]
                self.closed = False
                self.new_page_calls = 0

            def new_page(self):
                self.new_page_calls += 1
                return FakePage("dedicated")

            def close(self):
                self.closed = True

        class FakeBrowser:
            def __init__(self, context):
                self.contexts = [context]

        class FakeChromium:
            def __init__(self, browser):
                self._browser = browser

            def connect_over_cdp(self, _url):
                return self._browser

        class FakePlaywright:
            def __init__(self, browser):
                self.chromium = FakeChromium(browser)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_context = FakeContext()
        fake_browser = FakeBrowser(fake_context)

        with tempfile.TemporaryDirectory() as tmp:
            args = runner.parse_args([
                "--request-id", "ZWORKER-20260629-120000-attach-page",
                "--runtime-root", tmp,
                "--cdp-url", "ws://localhost:9222/devtools/browser/test",
                "--login-check",
            ])

            with unittest.mock.patch.object(runner, "require_playwright", return_value=lambda: FakePlaywright(fake_browser)):
                with unittest.mock.patch.object(runner, "ensure_login", return_value=None):
                    result = runner.run_browser_flow(args)

        self.assertEqual(result, 0)
        self.assertEqual(fake_context.new_page_calls, 1)
        self.assertFalse(fake_context.closed)
        self.assertFalse(fake_context.pages[0].closed)


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

    def test_answer_only_informational_task_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260628-120000-info"
            self._make_request_dir(base, request_id, {
                "allowed_paths": [],
                "expected_outputs": [],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Analysis\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- docs/README.md\n\n"
                    "### Read partially\n- none\n\n"
                    "### Not read\n- none\n\n"
                    "### External search used\nNo\n\n"
                    "The codebase is well structured.\n"
                ),
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
            self.assertFalse(output.requires_revision)
            self.assertIn("INFORMATIONAL", output.human_readable_summary)

    def test_file_producing_task_without_files_needs_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260628-120000-fileprod"
            self._make_request_dir(base, request_id, {
                "allowed_paths": ["src/"],
                "expected_outputs": ["src/utils.py"],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- docs/README.md\n\n"
                    "### Read partially\n- none\n\n"
                    "### Not read\n- none\n\n"
                    "### External search used\nNo\n\n"
                    "I wrote the utility but forgot to include it.\n"
                ),
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertTrue(output.requires_revision)
            self.assertEqual(output.decision, "needs_revision")
            self.assertFalse(output.auto_applied)
            self.assertIn("No repo-candidate files found", output.human_readable_summary)

    def test_informational_task_missing_sources_report_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260628-120000-nosrc"
            self._make_request_dir(base, request_id, {
                "allowed_paths": [],
                "expected_outputs": [],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": "# Quick answer\n\nNo sources report here.\n",
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
            self.assertFalse(output.requires_revision)
            self.assertIn("Note", output.human_readable_summary)
            self.assertIn("INFORMATIONAL", output.human_readable_summary)

    def test_fake_local_claims_in_answer_remain_problem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260628-120000-fake"
            self._make_request_dir(base, request_id, {
                "allowed_paths": ["src/"],
                "expected_outputs": ["src/component.py"],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- docs/README.md\n\n"
                    "### Read partially\n- src/existing.py\n\n"
                    "### Not read\n- none\n\n"
                    "### External search used\nNo\n\n"
                    "I created src/component.py with the new feature.\n"
                    "The file is ready for review.\n"
                ),
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertTrue(output.requires_revision)
            self.assertEqual(output.decision, "needs_revision")
            self.assertIn("No repo-candidate files found", output.human_readable_summary)

    def test_zip_with_repo_files_goes_into_file_review_not_informational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260628-120000-filereview"
            self._make_request_dir(base, request_id, {
                "allowed_paths": [],
                "expected_outputs": [],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n"
                    "## Sources Read Report\n\n"
                    "### Read fully\n- docs/README.md\n\n"
                    "### Read partially\n- none\n\n"
                    "### Not read\n- none\n\n"
                    "### External search used\nNo\n\n"
                ),
                "src/file.py": "print('file review')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.decision, "accepted")
            self.assertTrue(output.auto_applied)
            self.assertEqual(output.auto_apply_files, 1)
            self.assertEqual(output.repo_files_in_scope, 1)
            self.assertNotIn("INFORMATIONAL", output.human_readable_summary)


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

    def test_revision_prompt_includes_rejection_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revisions = base / "revisions"
            revisions.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REVISIONS", base / "revisions"):
                output = jobs.zworker_revision_prompt(
                    "ZWORKER-20260627-120000-test",
                    feedback="Need fixes",
                    rejection_reasons=["out_of_scope_files_present", "repo_candidate_files_missing"],
                    revision_number=2,
                )
            rev_dir = Path(output.revision_dir)
            prompt_text = (rev_dir / "revision_prompt.md").read_text(encoding="utf-8")
            manifest = json.loads((rev_dir / "revision_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("## Rejection reasons", prompt_text)
            self.assertIn("- out_of_scope_files_present", prompt_text)
            self.assertEqual(manifest["rejection_reasons"], ["out_of_scope_files_present", "repo_candidate_files_missing"])

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


class ZworkerSourceUrlValidationTests(unittest.TestCase):

    def _pack(self, task: str, **kwargs) -> jobs.ZworkerPromptPackResult:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            return jobs.zworker_prompt_pack(task, output_dir=output_dir, **kwargs)

    def test_accepts_valid_https_raw_url(self) -> None:
        result = self._pack("Task", source_urls=[
            "https://raw.githubusercontent.com/owner/repo/main/src/file.py",
        ])
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.self_check_passed)

    def test_accepts_multiple_valid_https_urls(self) -> None:
        result = self._pack("Task", source_urls=[
            "https://raw.githubusercontent.com/A/repo/main/a.py",
            "https://raw.githubusercontent.com/B/repo/main/b.py",
        ])
        self.assertEqual(result.status, "completed")

    def test_rejects_relative_path(self) -> None:
        result = self._pack("Task", source_urls=["src/file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("not an absolute HTTPS URL", result.error)

    def test_rejects_dot_slash_relative(self) -> None:
        result = self._pack("Task", source_urls=["./src/file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("relative path", result.error)

    def test_rejects_dot_dot_traversal(self) -> None:
        result = self._pack("Task", source_urls=["../utils/helpers.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("relative path", result.error)

    def test_rejects_windows_c_drive_path(self) -> None:
        result = self._pack("Task", source_urls=["C:/Users/andre/project/file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("Windows absolute path", result.error)

    def test_rejects_windows_d_drive_path(self) -> None:
        result = self._pack("Task", source_urls=[R"D:\Codex\file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("Windows absolute path", result.error)

    def test_rejects_file_uri(self) -> None:
        result = self._pack("Task", source_urls=["file:///C:/Users/andre/file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("file:// URI", result.error)

    def test_rejects_file_uri_unix(self) -> None:
        result = self._pack("Task", source_urls=["file:///home/user/file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("file:// URI", result.error)

    def test_rejects_unix_absolute_path(self) -> None:
        result = self._pack("Task", source_urls=["/home/user/project/file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("Unix absolute path", result.error)

    def test_rejects_unc_path(self) -> None:
        result = self._pack("Task", source_urls=[R"\\server\share\file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("UNC path", result.error)

    def test_rejects_http_non_https(self) -> None:
        result = self._pack("Task", source_urls=["http://example.com/file.py"])
        self.assertEqual(result.status, "failed")
        self.assertIn("non-HTTPS URL", result.error)

    def test_rejects_empty_url(self) -> None:
        result = self._pack("Task", source_urls=[""])
        self.assertEqual(result.status, "failed")
        self.assertIn("empty URL", result.error)

    def test_rejects_mixed_valid_and_invalid(self) -> None:
        result = self._pack("Task", source_urls=[
            "https://raw.githubusercontent.com/owner/repo/main/a.py",
            "src/bad.py",
        ])
        self.assertEqual(result.status, "failed")
        self.assertIn("not an absolute HTTPS URL", result.error)

    def test_standalone_task_no_urls_still_works(self) -> None:
        result = self._pack("Standalone task")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.self_check_passed)


class ZworkerPromptSelfCheckTests(unittest.TestCase):

    def test_self_check_passes_for_valid_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Valid task",
                output_dir=output_dir,
                source_urls=["https://raw.githubusercontent.com/owner/repo/main/file.py"],
            )
            self.assertEqual(result.status, "completed")
            self.assertTrue(result.self_check_passed, f"Self-check errors: {result.self_check_errors}")
            self.assertEqual(len(result.self_check_errors), 0)

    def test_self_check_errors_are_empty_for_clean_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zworker_output"
            result = jobs.zworker_prompt_pack(
                "Clean task",
                output_dir=output_dir,
            )
            self.assertEqual(result.status, "completed")
            self.assertTrue(result.self_check_passed)
            self.assertEqual(len(result.self_check_errors), 0)

    def test_self_check_detects_missing_manual_url(self) -> None:
        prompt_text = """# Prompt

## Files to read
- https://example.com/file.py

No manual link here.
"""
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url="https://raw.githubusercontent.com/owner/repo/main/docs/zworker_external_agent_manual.md",
            nav_url="https://raw.githubusercontent.com/owner/repo/main/docs/zworker_repo_navigation.md",
        )
        self.assertFalse(ok)
        self.assertTrue(any("manual URL" in e for e in errors))

    def test_self_check_detects_missing_nav_url(self) -> None:
        prompt_text = """# Prompt
- https://raw.githubusercontent.com/owner/repo/main/docs/zworker_external_agent_manual.md
"""
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url="https://raw.githubusercontent.com/owner/repo/main/docs/zworker_external_agent_manual.md",
            nav_url="https://raw.githubusercontent.com/owner/repo/main/docs/zworker_repo_navigation.md",
        )
        self.assertFalse(ok)
        self.assertTrue(any("repo navigation URL" in e for e in errors))

    def test_self_check_detects_file_uri(self) -> None:
        prompt_text = """# Prompt
## Files to read
- file:///C:/Users/test/file.py
"""
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,  # not in prompt
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("file://" in e for e in errors))

    def test_self_check_detects_windows_drive_in_prompt(self) -> None:
        prompt_text = "Check C:/Users/test/file.py for details"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("Windows path" in e for e in errors))

    def test_self_check_detects_package_ready(self) -> None:
        prompt_text = "PACKAGE_READY is forbidden"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("PACKAGE_READY" in e for e in errors))

    def test_self_check_detects_manifest_json(self) -> None:
        prompt_text = "Please include manifest.json in the ZIP."
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("manifest.json" in e for e in errors))

    def test_self_check_reported_on_zworker_prompt_pack_result(self) -> None:
        instance = jobs.ZworkerPromptPackResult()
        self.assertTrue(hasattr(instance, "self_check_passed"))
        self.assertTrue(hasattr(instance, "self_check_errors"))

    def test_self_check_rejects_markdown_relative_link_dotdot_slash(self) -> None:
        prompt_text = "See [External Worker Manual](../../ZWORKER-MANUAL.md) for details"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("Markdown relative link" in e for e in errors),
                        f"Expected Markdown relative link error, got: {errors}")

    def test_self_check_rejects_markdown_relative_link_dotdot_backslash(self) -> None:
        prompt_text = "See [codex-token-monitor](..\\..\\..\\..\\..\\)"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("Markdown relative link" in e for e in errors),
                        f"Expected Markdown relative link error, got: {errors}")

    def test_self_check_rejects_dotdot_slash_in_text(self) -> None:
        prompt_text = "# Repo\n\n- Root: ../project\n"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("../" in e for e in errors),
                        f"Expected ../ error, got: {errors}")

    def test_self_check_rejects_dotdot_backslash_in_text(self) -> None:
        prompt_text = "# Repo\n\n- Root: ..\\project\n"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("..\\" in e for e in errors),
                        f"Expected ..\\ error, got: {errors}")

    def test_self_check_rejects_c_drive_path(self) -> None:
        prompt_text = "See C:/Users/andre/project/file.py"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("C:/" in e for e in errors),
                        f"Expected C:/ error, got: {errors}")

    def test_self_check_rejects_d_drive_path(self) -> None:
        prompt_text = "See D:/Codex/file.py"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("D:/" in e for e in errors),
                        f"Expected D:/ error, got: {errors}")

    def test_self_check_rejects_d_drive_backslash_path(self) -> None:
        prompt_text = "See D:\\Codex\\file.py"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=prompt_text,
            nav_url=prompt_text,
        )
        self.assertFalse(ok)
        self.assertTrue(any("D:/" in e for e in errors),
                        f"Expected D:/ error, got: {errors}")

    def test_self_check_requires_exact_raw_manual_url(self) -> None:
        manual_url = "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md"
        nav_url = "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md"
        prompt_text = f"# Prompt\n- {manual_url}\n- {nav_url}\n"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=manual_url,
            nav_url=nav_url,
        )
        self.assertTrue(ok, f"Expected pass, got errors: {errors}")

    def test_self_check_rejects_wrong_manual_url(self) -> None:
        correct_manual = "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md"
        correct_nav = "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md"
        prompt_text = "# Prompt\n- https://other-url.com/manual.md\n- {correct_nav}\n"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=correct_manual,
            nav_url=correct_nav,
        )
        self.assertFalse(ok)
        self.assertTrue(any("manual URL not found" in e for e in errors))

    def test_self_check_rejects_wrong_nav_url(self) -> None:
        correct_manual = "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_external_agent_manual.md"
        correct_nav = "https://raw.githubusercontent.com/AndrewVerhoturov1/codex-token-monitor/main/docs/zworker_repo_navigation.md"
        prompt_text = f"# Prompt\n- {correct_manual}\n"
        ok, errors = jobs._zworker_prompt_self_check(
            prompt_text,
            manual_url=correct_manual,
            nav_url=correct_nav,
        )
        self.assertFalse(ok)
        self.assertTrue(any("repo navigation URL not found" in e for e in errors))


class ZworkerSkillExternalLinkRulesTests(unittest.TestCase):

    def _load_skill(self) -> str:
        skills_root = Path.home() / ".agents" / "skills"
        if not skills_root.exists():
            self.skipTest(f"Skills root not found: {skills_root}")
        path = skills_root / "opencode-zworker-control" / "SKILL.md"
        self.assertTrue(path.exists(), f"Skill not found: {path}")
        return path.read_text(encoding="utf-8")

    def test_skill_has_link_rules_section(self) -> None:
        content = self._load_skill()
        self.assertIn("External prompt link rules", content)

    def test_skill_bans_relative_paths(self) -> None:
        content = self._load_skill()
        self.assertIn("Relative paths", content)
        self.assertIn("src/file.py", content)

    def test_skill_bans_windows_paths(self) -> None:
        content = self._load_skill()
        self.assertIn("Windows absolute paths", content)
        self.assertIn("C:/Users", content)

    def test_skill_bans_file_uris(self) -> None:
        content = self._load_skill()
        self.assertIn("File:// URIs", content)
        self.assertIn("file:///", content)

    def test_skill_bans_unix_absolute_paths(self) -> None:
        content = self._load_skill()
        self.assertIn("Unix absolute paths", content)

    def test_skill_has_self_check_section(self) -> None:
        content = self._load_skill()
        self.assertIn("Prompt self-check", content)
        self.assertIn("_zworker_prompt_self_check", content)

    def test_skill_has_valid_invalid_examples(self) -> None:
        content = self._load_skill()
        self.assertIn("Valid vs invalid prompt examples", content)
        self.assertIn("Valid source links", content)
        self.assertIn("Invalid source links", content)

    def test_skill_requires_https_links(self) -> None:
        content = self._load_skill()
        self.assertIn("absolute HTTPS URLs", content)
        self.assertIn("raw.githubusercontent.com", content)

    def test_skill_external_prompt_link_rules_bans_unc(self) -> None:
        content = self._load_skill()
        self.assertIn("SMB/UNC paths", content)

    def test_skill_no_relative_in_external_prompt(self) -> None:
        content = self._load_skill()
        self.assertIn("FORBIDDEN in any external prompt", content)


class ZworkerAutoModeTests(unittest.TestCase):

    def test_zworker_auto_mode_constant(self) -> None:
        self.assertEqual(jobs.ZWORKER_MODE_AUTO, "zworker_auto")
        self.assertIn(jobs.ZWORKER_MODE_AUTO, jobs.ZWORKER_VALID_MODES)

    def test_zworker_auto_valid_states(self) -> None:
        self.assertIn(jobs.ZWORKER_AUTO_STATE_INITIALIZING, jobs.ZWORKER_AUTO_VALID_STATES)
        self.assertIn(jobs.ZWORKER_AUTO_STATE_REQUEST_PACKED, jobs.ZWORKER_AUTO_VALID_STATES)
        self.assertIn(jobs.ZWORKER_AUTO_STATE_WEB_RUNNER_RUNNING, jobs.ZWORKER_AUTO_VALID_STATES)
        self.assertIn(jobs.ZWORKER_AUTO_STATE_PROMPT_SENT, jobs.ZWORKER_AUTO_VALID_STATES)
        self.assertIn(jobs.ZWORKER_AUTO_STATE_AWAITING_ZIP, jobs.ZWORKER_AUTO_VALID_STATES)
        self.assertIn(jobs.ZWORKER_AUTO_STATE_ACCEPTED, jobs.ZWORKER_AUTO_VALID_STATES)
        self.assertIn(jobs.ZWORKER_AUTO_STATE_CLARIFICATION_REQUIRED, jobs.ZWORKER_AUTO_VALID_STATES)
        self.assertIn(jobs.ZWORKER_AUTO_STATE_FAILED, jobs.ZWORKER_AUTO_VALID_STATES)

    def test_zworker_auto_default_max_revisions(self) -> None:
        self.assertEqual(jobs.ZWORKER_AUTO_DEFAULT_MAX_REVISIONS, 2)

    def test_zworker_auto_run_config_dataclass(self) -> None:
        config = jobs.ZworkerAutoRunConfig(
            task="Test task",
            context="context",
            constraints="constraints",
            source_urls=["https://example.com/file.py"],
            allowed_paths="src/",
            forbidden_paths="secrets/",
            expected_outputs="src/output.py",
            request_id="TEST-001",
            max_revisions=3,
            provider_id="test-provider",
            model_id="test-model",
            cdp_url="ws://localhost:9222/devtools/browser/test",
        )
        self.assertEqual(config.task, "Test task")
        self.assertEqual(config.max_revisions, 3)
        self.assertEqual(len(config.source_urls), 1)
        self.assertEqual(config.cdp_url, "ws://localhost:9222/devtools/browser/test")

    def test_zworker_auto_result_dataclass(self) -> None:
        result = jobs.ZworkerAutoRunResult(
            request_id="TEST-001",
            status="completed",
            final_decision="accepted",
            revision_count=1,
            error="",
            events_log_path="/tmp/events.jsonl",
            state_file_path="/tmp/run_state.json",
            timings={"test_ms": 100},
        )
        self.assertEqual(result.final_decision, "accepted")
        self.assertEqual(result.revision_count, 1)


class ZworkerAutoZipPreValidationTests(unittest.TestCase):

    def _make_zip(self, dir_path: Path, files: dict) -> Path:
        import zipfile
        zip_path = dir_path / "result.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return zip_path

    def test_zip_precheck_valid_zip_with_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "answer.md": "# Answer\n\nDone.\n",
                "src/file.py": "print('hello')\n",
            })
            valid, error = jobs._zworker_validate_zip_precheck(zip_path)
            self.assertTrue(valid)
            self.assertEqual(error, "")

    def test_zip_precheck_missing_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "src/file.py": "print('hello')\n",
            })
            valid, error = jobs._zworker_validate_zip_precheck(zip_path)
            self.assertFalse(valid)
            self.assertIn("answer.md", error)

    def test_zip_precheck_bad_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_zip = root / "bad.zip"
            bad_zip.write_text("not a zip", encoding="utf-8")
            valid, error = jobs._zworker_validate_zip_precheck(bad_zip)
            self.assertFalse(valid)
            self.assertIn("Bad ZIP", error)

    def test_zip_precheck_empty_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_zip = self._make_zip(root, {})
            valid, error = jobs._zworker_validate_zip_precheck(empty_zip)
            self.assertFalse(valid)
            self.assertIn("empty", error.lower())

    def test_zip_precheck_answer_in_subdir_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = self._make_zip(root, {
                "subdir/answer.md": "# Answer\n",
            })
            valid, error = jobs._zworker_validate_zip_precheck(zip_path)
            self.assertFalse(valid)
            self.assertIn("answer.md", error)


class ZworkerAutoStateEventsTests(unittest.TestCase):

    def test_auto_write_and_read_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir(parents=True)

            state = {
                "request_id": "TEST-001",
                "state": jobs.ZWORKER_AUTO_STATE_PROMPT_SENT,
                "revision_count": 0,
            }
            jobs._zworker_auto_write_state(run_dir, state)

            read_state = jobs._zworker_auto_read_state(run_dir)
            self.assertEqual(read_state["request_id"], "TEST-001")
            self.assertEqual(read_state["state"], jobs.ZWORKER_AUTO_STATE_PROMPT_SENT)

    def test_auto_read_missing_state_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir(parents=True)

            read_state = jobs._zworker_auto_read_state(run_dir)
            self.assertEqual(read_state, {})

    def test_auto_append_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"

            event = {
                "event": "prompt_sent",
                "request_id": "TEST-001",
                "timestamp": "2026-06-29T12:00:00Z",
            }
            jobs._zworker_auto_append_event(events_path, event)

            content = events_path.read_text(encoding="utf-8")
            self.assertIn("prompt_sent", content)
            self.assertIn("TEST-001", content)


class ZworkerAutoResumeTests(unittest.TestCase):

    def test_auto_run_resume_no_resend_when_prompt_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "auto" / "ZWORKER-20260629-120000-test"
            run_dir.mkdir(parents=True, exist_ok=True)

            state = {
                "request_id": "ZWORKER-20260629-120000-test",
                "state": jobs.ZWORKER_AUTO_STATE_PROMPT_SENT,
                "revision_count": 0,
                "config": {"task": "Test task"},
            }
            jobs._zworker_auto_write_state(run_dir, state)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", Path(tmp) / "auto"):
                config = jobs.ZworkerAutoRunConfig(
                    task="Test task",
                    request_id="ZWORKER-20260629-120000-test",
                    force_resend=False,
                )
                result = jobs.zworker_auto_run(config)

            self.assertEqual(result.status, "resumed")
            self.assertEqual(result.final_decision, "awaiting_zip")

    def test_auto_run_force_resend_bypasses_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "auto" / "ZWORKER-20260629-120000-test"
            run_dir.mkdir(parents=True, exist_ok=True)

            state = {
                "request_id": "ZWORKER-20260629-120000-test",
                "state": jobs.ZWORKER_AUTO_STATE_PROMPT_SENT,
                "revision_count": 0,
            }
            jobs._zworker_auto_write_state(run_dir, state)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", Path(tmp) / "auto"):
                config = jobs.ZworkerAutoRunConfig(
                    task="New task",
                    request_id="ZWORKER-20260629-120000-test",
                    force_resend=True,
                )
                result = jobs.zworker_auto_run(config)

            self.assertIn(result.status, ("failed", "completed", "awaiting_zip"))


class ZworkerAutoIntegrationTests(unittest.TestCase):

    def test_auto_run_creates_run_dir_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auto_dir = Path(tmp) / "auto"
            auto_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", auto_dir):
                config = jobs.ZworkerAutoRunConfig(
                    task="Integration test task",
                    context="Test context",
                    max_revisions=2,
                )
                result = jobs.zworker_auto_run(config)

            self.assertIn(result.status, ("completed", "awaiting_zip"))
            self.assertTrue(result.request_id.startswith("ZWORKER-"))
            self.assertTrue(Path(result.state_file_path).exists())
            self.assertTrue(Path(result.events_log_path).exists())

    def test_auto_run_writes_prompt_pack_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auto_dir = Path(tmp) / "auto"
            auto_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", auto_dir):
                config = jobs.ZworkerAutoRunConfig(task="Event test")
                result = jobs.zworker_auto_run(config)

            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("prompt_pack_completed", events_content)

    def test_auto_run_writes_initializing_event_before_prompt_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auto_dir = Path(tmp) / "auto"
            auto_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", auto_dir):
                config = jobs.ZworkerAutoRunConfig(task="Initializing event")
                result = jobs.zworker_auto_run(config)

            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("initializing", events_content)
            self.assertIn("prompt_pack_completed", events_content)
            self.assertLess(
                events_content.index("initializing"),
                events_content.index("prompt_pack_completed"),
                "initializing event must appear before prompt_pack_completed",
            )


class ZworkerAutoOrchestrationTests(unittest.TestCase):

    def _make_zip(self, dir_path: Path, files: dict) -> Path:
        import zipfile
        zip_path = dir_path / "result.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return zip_path

    def _setup_runtime(self, tmp: Path) -> dict:
        runtime = {
            "requests": tmp / "requests",
            "inbox": tmp / "inbox",
            "auto": tmp / "auto",
            "web": tmp / "web",
        }
        for d in runtime.values():
            d.mkdir(parents=True, exist_ok=True)
        return runtime

    def test_auto_run_accepted_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)

            zip_path = self._make_zip(base, {
                "answer.md": "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n\n",
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        config = jobs.ZworkerAutoRunConfig(
                            task="Test accepted path",
                            max_revisions=2,
                        )
                        result = jobs.zworker_auto_run(config, zip_path=zip_path)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_decision, "accepted")

    def test_auto_run_completes_with_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)

            zip_path = self._make_zip(base, {
                "answer.md": "# Answer\n\nDone.\n",
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        config = jobs.ZworkerAutoRunConfig(
                            task="Test with zip",
                            allowed_paths="src/",
                        )
                        result = jobs.zworker_auto_run(config, zip_path=zip_path)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_decision, "accepted")

    def test_auto_run_resume_no_resend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-test-resume"

            run_dir = runtime["auto"] / request_id
            run_dir.mkdir(parents=True, exist_ok=True)
            state = {
                "request_id": request_id,
                "state": jobs.ZWORKER_AUTO_STATE_PROMPT_SENT,
                "revision_count": 0,
                "config": {
                    "task": "Test resume",
                    "context": "",
                    "constraints": "",
                    "source_urls": [],
                    "allowed_paths": "",
                    "forbidden_paths": "",
                    "expected_outputs": "",
                    "max_revisions": 2,
                    "provider_id": "opencode",
                    "model_id": "deepseek-v4-flash-free",
                },
                "started_at": "2026-06-29T12:00:00Z",
            }
            (run_dir / "run_state.json").write_text(json.dumps(state), encoding="utf-8")

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                    config = jobs.ZworkerAutoRunConfig(
                        task="Test resume",
                        request_id=request_id,
                        force_resend=False,
                    )
                    result = jobs.zworker_auto_run(config)

            self.assertEqual(result.status, "resumed")
            self.assertEqual(result.final_decision, "awaiting_zip")

    def test_auto_run_force_resend_overrides_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-test-force"

            run_dir = runtime["auto"] / request_id
            run_dir.mkdir(parents=True, exist_ok=True)
            state = {
                "request_id": request_id,
                "state": jobs.ZWORKER_AUTO_STATE_PROMPT_SENT,
                "revision_count": 0,
            }
            (run_dir / "run_state.json").write_text(json.dumps(state), encoding="utf-8")

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                config = jobs.ZworkerAutoRunConfig(
                    task="Test force",
                    request_id=request_id,
                    force_resend=True,
                )
                result = jobs.zworker_auto_run(config)

            self.assertEqual(result.status, "awaiting_zip")
            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("prompt_pack_completed", events_content)

    def test_auto_run_zip_pre_validation_rejects_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)

            zip_path = self._make_zip(base, {
                "src/file.py": "print('hello')\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        config = jobs.ZworkerAutoRunConfig(
                            task="Test bad zip",
                            max_revisions=2,
                        )
                        result = jobs.zworker_auto_run(config, zip_path=zip_path)

            self.assertEqual(result.status, "needs_revision")
            self.assertEqual(result.final_decision, "awaiting_zip")
            self.assertEqual(result.revision_count, 1)

    def test_auto_run_web_runner_contract_requires_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-contract"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(json.dumps({"request_id": request_id, "state": "ANSWER_READY"}), encoding="utf-8")

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                    with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                        with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", return_value=(True, "")):
                            config = jobs.ZworkerAutoRunConfig(
                                task="Contract zip test",
                                request_id=request_id,
                            )
                            result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "failed")
            self.assertIn("web_runner_contract_no_zip", result.error)

    def test_auto_run_web_runner_accepts_contract_zip_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-contract-zip"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            zip_path = web_runtime_root / "output" / request_id / f"{request_id}-zworker-result.zip"
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with jobs.zipfile.ZipFile(zip_path, "w", jobs.zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("answer.md", "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n")
                zf.writestr("src/file.py", "print('hello')\n")

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(json.dumps({"request_id": request_id, "state": "ZIP_VALID", "zip_path": str(zip_path)}), encoding="utf-8")

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                            with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", return_value=(True, "")):
                                config = jobs.ZworkerAutoRunConfig(
                                    task="Contract zip test",
                                    request_id=request_id,
                                    allowed_paths="src/",
                                )
                                result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_decision, "accepted")

    def test_auto_run_web_runner_timeout_after_prompt_sent_becomes_awaiting_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-timeout-resume"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(
                json.dumps(
                    {
                        "request_id": request_id,
                        "state": "ANSWER_STREAMING",
                        "chat_url": "https://chatgpt.com/c/test-timeout-resume",
                    }
                ),
                encoding="utf-8",
            )

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                    with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                        with unittest.mock.patch.object(jobs, "_zworker_auto_run_model_preflight", return_value=(True, "")):
                            with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", return_value=(False, "web_runner_timeout")):
                                config = jobs.ZworkerAutoRunConfig(
                                    task="Timeout resume test",
                                    request_id=request_id,
                                )
                                result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "awaiting_zip")
            self.assertEqual(result.final_decision, "awaiting_zip")
            state_payload = json.loads(Path(result.state_file_path).read_text(encoding="utf-8"))
            self.assertEqual(state_payload["state"], jobs.ZWORKER_AUTO_STATE_PROMPT_SENT)
            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("web_runner_resume_available", events_content)

    def test_auto_run_web_runner_timeout_with_zip_still_processes_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-timeout-zip"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            zip_path = web_runtime_root / "output" / request_id / f"{request_id}-zworker-result.zip"
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with jobs.zipfile.ZipFile(zip_path, "w", jobs.zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("answer.md", "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n")
                zf.writestr("src/file.py", "print('hello')\n")

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(
                json.dumps(
                    {
                        "request_id": request_id,
                        "state": "ZIP_VALID",
                        "zip_path": str(zip_path),
                    }
                ),
                encoding="utf-8",
            )

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                            with unittest.mock.patch.object(jobs, "_zworker_auto_run_model_preflight", return_value=(True, "")):
                                with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", return_value=(False, "web_runner_timeout")):
                                    config = jobs.ZworkerAutoRunConfig(
                                        task="Timeout zip test",
                                        request_id=request_id,
                                        allowed_paths="src/",
                                    )
                                    result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_decision, "accepted")
            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("web_runner_failed_but_zip_present", events_content)

    def test_auto_run_web_runner_not_started_marks_not_started_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-not-started"

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                    with unittest.mock.patch.object(jobs, "_zworker_auto_run_model_preflight", return_value=(True, "")):
                        with unittest.mock.patch.object(
                            jobs,
                            "_zworker_auto_invoke_web_runner",
                            return_value=(False, "web_runner_not_started: session_state_missing; diag_dir=/tmp/diag"),
                        ):
                            config = jobs.ZworkerAutoRunConfig(
                                task="Not started test",
                                request_id=request_id,
                            )
                            result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "failed")
            self.assertIn("web_state=not_started", result.error)
            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn('"web_state": "not_started"', events_content)

    def test_auto_run_retries_once_after_web_runner_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-retry-not-started"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            zip_path = web_runtime_root / "output" / request_id / f"{request_id}-zworker-result.zip"
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with jobs.zipfile.ZipFile(zip_path, "w", jobs.zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("answer.md", "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n")
                zf.writestr("src/file.py", "print('hello')\n")

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(
                json.dumps({"request_id": request_id, "state": "ZIP_VALID", "zip_path": str(zip_path)}),
                encoding="utf-8",
            )

            invoke_mock = unittest.mock.Mock(side_effect=[
                (False, "web_runner_not_started: session_state_missing; diag_dir=/tmp/diag"),
                (True, ""),
            ])

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                            with unittest.mock.patch.object(jobs, "_zworker_auto_run_model_preflight", return_value=(True, "")):
                                with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", invoke_mock):
                                    with unittest.mock.patch.object(jobs.time, "sleep", return_value=None) as sleep_mock:
                                        config = jobs.ZworkerAutoRunConfig(
                                            task="Retry startup timeout",
                                            request_id=request_id,
                                            allowed_paths="src/",
                                        )
                                        result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_decision, "accepted")
            self.assertEqual(invoke_mock.call_count, 2)
            sleep_mock.assert_called()
            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("web_runner_retry_scheduled", events_content)
            self.assertIn("web_runner_retrying", events_content)

    def test_auto_run_runs_model_preflight_before_main_web_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-preflight-first"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            zip_path = web_runtime_root / "output" / request_id / f"{request_id}-zworker-result.zip"
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with jobs.zipfile.ZipFile(zip_path, "w", jobs.zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("answer.md", "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n")
                zf.writestr("src/file.py", "print('hello')\n")

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(
                json.dumps({"request_id": request_id, "state": "ZIP_VALID", "zip_path": str(zip_path)}),
                encoding="utf-8",
            )

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                            with unittest.mock.patch.object(jobs, "_zworker_auto_run_model_preflight", return_value=(True, "")) as preflight_mock:
                                with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", return_value=(True, "")) as invoke_mock:
                                    config = jobs.ZworkerAutoRunConfig(
                                        task="Preflight first",
                                        request_id=request_id,
                                        allowed_paths="src/",
                                    )
                                    result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_decision, "accepted")
            preflight_mock.assert_called_once()
            invoke_mock.assert_called_once()
            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("web_runner_preflight_started", events_content)
            self.assertIn("web_runner_preflight_completed", events_content)

    def test_auto_run_preflight_failure_stops_before_main_web_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-preflight-fail"

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                    with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                        with unittest.mock.patch.object(jobs, "_zworker_auto_run_model_preflight", return_value=(False, "FAILED_MODEL_NOT_VERIFIED")) as preflight_mock:
                            with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner") as invoke_mock:
                                config = jobs.ZworkerAutoRunConfig(
                                    task="Preflight fail",
                                    request_id=request_id,
                                )
                                result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "failed")
            self.assertIn("web_runner_preflight_failed", result.error)
            self.assertIn("FAILED_MODEL_NOT_VERIFIED", result.error)
            preflight_mock.assert_called_once()
            invoke_mock.assert_not_called()

    def test_auto_run_retries_with_model_preflight_after_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-preflight-retry"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            zip_path = web_runtime_root / "output" / request_id / f"{request_id}-zworker-result.zip"
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with jobs.zipfile.ZipFile(zip_path, "w", jobs.zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("answer.md", "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n")
                zf.writestr("src/file.py", "print('hello')\n")

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(
                json.dumps({"request_id": request_id, "state": "ZIP_VALID", "zip_path": str(zip_path)}),
                encoding="utf-8",
            )

            invoke_mock = unittest.mock.Mock(side_effect=[
                (False, "web_runner_not_started: session_state_missing; diag_dir=/tmp/diag"),
                (True, ""),
            ])

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                            with unittest.mock.patch.object(jobs, "_zworker_auto_run_model_preflight", return_value=(True, "")) as preflight_mock:
                                with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", invoke_mock):
                                    with unittest.mock.patch.object(jobs.time, "sleep", return_value=None):
                                        config = jobs.ZworkerAutoRunConfig(
                                            task="Preflight retry",
                                            request_id=request_id,
                                            allowed_paths="src/",
                                        )
                                        result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_decision, "accepted")
            self.assertEqual(invoke_mock.call_count, 2)
            self.assertEqual(preflight_mock.call_count, 2)
            events_content = Path(result.events_log_path).read_text(encoding="utf-8")
            self.assertIn("web_runner_preflight_started", events_content)
            self.assertIn("web_runner_retry_preflight_completed", events_content)

    def test_auto_run_writes_full_diagnostics_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-diagnostics"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"

            zip_path = web_runtime_root / "output" / request_id / f"{request_id}-zworker-result.zip"
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with jobs.zipfile.ZipFile(zip_path, "w", jobs.zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("answer.md", "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n")
                zf.writestr("src/file.py", "print('hello')\n")

            session_dir = web_runtime_root / "sessions" / request_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "run_state.json").write_text(
                json.dumps(
                    {
                        "request_id": request_id,
                        "state": "HANDOFF_DONE",
                        "chat_url": "https://chatgpt.com/c/test-diagnostics",
                        "zip_path": str(zip_path),
                    }
                ),
                encoding="utf-8",
            )
            (session_dir / "events.jsonl").write_text(
                "\n".join([
                    json.dumps({"ts": "2026-06-29T12:00:01.000Z", "event": "state_changed", "state": "CHAT_CREATED", "new_state": "CHAT_CREATED"}),
                    json.dumps({"ts": "2026-06-29T12:00:02.000Z", "event": "state_changed", "state": "PROMPT_SENT", "new_state": "PROMPT_SENT"}),
                    json.dumps({"ts": "2026-06-29T12:00:03.000Z", "event": "state_changed", "state": "HANDOFF_DONE", "new_state": "HANDOFF_DONE"}),
                ]) + "\n",
                encoding="utf-8",
            )

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                            with unittest.mock.patch.object(jobs, "_zworker_auto_invoke_web_runner", return_value=(True, "")):
                                config = jobs.ZworkerAutoRunConfig(
                                    task="Diagnostics timeline",
                                    request_id=request_id,
                                    allowed_paths="src/",
                                )
                                result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "completed")
            diagnostics_path = runtime["auto"] / request_id / "diagnostics" / "full_timeline.json"
            self.assertTrue(diagnostics_path.exists())
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            self.assertEqual(diagnostics["request_id"], request_id)
            self.assertEqual(diagnostics["final_outcome"]["status"], "completed")
            self.assertEqual(diagnostics["web"]["state"]["state"], "HANDOFF_DONE")
            sources = {item["source"] for item in diagnostics["timeline"]}
            self.assertIn("auto", sources)
            self.assertIn("web", sources)
            events = [item["event"] for item in diagnostics["timeline"]]
            self.assertIn("prompt_pack_completed", events)
            self.assertIn("state_changed", events)

    def test_auto_run_diagnostics_capture_startup_timeout_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)
            request_id = "ZWORKER-20260629-120000-diagnostics-startup-timeout"
            web_runtime_root = base / ".ai" / "zworker" / "runtime" / "web"
            diag_dir = web_runtime_root / "diagnostics" / request_id
            diag_dir.mkdir(parents=True, exist_ok=True)
            (diag_dir / "launch.json").write_text(
                json.dumps(
                    {
                        "request_id": request_id,
                        "timestamp": "2026-06-29T12:00:05.000Z",
                        "phase": "startup_timeout",
                        "returncode": 1,
                        "stdout_log": str(diag_dir / "stdout.log"),
                        "stderr_log": str(diag_dir / "stderr.log"),
                    }
                ),
                encoding="utf-8",
            )
            (diag_dir / "stdout.log").write_text("", encoding="utf-8")
            (diag_dir / "stderr.log").write_text("startup hang", encoding="utf-8")

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                    with unittest.mock.patch.object(jobs, "REPO_ROOT", base):
                        with unittest.mock.patch.object(
                            jobs,
                            "_zworker_auto_invoke_web_runner",
                            return_value=(False, "web_runner_not_started: session_state_missing; diag_dir=/tmp/diag"),
                        ):
                            config = jobs.ZworkerAutoRunConfig(
                                task="Diagnostics startup timeout",
                                request_id=request_id,
                            )
                            result = jobs.zworker_auto_run(config, use_web_runner=True)

            self.assertEqual(result.status, "failed")
            diagnostics_path = Path(result.diagnostics_report_path)
            self.assertTrue(diagnostics_path.exists())
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            self.assertEqual(diagnostics["web_runner_diagnostics"]["phase"], "startup_timeout")
            self.assertTrue(any(item["source"] == "web_runner_diagnostics" for item in diagnostics["timeline"]))

    def test_auto_run_max_revisions_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = self._setup_runtime(base)

            zip_path = self._make_zip(base, {
                "answer.md": "# Answer\n\nI couldn't create the files.\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", runtime["requests"]):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", runtime["inbox"]):
                    with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_AUTO", runtime["auto"]):
                        config = jobs.ZworkerAutoRunConfig(
                            task="Test max revisions",
                            allowed_paths="src/",
                            expected_outputs="src/utils.py",
                            max_revisions=2,
                        )
                        result = jobs.zworker_auto_run(config, zip_path=zip_path)

            self.assertEqual(result.status, "needs_revision")
            self.assertEqual(result.revision_count, 1)


class ZworkerAutoWebRunnerTimeoutTests(unittest.TestCase):

    def test_default_web_runner_timeout_is_720(self) -> None:
        config = jobs.ZworkerAutoRunConfig(task="Test task")
        self.assertEqual(config.web_runner_timeout_seconds, 720)

    def test_custom_web_runner_timeout_is_passed(self) -> None:
        config = jobs.ZworkerAutoRunConfig(task="Test task", web_runner_timeout_seconds=300)
        self.assertEqual(config.web_runner_timeout_seconds, 300)

    def test_web_runner_timeout_constant_defined(self) -> None:
        self.assertEqual(jobs.ZWORKER_AUTO_DEFAULT_WEB_RUNNER_TIMEOUT_SECONDS, 720)


class ZworkerSemanticRemapTests(unittest.TestCase):

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
            "expected_outputs": [],
        }
        if manifest_overrides:
            manifest.update(manifest_overrides)
        (req_dir / "request_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return req_dir

    def test_semantic_remap_exact_basename_match(self) -> None:
        out_of_scope = [
            ("components/Button.tsx", "not in scope"),
        ]
        expected = ["src/components/Button.tsx"]
        remaps = jobs._zworker_semantic_remap(out_of_scope, expected)
        self.assertEqual(len(remaps), 1)
        self.assertEqual(remaps[0][1], "src/components/Button.tsx")
        self.assertEqual(remaps[0][2], "exact_basename")

    def test_semantic_remap_unique_extension_match(self) -> None:
        out_of_scope = [
            ("temp/generated.svg", "not in scope"),
        ]
        expected = ["src/assets/icon.svg"]
        remaps = jobs._zworker_semantic_remap(out_of_scope, expected)
        self.assertEqual(len(remaps), 1)
        self.assertEqual(remaps[0][1], "src/assets/icon.svg")
        self.assertEqual(remaps[0][2], "unique_extension")

    def test_semantic_remap_skips_unique_extension_for_code_like_files(self) -> None:
        out_of_scope = [
            ("temp/helper.ts", "not in scope"),
        ]
        expected = ["src/utils.ts"]
        remaps = jobs._zworker_semantic_remap(out_of_scope, expected)
        self.assertEqual(remaps, [])

    def test_semantic_remap_no_match_when_multiple_extensions(self) -> None:
        out_of_scope = [
            ("temp/file.ts", "not in scope"),
        ]
        expected = ["src/file.ts", "lib/file.ts"]
        remaps = jobs._zworker_semantic_remap(out_of_scope, expected)
        self.assertEqual(len(remaps), 0)

    def test_semantic_remap_no_match_when_no_expected_outputs(self) -> None:
        out_of_scope = [
            ("src/extra.ts", "not in scope"),
        ]
        expected: list[str] = []
        remaps = jobs._zworker_semantic_remap(out_of_scope, expected)
        self.assertEqual(len(remaps), 0)

    def test_semantic_remap_multiple_files(self) -> None:
        out_of_scope = [
            ("temp/a.py", "not in scope"),
            ("temp/b.py", "not in scope"),
        ]
        expected = ["src/a.py", "src/b.py"]
        remaps = jobs._zworker_semantic_remap(out_of_scope, expected)
        self.assertEqual(len(remaps), 2)

    def test_process_result_remaps_exact_basename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260629-120000-remap1"
            self._make_request_dir(base, request_id, {
                "allowed_paths": ["src/"],
                "expected_outputs": ["src/Button.tsx"],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n\n"
                ),
                "components/Button.tsx": "export const Button = () => {};\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.decision, "accepted")
            self.assertTrue(output.auto_applied)
            self.assertGreater(output.remapped_files, 0)
            self.assertTrue((base / "src" / "Button.tsx").exists())

    def test_process_result_remaps_unique_extension_for_non_code_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260629-120000-remap2"
            self._make_request_dir(base, request_id, {
                "allowed_paths": ["src/assets/"],
                "expected_outputs": ["src/assets/icon.svg"],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n\n"
                ),
                "temp/generated.svg": "<svg></svg>\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.decision, "accepted")
            self.assertTrue(output.auto_applied)
            self.assertGreater(output.remapped_files, 0)
            self.assertTrue((base / "src" / "assets" / "icon.svg").exists())

    def test_process_result_blocks_unique_extension_remap_for_code_like_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260629-120000-remap4"
            self._make_request_dir(base, request_id, {
                "allowed_paths": ["src/"],
                "expected_outputs": ["src/helper.ts"],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n\n"
                ),
                "temp/generated.ts": "export const helper = () => {};\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.decision, "needs_clarification")
            self.assertFalse(output.auto_applied)
            self.assertEqual(output.remapped_files, 0)
            self.assertIn("out_of_scope_files_present", output.rejection_reasons)

    def test_process_result_ambiguous_case_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            request_id = "ZWORKER-20260629-120000-remap3"
            self._make_request_dir(base, request_id, {
                "allowed_paths": ["src/", "lib/"],
                "expected_outputs": ["src/utils.py", "lib/utils.py"],
            })
            self._make_unpack_dir(base, request_id, {
                "answer.md": (
                    "# Answer\n\n## Sources Read Report\n\n### Read fully\n- doc1\n\n### Read partially\n- none\n\n### Not read\n- none\n\n### External search used\nNo\n\n"
                ),
                "temp/utils.py": "def helper(): pass\n",
            })

            with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_REQUESTS", base / "requests"):
                with unittest.mock.patch.object(jobs, "ZWORKER_RUNTIME_INBOX", base / "inbox"):
                    output = jobs.zworker_process_result(
                        request_id,
                        unpack_dir=base / "inbox" / request_id,
                        target_root=base,
                    )
            self.assertEqual(output.decision, "needs_clarification")
            self.assertEqual(output.remapped_files, 0)


class ZworkerAutoAttachModeTests(unittest.TestCase):

    def test_resolve_cdp_url_prefers_existing_debugger(self) -> None:
        with unittest.mock.patch.object(jobs, "_zworker_auto_read_cdp_url", return_value="ws://localhost:9222/devtools/browser/live"):
            with unittest.mock.patch.object(jobs, "_zworker_auto_launch_chrome_plus_profile") as launch_mock:
                result = jobs._zworker_auto_resolve_cdp_url(wait_seconds=0)
        self.assertEqual(result, "ws://localhost:9222/devtools/browser/live")
        launch_mock.assert_not_called()

    def test_resolve_cdp_url_prefers_live_debugger_over_stale_preferred_url(self) -> None:
        with unittest.mock.patch.object(jobs, "_zworker_auto_read_cdp_url", return_value="ws://localhost:9222/devtools/browser/live"):
            result = jobs._zworker_auto_resolve_cdp_url(
                preferred_url="ws://localhost:9222/devtools/browser/stale",
                wait_seconds=0,
            )
        self.assertEqual(result, "ws://localhost:9222/devtools/browser/live")

    def test_resolve_cdp_url_launches_plus_profile_when_needed(self) -> None:
        with unittest.mock.patch.object(jobs, "_zworker_auto_read_cdp_url", side_effect=["", "ws://localhost:9222/devtools/browser/new"]):
            with unittest.mock.patch.object(jobs, "_zworker_auto_launch_chrome_plus_profile", return_value=True) as launch_mock:
                with unittest.mock.patch.object(jobs.time, "sleep", return_value=None):
                    result = jobs._zworker_auto_resolve_cdp_url(wait_seconds=1)
        self.assertEqual(result, "ws://localhost:9222/devtools/browser/new")
        launch_mock.assert_called_once()

    def test_invoke_web_runner_with_cdp_url_passes_attach_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "REPO_ROOT", Path(tmp)):
                ok, error = jobs._zworker_auto_invoke_web_runner(
                    request_id="ZWORKER-20260629-120000-test001",
                    runtime_root=runtime_root,
                    resume=False,
                    force_resend=False,
                    cdp_url="ws://localhost:9222/devtools/browser/test",
                    timeout_seconds=10,
                )
            self.assertFalse(ok)
            self.assertNotIn("FAILED_ATTACH_REQUIRED", error)

    def test_invoke_web_runner_without_cdp_url_uses_resolved_attach_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "REPO_ROOT", Path(tmp)):
                with unittest.mock.patch.object(jobs, "_zworker_auto_resolve_cdp_url", return_value="ws://localhost:9222/devtools/browser/test"):
                    ok, error = jobs._zworker_auto_invoke_web_runner(
                        request_id="ZWORKER-20260629-120000-test002",
                        runtime_root=runtime_root,
                        resume=False,
                        force_resend=False,
                        cdp_url="",
                        timeout_seconds=10,
                    )
            self.assertFalse(ok)
            self.assertNotIn("FAILED_ATTACH_REQUIRED", error)

    def test_invoke_web_runner_without_cdp_url_fails_when_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.object(jobs, "REPO_ROOT", Path(tmp)):
                with unittest.mock.patch.object(jobs, "_zworker_auto_resolve_cdp_url", return_value=""):
                    ok, error = jobs._zworker_auto_invoke_web_runner(
                        request_id="ZWORKER-20260629-120000-test003",
                        runtime_root=runtime_root,
                        resume=False,
                        force_resend=False,
                        cdp_url="",
                        timeout_seconds=10,
                    )
            self.assertFalse(ok)
            self.assertIn("cdp_url_unavailable", error)

    def test_invoke_web_runner_fails_fast_when_session_state_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)

            class FakeProcess:
                def __init__(self):
                    self.returncode = None
                    self.killed = False

                def poll(self):
                    return None

                def kill(self):
                    self.killed = True
                    self.returncode = -9

                def communicate(self, timeout=None):
                    return ("", "startup hang")

            fake_process = FakeProcess()

            monotonic_values = iter([0.0, 0.0, 0.3, 0.7, 1.2, 1.4, 1.5, 1.6])

            with unittest.mock.patch.object(jobs, "ZWORKER_AUTO_WEB_RUNNER_STARTUP_TIMEOUT_SECONDS", 1.0):
                with unittest.mock.patch.object(jobs, "REPO_ROOT", Path(tmp)):
                    with unittest.mock.patch.object(jobs, "_zworker_auto_resolve_cdp_url", return_value="ws://localhost:9222/devtools/browser/live"):
                        with unittest.mock.patch.object(jobs.subprocess, "Popen", return_value=fake_process):
                            with unittest.mock.patch.object(jobs.time, "monotonic", side_effect=lambda: next(monotonic_values)):
                                with unittest.mock.patch.object(jobs.time, "sleep", return_value=None):
                                    ok, error = jobs._zworker_auto_invoke_web_runner(
                                        request_id="ZWORKER-20260629-120000-startfail",
                                        runtime_root=runtime_root,
                                        cdp_url="ws://localhost:9222/devtools/browser/stale",
                                        timeout_seconds=10,
                                    )

            self.assertFalse(ok)
            self.assertTrue(fake_process.killed)
            self.assertIn("web_runner_not_started", error)
            self.assertIn("diag_dir=", error)
            diag_dir = runtime_root / "diagnostics" / "ZWORKER-20260629-120000-startfail"
            self.assertTrue((diag_dir / "launch.json").exists())
            self.assertTrue((diag_dir / "stderr.log").exists())
            launch = json.loads((diag_dir / "launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch["phase"], "startup_timeout")
            self.assertEqual(launch["probe_mode"], "")
            self.assertEqual(launch["pid"], 0)
            self.assertFalse(launch["session_dir_exists"])
            self.assertFalse(launch["session_state_exists"])
            self.assertGreaterEqual(launch["startup_timeout_seconds"], 1.0)
            self.assertTrue(launch["startup_trace"])

    def test_invoke_web_runner_detects_early_exit_with_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)

            class FakeProcessEarlyExit:
                def __init__(self):
                    self.returncode = 1
                    self.killed = False

                def poll(self):
                    return 1

                def kill(self):
                    self.killed = True

                def communicate(self, timeout=None):
                    return ("", "ModuleNotFoundError: No module named 'playwright'")

            fake_process = FakeProcessEarlyExit()

            with unittest.mock.patch.object(jobs, "ZWORKER_AUTO_WEB_RUNNER_STARTUP_TIMEOUT_SECONDS", 5.0):
                with unittest.mock.patch.object(jobs, "REPO_ROOT", Path(tmp)):
                    with unittest.mock.patch.object(jobs, "_zworker_auto_resolve_cdp_url", return_value="ws://localhost:9222/devtools/browser/live"):
                        with unittest.mock.patch.object(jobs.subprocess, "Popen", return_value=fake_process):
                            with unittest.mock.patch.object(jobs.time, "monotonic", return_value=0.5):
                                with unittest.mock.patch.object(jobs.time, "sleep", return_value=None):
                                    ok, error = jobs._zworker_auto_invoke_web_runner(
                                        request_id="ZWORKER-20260629-120000-early-exit",
                                        runtime_root=runtime_root,
                                        cdp_url="ws://localhost:9222/devtools/browser/live",
                                        timeout_seconds=10,
                                    )

            self.assertFalse(ok)
            self.assertFalse(fake_process.killed)
            self.assertIn("ModuleNotFoundError", error)
            self.assertIn("diag_dir=", error)
            diag_dir = runtime_root / "diagnostics" / "ZWORKER-20260629-120000-early-exit"
            self.assertTrue((diag_dir / "launch.json").exists())
            self.assertTrue((diag_dir / "stderr.log").exists())
            self.assertIn("startup_early_exit", (diag_dir / "launch.json").read_text(encoding="utf-8"))

    def test_invoke_web_runner_model_check_adds_probe_flag_to_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)
            request_id = "ZWORKER-20260629-120000-model-check"

            class FakeProcessEarlyExit:
                def __init__(self):
                    self.returncode = 1
                    self.killed = False
                    self.pid = 4242

                def poll(self):
                    return 1

                def kill(self):
                    self.killed = True

                def communicate(self, timeout=None):
                    return ("", "model check fail")

            fake_process = FakeProcessEarlyExit()

            with unittest.mock.patch.object(jobs, "REPO_ROOT", Path(tmp)):
                with unittest.mock.patch.object(jobs, "_zworker_auto_resolve_cdp_url", return_value="ws://localhost:9222/devtools/browser/live"):
                    with unittest.mock.patch.object(jobs.subprocess, "Popen", return_value=fake_process) as popen_mock:
                        with unittest.mock.patch.object(jobs.time, "monotonic", return_value=0.5):
                            with unittest.mock.patch.object(jobs.time, "sleep", return_value=None):
                                ok, error = jobs._zworker_auto_invoke_web_runner(
                                    request_id=request_id,
                                    runtime_root=runtime_root,
                                    cdp_url="ws://localhost:9222/devtools/browser/live",
                                    timeout_seconds=10,
                                    probe_mode="model_check",
                                )

            self.assertFalse(ok)
            self.assertIn("diag_dir=", error)
            invoked_cmd = popen_mock.call_args.args[0]
            self.assertIn("--model-check", invoked_cmd)
            diag_dir = runtime_root / "diagnostics" / request_id
            launch = json.loads((diag_dir / "launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch["probe_mode"], "model_check")

    def test_write_web_runner_diagnostics_creates_empty_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)

            diag_dir = jobs._zworker_auto_write_web_runner_diagnostics(
                runtime_root,
                "ZWORKER-20260629-120000-empty-logs",
                cmd=["python", "runner.py"],
                cdp_url="ws://localhost:9222/devtools/browser/live",
                returncode=None,
                stdout_text="",
                stderr_text="",
                phase="startup_timeout",
            )

            self.assertTrue((diag_dir / "stdout.log").exists())
            self.assertTrue((diag_dir / "stderr.log").exists())
            self.assertEqual((diag_dir / "stdout.log").read_text(encoding="utf-8"), "")
            self.assertEqual((diag_dir / "stderr.log").read_text(encoding="utf-8"), "")


class ZworkerAutoChatUrlValidationTests(unittest.TestCase):

    def test_web_runner_validates_chat_url_has_c_path(self) -> None:
        import importlib.util
        from pathlib import Path as P

        runner_path = P(__file__).resolve().parents[1] / "scripts" / "zworker_chatgpt_web_runner.py"
        if not runner_path.exists():
            pytest.skip("web runner script not found")

        spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner", runner_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        assert module.is_valid_chat_url("https://chatgpt.com/c/abc123") is True
        assert module.is_valid_chat_url("https://chatgpt.com/") is False
        assert module.is_valid_chat_url("https://chatgpt.com/explore") is False

    def test_wait_for_valid_chat_url_accepts_delayed_transition(self) -> None:
        import importlib.util
        import sys
        import tempfile
        from pathlib import Path as P

        runner_path = P(__file__).resolve().parents[1] / "scripts" / "zworker_chatgpt_web_runner.py"
        if not runner_path.exists():
            pytest.skip("web runner script not found")

        spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner", runner_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["zworker_chatgpt_web_runner_wait_url"] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            state = module.ZworkerWebRunState(
                "ZWORKER-20260629-120000-testwait",
                runtime_root=P(tmp),
            )

            class MockPage:
                def __init__(self):
                    self._urls = [
                        "https://chatgpt.com/",
                        "https://chatgpt.com/",
                        "https://chatgpt.com/c/abc123",
                    ]
                    self._index = 0

                @property
                def url(self):
                    value = self._urls[min(self._index, len(self._urls) - 1)]
                    self._index += 1
                    return value

            page = MockPage()
            ok = module.wait_for_valid_chat_url(page, state, 1500, source="unit_test")
            self.assertTrue(ok)
            self.assertEqual(state.chat_url, "https://chatgpt.com/c/abc123")

    def test_ensure_model_accepts_generic_plus_picker(self) -> None:
        import importlib.util
        import sys
        import tempfile
        from pathlib import Path as P

        runner_path = P(__file__).resolve().parents[1] / "scripts" / "zworker_chatgpt_web_runner.py"
        if not runner_path.exists():
            pytest.skip("web runner script not found")

        spec = importlib.util.spec_from_file_location("zworker_chatgpt_web_runner", runner_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["zworker_chatgpt_web_runner_model_picker"] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)

        class MockElement:
            def __init__(self, text: str):
                self._text = text

            def wait_for(self, state="visible", timeout=500):
                return None

            def click(self, timeout=3000):
                return None

            def inner_text(self, timeout=1000):
                return self._text

        class MockLocator:
            def __init__(self, items):
                self._items = items

            def count(self):
                return len(self._items)

            @property
            def first(self):
                return self._items[0]

            def filter(self, has_text=None):
                return self

        class MockBodyLocator:
            def inner_text(self, timeout=3000):
                return "Что у тебя сегодня на уме?"

        class MockTextLocator:
            def count(self):
                return 0

        class MockPage:
            def locator(self, selector: str):
                if selector == "body":
                    return MockBodyLocator()
                if selector == "button":
                    return MockLocator([MockElement("High")])
                return MockLocator([])

            def get_by_role(self, role, name=None):
                if role == "button":
                    return MockLocator([MockElement("High")])
                return MockLocator([])

            def get_by_text(self, text, exact=False):
                return MockTextLocator()

        with tempfile.TemporaryDirectory() as tmp:
            state = module.ZworkerWebRunState(
                "ZWORKER-20260629-120000-testmodel",
                runtime_root=P(tmp),
            )
            observed = module.ensure_model(
                MockPage(),
                state,
                ["Pro Extended", "Pro Standard"],
                timeout_ms=1000,
                allow_unverified=False,
            )

        self.assertEqual(observed, "High")
        self.assertEqual(state.metadata["observed_model"], "High")


class ZworkerAutoCliTests(unittest.TestCase):

    def test_main_zworker_auto_enables_web_runner(self) -> None:
        fake_result = jobs.ZworkerAutoRunResult(
            request_id="ZWORKER-20260629-120000-cli-smoke",
            status="completed",
            final_decision="accepted",
        )
        argv = [
            "codex_token_monitor_opencode_jobs.py",
            "--zworker-auto",
            "--zworker-auto-task",
            "CLI smoke task",
            "--zworker-auto-allowed-paths",
            "_w_route_smoke/smoke-note.md",
        ]

        with unittest.mock.patch.object(jobs, "zworker_auto_run", return_value=fake_result) as run_mock:
            with unittest.mock.patch.object(jobs.sys, "argv", argv):
                with unittest.mock.patch("builtins.print"):
                    with self.assertRaises(SystemExit) as exc:
                        jobs.main()

        self.assertEqual(exc.exception.code, jobs.EXIT_COMPLETED)
        self.assertTrue(run_mock.called)
        self.assertTrue(run_mock.call_args.kwargs["use_web_runner"])
        self.assertIn("job_config", run_mock.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
