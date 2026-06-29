#!/usr/bin/env python3
"""State/runtime helpers for zworker ChatGPT Web automation.

Dependency-free helper used by the future zworker-auto orchestrator. It writes:
- run_state.json
- events.jsonl
- chat_url.txt
and protects resume flows from accidental duplicate prompt sends.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROMPT_SENT_STATES = frozenset({
    "PROMPT_SENT", "ANSWER_STREAMING", "ANSWER_READY", "ZIP_LINK_WAITING",
    "ZIP_LINK_FOUND", "ZIP_DOWNLOAD_STARTING", "ZIP_DOWNLOAD_STARTED",
    "ZIP_DOWNLOADED", "ZIP_VALIDATING", "ZIP_VALID", "HANDOFF_UNPACKING",
    "HANDOFF_UNPACKED", "HANDOFF_PROCESSING", "HANDOFF_DONE",
})

ANSWER_READY_STATES = frozenset({
    "ANSWER_READY", "ZIP_LINK_WAITING", "ZIP_LINK_FOUND", "ZIP_DOWNLOAD_STARTING",
    "ZIP_DOWNLOAD_STARTED", "ZIP_DOWNLOADED", "ZIP_VALIDATING", "ZIP_VALID",
    "HANDOFF_UNPACKING", "HANDOFF_UNPACKED", "HANDOFF_PROCESSING", "HANDOFF_DONE",
})

DOWNLOAD_PHASE_STATES = frozenset({
    "ZIP_LINK_WAITING", "ZIP_LINK_FOUND", "ZIP_DOWNLOAD_STARTING",
    "ZIP_DOWNLOAD_STARTED", "ZIP_DOWNLOADED", "ZIP_VALIDATING", "ZIP_VALID",
    "HANDOFF_UNPACKING", "HANDOFF_UNPACKED", "HANDOFF_PROCESSING", "HANDOFF_DONE",
})

_REQUEST_ID_RE = re.compile(r"^ZWORKER-\d{8}-\d{6}-[A-Za-z0-9][A-Za-z0-9_-]*")


def utcnow_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_valid_chat_url(url: str) -> bool:
    if not url:
        return False
    return bool(re.search(r"/c/[a-zA-Z0-9]+", url))


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_request_id(request_id: str) -> None:
    if not _REQUEST_ID_RE.match(request_id or ""):
        raise ValueError(f"Invalid zworker request_id: {request_id!r}")


def atomic_write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        Path(tmp_name).replace(path)
    finally:
        tmp = Path(tmp_name)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(tmp_name).replace(path)
    finally:
        tmp = Path(tmp_name)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")


@dataclass
class ZworkerWebRunState:
    request_id: str
    runtime_root: str | Path = ".ai/zworker/runtime/web"
    attempt_no: int = 1
    revision_no: int = 1

    state: str = "CREATED"
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    chat_url: str = ""
    prompt_sha256: str = ""
    zip_path: str = ""
    zip_sha256: str = ""
    last_error: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)
        self.runtime_root = str(Path(self.runtime_root))
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (self.session_dir / "dom_snapshots").mkdir(parents=True, exist_ok=True)
        (self.session_dir / "traces").mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return Path(self.runtime_root)

    @property
    def session_dir(self) -> Path:
        return self.root / "sessions" / self.request_id

    @property
    def output_dir(self) -> Path:
        return self.root / "output" / self.request_id

    @property
    def downloads_dir(self) -> Path:
        return self.root / "downloads" / self.request_id

    @property
    def run_state_path(self) -> Path:
        return self.session_dir / "run_state.json"

    @property
    def events_path(self) -> Path:
        return self.session_dir / "events.jsonl"

    @property
    def chat_url_path(self) -> Path:
        return self.session_dir / "chat_url.txt"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runtime_root"] = str(self.runtime_root)
        payload["session_dir"] = str(self.session_dir)
        payload["output_dir"] = str(self.output_dir)
        payload["downloads_dir"] = str(self.downloads_dir)
        return payload

    def persist(self) -> None:
        atomic_write_json(self.run_state_path, self.to_dict())
        if self.chat_url:
            atomic_write_text(self.chat_url_path, self.chat_url + "\n")

    def event(self, event: str, **fields: Any) -> None:
        payload = {
            "ts": utcnow_iso(),
            "request_id": self.request_id,
            "attempt_no": self.attempt_no,
            "revision_no": self.revision_no,
            "state": self.state,
            "event": event,
        }
        payload.update(fields)
        append_jsonl(self.events_path, payload)

    def set_state(self, state: str, **fields: Any) -> None:
        self.state = state
        self.updated_at = utcnow_iso()
        if fields.get("chat_url"):
            self.chat_url = str(fields["chat_url"])
        if fields.get("prompt_sha256"):
            self.prompt_sha256 = str(fields["prompt_sha256"])
        if fields.get("zip_path"):
            self.zip_path = str(fields["zip_path"])
        if fields.get("zip_sha256"):
            self.zip_sha256 = str(fields["zip_sha256"])
        meta = {k: v for k, v in fields.items() if k not in {"chat_url", "prompt_sha256", "zip_path", "zip_sha256"}}
        if meta:
            self.metadata.update(meta)
        self.event("state_changed", new_state=state, **fields)
        self.persist()

    def fail(self, code: str, message: str, *, recoverable: bool = False, **fields: Any) -> None:
        self.state = "FAILED"
        self.updated_at = utcnow_iso()
        self.last_error = {"code": code, "message": message, "recoverable": recoverable, "ts": self.updated_at}
        self.last_error.update(fields)
        self.event("failed", code=code, message=message, recoverable=recoverable, **fields)
        self.persist()

    def has_prompt_been_sent(self) -> bool:
        return self.state in PROMPT_SENT_STATES or bool(self.metadata.get("prompt_sent_at"))

    def is_answer_ready(self) -> bool:
        return self.state in ANSWER_READY_STATES

    def is_in_download_phase(self) -> bool:
        return self.state in DOWNLOAD_PHASE_STATES

    def get_resume_point(self) -> str:
        if self.state == "ANSWER_READY":
            return "answer_ready"
        if self.state in DOWNLOAD_PHASE_STATES:
            return "download"
        if self.has_prompt_been_sent():
            return "prompt_sent"
        return "start"

    def can_skip_prompt_send(self) -> bool:
        return self.has_prompt_been_sent() and bool(self.chat_url) and is_valid_chat_url(self.chat_url)

    def require_prompt_send_allowed(self, *, force: bool = False) -> None:
        if force:
            return
        if self.has_prompt_been_sent() and not self.chat_url:
            raise RuntimeError(
                "Prompt was marked sent but no chat_url available. Use --force-resend."
            )

    @classmethod
    def load(cls, request_id: str, runtime_root: str | Path = ".ai/zworker/runtime/web") -> "ZworkerWebRunState":
        validate_request_id(request_id)
        path = Path(runtime_root) / "sessions" / request_id / "run_state.json"
        if not path.exists():
            return cls(request_id=request_id, runtime_root=runtime_root)
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = {
            "request_id", "runtime_root", "attempt_no", "revision_no", "state", "created_at",
            "updated_at", "chat_url", "prompt_sha256", "zip_path", "zip_sha256", "last_error", "metadata",
        }
        kwargs = {k: data[k] for k in keys if k in data}
        kwargs["runtime_root"] = runtime_root
        return cls(**kwargs)
