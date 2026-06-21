import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "scripts" / "codex_token_monitor_server.py"
SPEC = importlib.util.spec_from_file_location("codex_token_monitor_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(server)


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def event(event_type: str, payload: dict | None = None) -> dict:
    return {"type": event_type, "payload": payload or {}}


def make_step(index: int, start: int, end: int) -> dict:
    return {
        "step_index": index,
        "event_range": {
            "start_event_index": start,
            "end_event_index": end,
            "raw_events_count": end - start + 1,
        },
    }


class RawJsonlIteratorTests(unittest.TestCase):
    def test_tracks_exact_offsets_and_skips_blank_and_malformed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            first = json.dumps(event("session_meta")).encode()
            second = json.dumps(event("turn_context")).encode()
            data = first + b"\r\n\r\n{broken}\n" + second + b"\n"
            write_bytes(rollout, data)

            records = list(server._iter_rollout_jsonl_records(root, [rollout]))

            self.assertEqual([r["global_event_index"] for r in records], [1, 2])
            self.assertEqual([r["line_number"] for r in records], [1, 4])
            self.assertEqual(records[0]["byte_start"], 0)
            self.assertEqual(records[0]["byte_end"], len(first) + 2)
            second_start = data.index(second)
            self.assertEqual(records[1]["byte_start"], second_start)
            self.assertEqual(records[1]["byte_end"], second_start + len(second) + 1)
            self.assertEqual(records[1]["event"]["type"], "turn_context")

    def test_existing_reader_returns_only_parsed_event_dicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            expected = [event("session_meta"), event("turn_context")]
            write_bytes(
                rollout,
                json.dumps(expected[0]).encode()
                + b"\n\nnot-json\n"
                + json.dumps(expected[1]).encode()
                + b"\n",
            )
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                self.assertEqual(server._read_rollout_jsonl(root, "thread"), expected)


class LiveRolloutCacheTests(unittest.TestCase):
    def test_cache_ttl_starts_after_slow_index_build_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            write_bytes(rollout, b"{}\n")
            clock = [100.0]
            scan_count = 0

            def fake_scan(path):
                nonlocal scan_count
                scan_count += 1
                clock[0] += 20.0
                return "thread", {"paths": [str(path)], "step_count": 1}

            cache_key = str(root.resolve())
            server._live_rollout_summary_cache.pop(cache_key, None)
            with (
                mock.patch.object(server.time, "time", side_effect=lambda: clock[0]),
                mock.patch.object(server, "_scan_rollout_file_summary", side_effect=fake_scan),
            ):
                first = server._get_live_rollout_summaries(root)
                second = server._get_live_rollout_summaries(root)

            self.assertIs(first, second)
            self.assertEqual(scan_count, 1)


class RawExportZipTests(unittest.TestCase):
    def test_selected_zip_preserves_bytes_and_builds_exact_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            rows = [json.dumps(event(f"e{i}")).encode() for i in range(1, 5)]
            original = rows[0] + b"\n" + rows[1] + b"\n\nbad\n" + rows[2] + b"\n" + rows[3] + b"\n"
            write_bytes(rollout, original)

            archive_path = server._create_raw_export_zip(
                root,
                "thread",
                [rollout],
                [make_step(1, 1, 3), make_step(2, 4, 4)],
                [1],
            )
            try:
                with zipfile.ZipFile(archive_path) as zf:
                    raw_names = [n for n in zf.namelist() if n.startswith("raw/")]
                    self.assertEqual(len(raw_names), 1)
                    self.assertEqual(zf.read(raw_names[0]), original)
                    self.assertEqual(zf.getinfo(raw_names[0]).compress_type, zipfile.ZIP_STORED)
                    manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["mode"], "selected")
                self.assertEqual(manifest["requested_step_indices"], [1])
                self.assertEqual([s["step_index"] for s in manifest["steps"]], [1])
                self.assertEqual(len(manifest["steps"][0]["segments"]), 2)
                self.assertEqual(
                    manifest["steps"][0]["segments"][0]["event_start"],
                    1,
                )
                self.assertEqual(
                    manifest["steps"][0]["segments"][0]["event_end"],
                    2,
                )
                self.assertEqual(
                    manifest["steps"][0]["segments"][1]["event_start"],
                    3,
                )
            finally:
                archive_path.unlink(missing_ok=True)

    def test_session_mode_includes_all_steps_across_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "sessions" / "a" / "rollout-a.jsonl"
            second = root / "sessions" / "b" / "rollout-b.jsonl"
            write_bytes(first, json.dumps(event("e1")).encode() + b"\n")
            write_bytes(
                second,
                json.dumps(event("e2")).encode()
                + b"\n"
                + json.dumps(event("e3")).encode()
                + b"\n",
            )

            archive_path = server._create_raw_export_zip(
                root,
                "thread",
                [first, second],
                [make_step(1, 1, 2), make_step(2, 3, 3)],
                None,
            )
            try:
                with zipfile.ZipFile(archive_path) as zf:
                    manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["mode"], "session")
                self.assertEqual([s["step_index"] for s in manifest["steps"]], [1, 2])
                self.assertEqual(len(manifest["files"]), 2)
                self.assertEqual(len(manifest["steps"][0]["segments"]), 2)
                self.assertNotEqual(
                    manifest["steps"][0]["segments"][0]["file_index"],
                    manifest["steps"][0]["segments"][1]["file_index"],
                )
            finally:
                archive_path.unlink(missing_ok=True)

    def test_rejects_rollout_outside_codex_dir(self):
        with tempfile.TemporaryDirectory() as inside, tempfile.TemporaryDirectory() as outside:
            root = Path(inside)
            rollout = Path(outside) / "rollout.jsonl"
            write_bytes(rollout, json.dumps(event("e1")).encode() + b"\n")
            with self.assertRaises(server.RawExportError) as ctx:
                server._create_raw_export_zip(
                    root,
                    "thread",
                    [rollout],
                    [make_step(1, 1, 1)],
                    None,
                )
            self.assertEqual(ctx.exception.status, 409)

    def test_validates_step_indices(self):
        steps = [make_step(1, 1, 1), make_step(2, 2, 2)]
        self.assertIsNone(server._parse_raw_step_indices(None, steps))
        self.assertEqual(server._parse_raw_step_indices(["2,1"], steps), [1, 2])
        for value in ([""], ["1,1"], ["0"], ["3"], ["abc"]):
            with self.subTest(value=value):
                with self.assertRaises(server.RawExportError) as ctx:
                    server._parse_raw_step_indices(value, steps)
                self.assertEqual(ctx.exception.status, 400)


class RawExportStreamingTests(unittest.TestCase):
    def make_handler(self, writer):
        handler = object.__new__(server.MonitorHandler)
        handler.wfile = writer
        handler.sent = []
        handler.send_response = lambda status: handler.sent.append(("status", status))
        handler.send_header = lambda key, value: handler.sent.append((key, value))
        handler.end_headers = lambda: handler.sent.append(("headers", True))
        return handler

    def test_stream_removes_temp_file_after_success(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"zip-data")
            path = Path(handle.name)
        writer = io.BytesIO()
        handler = self.make_handler(writer)

        handler._send_zip_file(path, "session.zip")

        self.assertEqual(writer.getvalue(), b"zip-data")
        self.assertFalse(path.exists())
        self.assertIn(("Content-Type", "application/zip"), handler.sent)

    def test_stream_removes_temp_file_after_writer_error(self):
        class BrokenWriter:
            def write(self, _data):
                raise BrokenPipeError()

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"zip-data")
            path = Path(handle.name)
        handler = self.make_handler(BrokenWriter())

        handler._send_zip_file(path, "session.zip")

        self.assertFalse(path.exists())

    def test_stream_reports_json_error_when_file_cannot_be_opened_before_headers(self):
        missing = Path(tempfile.gettempdir()) / "missing-codex-raw-export.zip"
        missing.unlink(missing_ok=True)
        handler = self.make_handler(io.BytesIO())
        handler.errors = []
        handler._send_error_json = lambda message, status=400: handler.errors.append(
            (message, status)
        )

        handler._send_zip_file(missing, "session.zip")

        self.assertEqual(handler.errors[0][1], 500)
        self.assertFalse(any(item == ("status", 200) for item in handler.sent))


class RawExportHandlerTests(unittest.TestCase):
    def make_handler(self, path, config):
        handler = object.__new__(server.MonitorHandler)
        handler.path = path
        handler._load_own_config = lambda: config
        handler.responses = []
        handler._send_error_json = lambda message, status=400: handler.responses.append(
            (status, message)
        )
        return handler

    def test_endpoint_returns_409_when_live_session_has_no_rollout(self):
        source = {"id": "live", "kind": "live", "codex_dir": "C:/codex"}
        handler = self.make_handler(
            "/api/raw-export?source_id=live&session_id=session",
            {"sources": [source]},
        )
        with (
            mock.patch.object(
                server,
                "discover_live_sessions",
                return_value=[{"id": "session"}],
            ),
            mock.patch.object(server, "_raw_rollout_paths", return_value=[]),
        ):
            handler.do_GET()

        self.assertEqual(handler.responses[0][0], 409)

    def test_endpoint_converts_unexpected_zip_creation_error_to_json_500(self):
        source = {"id": "live", "kind": "live", "codex_dir": "C:/codex"}
        handler = self.make_handler(
            "/api/raw-export?source_id=live&session_id=session",
            {"sources": [source]},
        )
        with (
            mock.patch.object(
                server,
                "discover_live_sessions",
                return_value=[{"id": "session"}],
            ),
            mock.patch.object(
                server,
                "_raw_rollout_paths",
                return_value=[Path("rollout.jsonl")],
            ),
            mock.patch.object(
                server,
                "build_live_session_detail",
                return_value={"steps": []},
            ),
            mock.patch.object(
                server,
                "_create_raw_export_zip",
                side_effect=RuntimeError("disk full"),
            ),
        ):
            handler.do_GET()

        self.assertEqual(handler.responses, [(500, "Cannot create raw telemetry ZIP: disk full")])


class FrontendContractTests(unittest.TestCase):
    def test_raw_download_controls_and_guards_are_present(self):
        html = (ROOT / "static" / "codex-token-monitor" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "codex-token-monitor" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="rawSessionDownloadButton"', html)
        self.assertIn('id="rawSelectedDownloadButton"', html)
        self.assertIn("/api/raw-export", js)
        self.assertIn("URLSearchParams", js)
        self.assertIn('params.set("step_indices"', js)
        self.assertIn("raw_export_available", js)
        self.assertIn("Сначала выделите шаги", js)


if __name__ == "__main__":
    unittest.main()
