from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.zworker_web_zip import is_unsafe_zip_path, validate_zip


def make_zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return path


def test_valid_zip_with_answer_md_and_repo_file(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "ok.zip", {"answer.md": "# ok\n", "scripts/example.py": "print('ok')\n"})
    report = validate_zip(zip_path, forbidden_paths=["secrets/"])
    assert report.valid
    assert report.answer_md_root
    assert report.file_count == 2
    assert report.sha256


def test_zip_without_answer_md_is_invalid(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "bad.zip", {"docs/readme.md": "no answer\n"})
    report = validate_zip(zip_path)
    assert not report.valid
    assert report.error == "answer.md is missing at ZIP root"


def test_zip_with_traversal_is_invalid(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "evil.zip", {"answer.md": "ok", "../evil.txt": "bad"})
    report = validate_zip(zip_path)
    assert not report.valid
    assert "../evil.txt" in report.unsafe_paths


def test_zip_with_windows_absolute_path_is_invalid(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "evil.zip", {"answer.md": "ok", "C:/secret.txt": "bad"})
    report = validate_zip(zip_path)
    assert not report.valid
    assert "C:/secret.txt" in report.unsafe_paths


def test_zip_with_forbidden_path_is_invalid(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "forbidden.zip", {"answer.md": "ok", "secrets/token.txt": "bad"})
    report = validate_zip(zip_path, forbidden_paths=["secrets/"])
    assert not report.valid
    assert report.forbidden_hits


def test_allowed_paths_are_optional_but_enforced_when_present(tmp_path: Path) -> None:
    zip_path = make_zip(tmp_path / "scope.zip", {"answer.md": "ok", "docs/allowed.md": "ok", "scripts/not_allowed.py": "bad"})
    report = validate_zip(zip_path, allowed_paths=["docs/"])
    assert not report.valid
    assert "scripts/not_allowed.py" in report.allowed_misses


def test_manifest_paths_are_loaded(tmp_path: Path) -> None:
    manifest = tmp_path / "request_manifest.json"
    manifest.write_text(json.dumps({"forbidden_paths": ["forbidden/"], "allowed_paths": ["docs/"]}), encoding="utf-8")
    zip_path = make_zip(tmp_path / "manifest.zip", {"answer.md": "ok", "forbidden/x.txt": "bad"})
    report = validate_zip(zip_path, manifest_path=manifest)
    assert not report.valid
    assert report.forbidden_hits


def test_unsafe_path_helper() -> None:
    assert is_unsafe_zip_path("../x")
    assert is_unsafe_zip_path("/x")
    assert is_unsafe_zip_path("C:/x")
    assert is_unsafe_zip_path("a/../../x")
    assert not is_unsafe_zip_path("docs/x.md")
