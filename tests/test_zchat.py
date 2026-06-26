import importlib.util
import json
import tempfile
import unittest
import uuid
import zipfile
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


class ZchatPromptPackTests(unittest.TestCase):

    def test_prompt_pack_creates_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zchat_output"
            result = jobs.zchat_prompt_pack(
                "Test task",
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

            prompt_text = prompt_path.read_text(encoding="utf-8")
            self.assertIn("Test task", prompt_text)
            self.assertIn("Test context", prompt_text)
            self.assertIn("Test constraint", prompt_text)

            passport_text = passport_path.read_text(encoding="utf-8")
            self.assertIn("https://example.com/file.py", passport_text)
            self.assertIn("temporary branch is NOT required", passport_text)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["manifest_version"], "1.0")
            self.assertEqual(manifest["mode"], jobs.ZCHAT_MODE_PROMPT_PACK)
            self.assertEqual(manifest["source_policy"], "public_github_raw_first")
            self.assertEqual(manifest["branch_policy"], "temporary_branch_only_if_public_insufficient")
            self.assertIn("prompt.md", manifest["artifacts"])
            self.assertIn("prompt_passport.md", manifest["artifacts"])
            self.assertIn("request_manifest.json", manifest["artifacts"])

    def test_prompt_pack_no_urls_marks_branch_may_be_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zchat_output"
            result = jobs.zchat_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")

            passport_text = (output_dir / "prompt_passport.md").read_text(encoding="utf-8")
            self.assertIn("temporary branch is NOT required", passport_text)

    def test_prompt_pack_uses_zchat_slug_when_no_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zchat_output"
            result = jobs.zchat_prompt_pack("Task", output_dir=output_dir)
            self.assertTrue(result.request_id)
            self.assertTrue(result.request_id.startswith("ZCHAT-"))
            self.assertTrue(jobs._zchat_slug_id_is_valid(result.request_id))

    def test_prompt_pack_explicit_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zchat_output"
            result = jobs.zchat_prompt_pack("Task", output_dir=output_dir, request_id="req-123")
            self.assertEqual(result.request_id, "req-123")


class ZchatImportPackTests(unittest.TestCase):

    def _create_test_zip(self, tmpdir: Path, files: list[tuple[str, str]], include_checksums: bool = True) -> Path:
        zip_path = tmpdir / "test_pack.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "manifest_version": "1.0",
                "package_id": "test-pkg-001",
                "created_at": "2025-01-01T00:00:00.000Z",
                "mode": "zchat_import_pack",
                "payload_files": [],
                "metadata": {},
            }
            checksum_lines = []
            for file_path, content in files:
                manifest["payload_files"].append({
                    "path": file_path,
                    "sha256": jobs._sha256_hex(content.encode("utf-8")),
                })
                zf.writestr("payload/" + file_path.replace("\\", "/"), content)
                checksum_lines.append(
                    f"{jobs._sha256_hex(content.encode('utf-8'))}  {file_path}"
                )
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            if include_checksums:
                zf.writestr("checksums.sha256", "\n".join(checksum_lines) + "\n")
        return zip_path

    def test_import_pack_missing_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = jobs.zchat_import_pack(Path(tmp) / "nonexistent.zip")
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)
            self.assertEqual(result.status, "failed")

    def test_import_pack_success_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [("test.py", "print('hello')")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_ACCEPTED)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.files_imported, 1)
            self.assertEqual(result.files_skipped, 0)
            self.assertTrue((target / "test.py").exists())
            self.assertEqual((target / "test.py").read_text(encoding="utf-8"), "print('hello')")
            self.assertTrue(Path(result.report_path).exists())

    def test_import_pack_success_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            files = [
                ("src/main.py", "def main(): pass"),
                ("src/utils.py", "def util(): pass"),
                ("README.md", "# Test"),
            ]
            zip_path = self._create_test_zip(tmpdir, files)
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_ACCEPTED)
            self.assertEqual(result.files_imported, 3)
            self.assertTrue((target / "src" / "main.py").exists())
            self.assertTrue((target / "src" / "utils.py").exists())
            self.assertTrue((target / "README.md").exists())

    def test_import_pack_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = tmpdir / "bad.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                manifest = {
                    "manifest_version": "1.0",
                    "package_id": "test",
                    "created_at": "2025-01-01T00:00:00.000Z",
                    "mode": "zchat_import_pack",
                    "payload_files": [{"path": "file.txt", "sha256": "a" * 64}],
                }
                zf.writestr("manifest.json", json.dumps(manifest))
                zf.writestr("checksums.sha256", f"{'b' * 64}  file.txt\n")
                zf.writestr("payload/file.txt", "content")
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)
            self.assertFalse((target / "file.txt").exists())

    def test_import_pack_forbidden_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [("/etc/passwd", "bad")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_SCOPE)

    def test_import_pack_forbidden_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [("../escape.txt", "bad")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_SCOPE)

    def test_import_pack_forbidden_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [(".git/config", "bad")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_SCOPE)

    def test_import_pack_forbidden_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [(".env", "SECRET=bad")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_SCOPE)

    def test_import_pack_forbidden_env_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [(".env.production", "SECRET=bad")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_SCOPE)

    def test_import_pack_forbidden_zchat_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [(".ai/zchat/runtime/file.txt", "bad")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_SCOPE)

    def test_import_pack_scope_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            outside = tmpdir / "outside"
            outside.mkdir()
            zip_path = self._create_test_zip(tmpdir, [(f"../../{outside.name}/escape.txt", "bad")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_SCOPE)

    def test_import_pack_nested_directories_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = self._create_test_zip(tmpdir, [("a/b/c/d/deep.py", "x=1")])
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_ACCEPTED)
            self.assertTrue((target / "a" / "b" / "c" / "d" / "deep.py").exists())

    def test_import_pack_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = tmpdir / "nomanifest.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("checksums.sha256", "abc\n")
                zf.writestr("payload/test.txt", "data")
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)

    def test_import_pack_missing_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = tmpdir / "nochecksums.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                manifest = {"manifest_version": "1.0", "package_id": "test", "mode": "zchat_import_pack", "payload_files": []}
                zf.writestr("manifest.json", json.dumps(manifest))
                zf.writestr("payload/test.txt", "data")
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)

    def test_import_pack_empty_payload_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = tmpdir / "empty.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                manifest = {"manifest_version": "1.0", "package_id": "test", "mode": "zchat_import_pack", "payload_files": []}
                zf.writestr("manifest.json", json.dumps(manifest))
                zf.writestr("checksums.sha256", "")
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)


class ZchatVerifyPackTests(unittest.TestCase):

    def test_verify_pack_missing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = jobs.zchat_verify_pack(Path(tmp) / "nonexistent")
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)

    def test_verify_pack_valid_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pack_dir = tmpdir / "pack"
            pack_dir.mkdir()
            (pack_dir / "payload").mkdir()

            content = b"test data"
            sha = jobs._sha256_hex(content)
            (pack_dir / "payload" / "file.txt").write_bytes(content)

            manifest = {
                "manifest_version": "1.0",
                "package_id": "test",
                "created_at": "2025-01-01T00:00:00.000Z",
                "mode": "zchat_import_pack",
                "payload_files": [{"path": "file.txt", "sha256": sha}],
            }
            (pack_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            (pack_dir / "checksums.sha256").write_text(f"{sha}  file.txt\n", encoding="utf-8")

            result = jobs.zchat_verify_pack(pack_dir)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_ACCEPTED)
            self.assertTrue(Path(result.report_path).exists())

    def test_verify_pack_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pack_dir = tmpdir / "pack"
            pack_dir.mkdir()
            (pack_dir / "payload").mkdir()
            (pack_dir / "checksums.sha256").write_text("abc\n", encoding="utf-8")

            result = jobs.zchat_verify_pack(pack_dir)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)

    def test_verify_pack_missing_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pack_dir = tmpdir / "pack"
            pack_dir.mkdir()
            (pack_dir / "payload").mkdir()

            manifest = {"manifest_version": "1.0", "package_id": "test", "mode": "zchat_import_pack", "payload_files": []}
            (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            result = jobs.zchat_verify_pack(pack_dir)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)

    def test_verify_pack_missing_payload_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pack_dir = tmpdir / "pack"
            pack_dir.mkdir()

            manifest = {"manifest_version": "1.0", "package_id": "test", "mode": "zchat_import_pack", "payload_files": []}
            (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (pack_dir / "checksums.sha256").write_text("", encoding="utf-8")

            result = jobs.zchat_verify_pack(pack_dir)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)

    def test_verify_pack_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pack_dir = tmpdir / "pack"
            pack_dir.mkdir()
            (pack_dir / "payload").mkdir()
            (pack_dir / "payload" / "file.txt").write_text("content", encoding="utf-8")

            manifest = {
                "manifest_version": "1.0",
                "package_id": "test",
                "mode": "zchat_import_pack",
                "payload_files": [{"path": "file.txt", "sha256": "a" * 64}],
            }
            (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (pack_dir / "checksums.sha256").write_text(f"{'b' * 64}  file.txt\n", encoding="utf-8")

            result = jobs.zchat_verify_pack(pack_dir)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_REJECTED_STRUCTURAL)

    def test_verify_pack_extra_payload_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pack_dir = tmpdir / "pack"
            pack_dir.mkdir()
            (pack_dir / "payload").mkdir()
            (pack_dir / "payload" / "file.txt").write_text("one", encoding="utf-8")
            (pack_dir / "payload" / "extra.txt").write_text("two", encoding="utf-8")

            manifest = {
                "manifest_version": "1.0",
                "package_id": "test",
                "mode": "zchat_import_pack",
                "payload_files": [{"path": "file.txt", "sha256": jobs._sha256_hex(b"one")}],
            }
            (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            sha_file = jobs._sha256_hex(b"one")
            (pack_dir / "checksums.sha256").write_text(f"{sha_file}  file.txt\n", encoding="utf-8")

            result = jobs.zchat_verify_pack(pack_dir)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_NEEDS_DECISION)


class ZchatForbiddenPathTests(unittest.TestCase):

    def test_absolute_path_forbidden(self) -> None:
        result = jobs._zchat_forbidden_path("/etc/passwd", Path("/tmp"))
        self.assertTrue(result)

    def test_traversal_forbidden(self) -> None:
        result = jobs._zchat_forbidden_path("../escape.txt", Path("/tmp/repo"))
        self.assertTrue(result)

    def test_git_prefix_forbidden(self) -> None:
        result = jobs._zchat_forbidden_path(".git/config", Path("/tmp/repo"))
        self.assertTrue(result)

    def test_env_prefix_forbidden(self) -> None:
        result = jobs._zchat_forbidden_path(".env", Path("/tmp/repo"))
        self.assertTrue(result)

    def test_env_production_forbidden(self) -> None:
        result = jobs._zchat_forbidden_path(".env.production", Path("/tmp/repo"))
        self.assertTrue(result)

    def test_zchat_path_forbidden(self) -> None:
        result = jobs._zchat_forbidden_path(".ai/zchat/runtime/file.txt", Path("/tmp/repo"))
        self.assertTrue(result)

    def test_normal_path_allowed(self) -> None:
        result = jobs._zchat_forbidden_path("src/main.py", Path("/tmp/repo"))
        self.assertEqual(result, "")

    def test_nested_path_allowed(self) -> None:
        result = jobs._zchat_forbidden_path("a/b/c/d/file.py", Path("/tmp/repo"))
        self.assertEqual(result, "")

    def test_windows_absolute_path_forbidden(self) -> None:
        result = jobs._zchat_forbidden_path("C:\\Windows\\file.txt", Path("D:\\repo"))
        self.assertTrue(result)


class ZchatSlugIdTests(unittest.TestCase):

    def test_slug_id_format(self) -> None:
        slug = jobs._zchat_slug_id()
        self.assertTrue(slug.startswith("ZCHAT-"))
        self.assertTrue(jobs._zchat_slug_id_is_valid(slug))

    def test_slug_id_uniqueness(self) -> None:
        slugs = {jobs._zchat_slug_id() for _ in range(10)}
        self.assertEqual(len(slugs), 10)

    def test_slug_id_rejects_invalid(self) -> None:
        self.assertFalse(jobs._zchat_slug_id_is_valid(""))
        self.assertFalse(jobs._zchat_slug_id_is_valid("ZCHAT-abc"))
        self.assertFalse(jobs._zchat_slug_id_is_valid("not-a-slug"))
        self.assertFalse(jobs._zchat_slug_id_is_valid(str(uuid.uuid4())))
        self.assertFalse(jobs._zchat_slug_id_is_valid("ZCHAT-20260101-120000-ZZZZZZZZ"))

    def test_slug_id_validates_correctly(self) -> None:
        slug = jobs._zchat_slug_id()
        self.assertEqual(len(slug.split("-")), 4)


class ZchatDecisionPackTests(unittest.TestCase):

    def test_decision_pack_accepted(self) -> None:
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef01",
            reviewer="codex",
            verdict=jobs.ZCHAT_DECISION_ACCEPTED,
            rationale="All checks passed.",
            evidence="CI green, review approved.",
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.verdict, jobs.ZCHAT_DECISION_ACCEPTED)
        self.assertTrue(result.decision_id)
        self.assertTrue("accepted" in result.journal_path.replace("\\", "/"))
        self.assertTrue(Path(result.decision_path).exists())
        self.assertTrue(Path(result.manifest_path).exists())

        decision_text = Path(result.decision_path).read_text(encoding="utf-8")
        self.assertIn("accepted", decision_text)
        self.assertIn("All checks passed", decision_text)
        self.assertIn("CI green", decision_text)

        manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["verdict"], jobs.ZCHAT_DECISION_ACCEPTED)
        self.assertEqual(manifest["subject_id"], "ZCHAT-20260601-120000-abcdef01")

    def test_decision_pack_rejected(self) -> None:
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef02",
            verdict=jobs.ZCHAT_DECISION_REJECTED,
            rationale="Scope violation detected.",
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.verdict, jobs.ZCHAT_DECISION_REJECTED)
        self.assertTrue("rejected" in result.journal_path.replace("\\", "/"))
        self.assertTrue(Path(result.decision_path).exists())

        decision_text = Path(result.decision_path).read_text(encoding="utf-8")
        self.assertIn("rejected", decision_text)
        self.assertIn("Scope violation detected", decision_text)

    def test_decision_pack_needs_revision(self) -> None:
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef03",
            verdict=jobs.ZCHAT_DECISION_NEEDS_REVISION,
            rationale="Missing tests.",
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.verdict, jobs.ZCHAT_DECISION_NEEDS_REVISION)
        self.assertTrue("reviews" in result.journal_path.replace("\\", "/"))

    def test_decision_pack_missing_verdict(self) -> None:
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef04",
            verdict="",
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("verdict is required", result.error)

    def test_decision_pack_invalid_verdict(self) -> None:
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef05",
            verdict="invalid_verdict",
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("Invalid verdict", result.error)

    def test_decision_pack_uses_slug_when_no_id(self) -> None:
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef06",
            verdict=jobs.ZCHAT_DECISION_ACCEPTED,
        )
        self.assertTrue(result.decision_id.startswith("ZCHAT-"))
        self.assertTrue(jobs._zchat_slug_id_is_valid(result.decision_id))

    def test_decision_pack_explicit_id(self) -> None:
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef07",
            verdict=jobs.ZCHAT_DECISION_ACCEPTED,
            decision_id="ZCHAT-CUSTOM-001",
        )
        self.assertEqual(result.decision_id, "ZCHAT-CUSTOM-001")

    def test_decision_pack_with_branch_info(self) -> None:
        branch_info = {
            "slug_id": "ZCHAT-20260601-120000-branch01",
            "branch_name": "zchat/test-branch",
            "base_branch": "main",
            "created": True,
            "pushed": True,
            "deleted": False,
            "error": "",
        }
        result = jobs.zchat_decision_pack(
            subject_id="ZCHAT-20260601-120000-abcdef08",
            verdict=jobs.ZCHAT_DECISION_ACCEPTED,
            rationale="Branch created and pushed.",
            branch_info=branch_info,
        )
        self.assertEqual(result.status, "completed")

        decision_text = Path(result.decision_path).read_text(encoding="utf-8")
        self.assertIn("zchat/test-branch", decision_text)
        self.assertIn("created", decision_text)

        manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["branch_info"]["branch_name"], "zchat/test-branch")
        self.assertTrue(manifest["branch_info"]["created"])
        self.assertTrue(manifest["branch_info"]["pushed"])


class ZchatStructuredRuntimeTests(unittest.TestCase):

    def test_prompt_pack_uses_requests_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "custom_out"
            result = jobs.zchat_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            self.assertTrue(output_dir.exists())

    def test_prompt_pack_default_dir_is_under_requests(self) -> None:
        result = jobs.zchat_prompt_pack("Task")
        self.assertEqual(result.status, "completed")
        output_dir = Path(result.output_dir)
        self.assertTrue("requests" in output_dir.parts)
        self.assertTrue(jobs._zchat_slug_id_is_valid(output_dir.name))

    def test_import_pack_uses_imports_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            target = tmpdir / "target"
            target.mkdir()
            zip_path = tmpdir / "test.zip"
            content = b"hello"
            sha = jobs._sha256_hex(content)
            manifest = {
                "manifest_version": "1.0",
                "package_id": "struct-test",
                "mode": jobs.ZCHAT_MODE_IMPORT_PACK,
                "payload_files": [{"path": "test.txt", "sha256": sha}],
            }
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest))
                zf.writestr("checksums.sha256", f"{sha}  test.txt\n")
                zf.writestr("payload/test.txt", content)
            result = jobs.zchat_import_pack(zip_path, target_root=target)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_ACCEPTED)
            report_dir = Path(result.report_path).parent
            self.assertTrue("imports" in Path(result.report_path).parts)

    def test_verify_pack_uses_reviews_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pack_dir = tmpdir / "pack"
            pack_dir.mkdir()
            (pack_dir / "payload").mkdir()
            content = b"data"
            sha = jobs._sha256_hex(content)
            (pack_dir / "payload" / "f.txt").write_bytes(content)
            manifest = {
                "manifest_version": "1.0",
                "package_id": "review-test",
                "mode": jobs.ZCHAT_MODE_IMPORT_PACK,
                "payload_files": [{"path": "f.txt", "sha256": sha}],
            }
            (pack_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            (pack_dir / "checksums.sha256").write_text(f"{sha}  f.txt\n", encoding="utf-8")
            result = jobs.zchat_verify_pack(pack_dir)
            self.assertEqual(result.verdict, jobs.ZCHAT_VERDICT_ACCEPTED)
            self.assertTrue("reviews" in Path(result.report_path).parts)


class ZchatBranchPolicyTests(unittest.TestCase):

    def test_branch_decision_public_sufficient(self) -> None:
        decision = _git_utils_module.resolve_branch_decision(
            source_urls=["https://raw.githubusercontent.com/example/repo/main/file.py"],
        )
        self.assertEqual(decision["decision"], "no_branch_needed")
        self.assertFalse(decision["create_branch"])

    def test_branch_decision_public_insufficient(self) -> None:
        decision = _git_utils_module.resolve_branch_decision(source_urls=[])
        self.assertEqual(decision["decision"], "branch_may_be_needed")
        self.assertFalse(decision["create_branch"])

    def test_branch_decision_has_public_context(self) -> None:
        decision = _git_utils_module.resolve_branch_decision(
            has_public_github_context=True,
        )
        self.assertEqual(decision["decision"], "no_branch_needed")
        self.assertFalse(decision["create_branch"])

    def test_prompt_pack_no_urls_resolves_branch_decision_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "zchat_output"
            result = jobs.zchat_prompt_pack("Task", output_dir=output_dir)
            self.assertEqual(result.status, "completed")
            passport_text = (output_dir / "prompt_passport.md").read_text(encoding="utf-8")
            self.assertIn("temporary branch is NOT required", passport_text)


if __name__ == "__main__":
    unittest.main()
