#!/usr/bin/env python3
"""ZIP pre-validation helpers for the ChatGPT Web zworker helper slice.

The validator mirrors the lightweight zworker contract:
- answer.md must be at ZIP root;
- repo files are stored directly as repo-relative paths;
- unsafe paths are rejected before handoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")
_TEMP_DOWNLOAD_SUFFIXES = (".crdownload", ".tmp", ".download")
_NTFS_ADS_RE = re.compile(r":[^/\\]+$")
DEFAULT_MAX_ZIP_SIZE_BYTES = 50 * 1024 * 1024


@dataclass
class ZipValidationReport:
    zip_path: str
    status: str = "invalid"
    valid: bool = False
    security_reject: bool = False
    exists: bool = False
    non_empty: bool = False
    is_zip: bool = False
    answer_md_root: bool = False
    file_count: int = 0
    size_bytes: int = 0
    sha256: str = ""
    unsafe_paths: list[str] = field(default_factory=list)
    forbidden_hits: list[str] = field(default_factory=list)
    allowed_misses: list[str] = field(default_factory=list)
    duplicate_paths_casefold: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, Iterable):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def load_manifest_paths(manifest_path: Path | None) -> tuple[list[str], list[str]]:
    if not manifest_path:
        return [], []
    path = Path(manifest_path)
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return _as_list(data.get("allowed_paths")), _as_list(data.get("forbidden_paths"))


def normalize_zip_member(name: str) -> str:
    name = (name or "").replace("\\", "/")
    while "//" in name:
        name = name.replace("//", "/")
    return name.strip()


def is_unsafe_zip_path(name: str) -> bool:
    raw = name or ""
    normalized = normalize_zip_member(raw)
    if not normalized:
        return True
    if normalized.startswith("/") or normalized.startswith("//"):
        return True
    if raw.startswith("\\\\"):
        return True
    if _WINDOWS_DRIVE_RE.match(raw) or _WINDOWS_DRIVE_RE.match(normalized):
        return True
    if _NTFS_ADS_RE.search(normalized):
        return True
    parts = PurePosixPath(normalized).parts
    if any(part in {"..", "", "."} for part in parts):
        return True
    return False


def _clean_scope_path(value: str) -> str:
    return normalize_zip_member(value).strip("/")


def _matches_scope(path: str, scope: str) -> bool:
    path_norm = _clean_scope_path(path).casefold()
    scope_norm = _clean_scope_path(scope).casefold()
    if not scope_norm:
        return False
    return path_norm == scope_norm or path_norm.startswith(scope_norm.rstrip("/") + "/")


def _is_allowed(path: str, allowed_paths: list[str]) -> bool:
    if not allowed_paths:
        return True
    if _clean_scope_path(path) == "answer.md":
        return True
    return any(_matches_scope(path, allowed) for allowed in allowed_paths)


def _forbidden_hit(path: str, forbidden_paths: list[str]) -> str:
    for forbidden in forbidden_paths:
        if _matches_scope(path, forbidden):
            return forbidden
    return ""


def validate_zip(
    zip_path: str | Path,
    *,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    manifest_path: str | Path | None = None,
    max_size_bytes: int = DEFAULT_MAX_ZIP_SIZE_BYTES,
) -> ZipValidationReport:
    path = Path(zip_path)
    manifest_allowed, manifest_forbidden = load_manifest_paths(Path(manifest_path) if manifest_path else None)
    allowed = list(allowed_paths or []) + manifest_allowed
    forbidden = list(forbidden_paths or []) + manifest_forbidden

    report = ZipValidationReport(zip_path=str(path))
    report.exists = path.exists()
    if not report.exists:
        report.error = "zip file does not exist"
        return report

    report.size_bytes = path.stat().st_size
    report.non_empty = report.size_bytes > 0
    if not report.non_empty:
        report.error = "zip file is empty"
        return report
    if max_size_bytes > 0 and report.size_bytes > max_size_bytes:
        report.error = f"zip file exceeds max size ({report.size_bytes} > {max_size_bytes})"
        return report
    if path.name.endswith(_TEMP_DOWNLOAD_SUFFIXES):
        report.error = "zip path looks like an incomplete browser download"
        return report

    report.sha256 = sha256_file(path)
    report.is_zip = zipfile.is_zipfile(path)
    if not report.is_zip:
        report.error = "file is not a valid ZIP"
        return report

    seen_casefold: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            report.file_count = len(names)
            report.answer_md_root = "answer.md" in names
            for raw_name in names:
                normalized = normalize_zip_member(raw_name)
                if is_unsafe_zip_path(raw_name):
                    report.unsafe_paths.append(raw_name)
                    continue
                key = normalized.casefold()
                if key in seen_casefold and seen_casefold[key] != raw_name:
                    report.duplicate_paths_casefold.append(raw_name)
                else:
                    seen_casefold[key] = raw_name
                hit = _forbidden_hit(normalized, forbidden)
                if hit:
                    report.forbidden_hits.append(f"{raw_name} -> {hit}")
                if not _is_allowed(normalized, allowed):
                    report.allowed_misses.append(raw_name)
                if normalized.startswith("__MACOSX/") or normalized.endswith("/.DS_Store"):
                    report.warnings.append(f"unwanted platform artifact: {raw_name}")
    except zipfile.BadZipFile:
        report.error = "BadZipFile while opening ZIP"
        report.is_zip = False
        return report

    security_issues = bool(report.unsafe_paths) or bool(report.forbidden_hits)
    report.security_reject = security_issues

    if not report.answer_md_root:
        report.warnings.append("answer.md is missing at ZIP root")
    if report.allowed_misses:
        report.warnings.append(f"ZIP contains {len(report.allowed_misses)} file(s) outside allowed paths")
    if report.duplicate_paths_casefold:
        report.warnings.append(f"ZIP contains {len(report.duplicate_paths_casefold)} duplicate path(s) that collide case-insensitively")

    if security_issues:
        report.valid = False
        report.status = "security_reject"
        if report.unsafe_paths:
            report.error = "ZIP contains unsafe paths"
        elif report.forbidden_hits:
            report.error = "ZIP contains forbidden paths"
    elif report.warnings:
        report.valid = True
        report.status = "accepted_with_warnings"
        report.error = ""
    else:
        report.valid = True
        report.status = "valid"
        report.error = ""

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-validate a zworker result ZIP.")
    parser.add_argument("zip_path")
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--allowed-path", action="append", default=[])
    parser.add_argument("--forbidden-path", action="append", default=[])
    parser.add_argument("--report-json", default="")
    args = parser.parse_args(argv)
    report = validate_zip(
        args.zip_path,
        allowed_paths=args.allowed_path,
        forbidden_paths=args.forbidden_path,
        manifest_path=args.manifest_path or None,
    )
    encoded = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
