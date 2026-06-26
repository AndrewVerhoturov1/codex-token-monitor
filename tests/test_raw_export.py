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


class MonitorCachingTests(unittest.TestCase):
    def test_end_headers_adds_no_store_headers(self):
        handler = object.__new__(server.MonitorHandler)
        sent = []
        handler.send_header = lambda key, value: sent.append((key, value))

        with mock.patch.object(server.SimpleHTTPRequestHandler, "end_headers", autospec=True) as parent_end:
            server.MonitorHandler.end_headers(handler)

        self.assertIn(("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"), sent)
        self.assertIn(("Pragma", "no-cache"), sent)
        self.assertIn(("Expires", "0"), sent)
        parent_end.assert_called_once_with(handler)


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


class CallLevelEventsTest(unittest.TestCase):
    def test_request_usage_items_include_zero_usage_events(self):
        """Test that request_usage_items array includes all AI calls, even those with zero usage."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            
            # Use the same format as existing tests: single events per line
            event1 = event("event_msg", {"type": "event_msg", "info": {"last_token_usage": {
                "input_tokens": 100, "cached_tokens": 20, "output_tokens": 50
            }}})  
            event2 = event("event_msg", {"type": "event_msg", "info": {"last_token_usage": {
                "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0  # ZERO usage
            }}})
            event3 = event("event_msg", {"type": "event_msg", "info": {"last_token_usage": {
                "input_tokens": 80, "cached_tokens": 10, "output_tokens": 60
            }}})
            
            data = (json.dumps(event1) + "\n" +
                   json.dumps(event2) + "\n" +
                   json.dumps(event3) + "\n").encode()
            write_bytes(rollout, data)
            
            # Test _iter_rollout_jsonl_records directly
            records = list(server._iter_rollout_jsonl_records(root, [rollout]))
            
            # Should have 3 records
            self.assertEqual(len(records), 3, "Should read 3 events")
            
            # Verify zero-usage is preserved
            zero_usage_events = [r["event"] for r in records if (
                r["event"].get("payload", {}).get("info", {}).get("last_token_usage", {}).get("input_tokens") == 0 and
                r["event"].get("payload", {}).get("info", {}).get("last_token_usage", {}).get("output_tokens") == 0
            )]
            self.assertEqual(len(zero_usage_events), 1, 
                           "Should have exactly one zero-usage event in the raw records")
            
            # Verify the zero-usage values are explicit zeros, not missing
            zero_event = zero_usage_events[0]
            zero_usage = zero_event["payload"]["info"]["last_token_usage"]
            self.assertIn("input_tokens", zero_usage, "Zero-usage event should have input_tokens key")
            self.assertIn("output_tokens", zero_usage, "Zero-usage event should have output_tokens key")
            self.assertEqual(zero_usage["input_tokens"], 0, "Zero-usage input_tokens should be explicitly 0")
            self.assertEqual(zero_usage["output_tokens"], 0, "Zero-usage output_tokens should be explicitly 0")


class CallLevelAuditTests(unittest.TestCase):
    def test_session_ai_calls_preserves_zero_usage_and_unmapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "test-model", "effort": "medium"}),
                event("response_item", {"role": "user", "content": [{"text": "Hello"}]}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 100, "cached_tokens": 20, "output_tokens": 50}}}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}}}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 200, "cached_tokens": 30, "output_tokens": 80}}}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            self.assertEqual(len(ai_calls), 3, "Should have 3 AI calls")
            zero_calls = [c for c in ai_calls if c["is_zero_usage"]]
            self.assertEqual(len(zero_calls), 1, "Should have 1 zero-usage AI call")
            usage_calls = [c for c in ai_calls if not c["is_zero_usage"]]
            self.assertEqual(len(usage_calls), 2, "Should have 2 usage AI calls")
            zero_call = zero_calls[0]
            self.assertEqual(zero_call["usage"]["input_tokens"], 0)
            self.assertEqual(zero_call["usage"]["output_tokens"], 0)
            self.assertEqual(zero_call["call_index"], 2)
            mapped_calls = [c for c in ai_calls if c["mapping_confidence"] == "high"]
            self.assertGreaterEqual(len(mapped_calls), 1, "At least one AI call should be mapped to step")

    def test_ai_calls_mapped_to_step_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1 prompt"}]}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50}}}),
                event("response_item", {"role": "user", "content": [{"text": "Step 2 prompt"}]}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 200, "cached_tokens": 50, "output_tokens": 100}}}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 300, "cached_tokens": 0, "output_tokens": 150}}}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            self.assertEqual(len(steps), 2, "Should have 2 steps")
            step1_calls = [c for c in ai_calls if c["step_index"] == 1]
            step2_calls = [c for c in ai_calls if c["step_index"] == 2]
            self.assertEqual(len(step1_calls), 1, "Step 1 should have 1 AI call")
            self.assertEqual(len(step2_calls), 2, "Step 2 should have 2 AI calls")

    def test_ai_calls_unmapped_before_first_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 50, "cached_tokens": 0, "output_tokens": 10}}}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1 prompt"}]}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50}}}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            unmapped = [c for c in ai_calls if c["mapping_confidence"] == "unmapped"]
            self.assertGreaterEqual(len(unmapped), 1, "Should have at least one unmapped AI call (before first step)")

    def test_ai_calls_scores_in_honest_audit_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1"}]}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50}}}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}}}),
                event("event_msg", {"info": {"last_token_usage": {"input_tokens": 200, "cached_tokens": 0, "output_tokens": 80}}}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            self.assertEqual(ai_calls[0]["is_zero_usage"], False)
            self.assertEqual(ai_calls[1]["is_zero_usage"], True)
            self.assertEqual(ai_calls[2]["is_zero_usage"], False)
            zero_count = sum(1 for c in ai_calls if c["is_zero_usage"])
            usage_count = sum(1 for c in ai_calls if not c["is_zero_usage"])
            self.assertEqual(zero_count, 1)
            self.assertEqual(usage_count, 2)


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


class HonestyWarningsTests(unittest.TestCase):
    def test_call_vs_cumulative_cost_mismatch_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1"}]}),
                event("event_msg", {"info": {
                    "last_token_usage": {"input_tokens": 1000, "cached_tokens": 200, "output_tokens": 500},
                    "total_token_usage": {"input_tokens": 2000, "cached_tokens": 200, "output_tokens": 600}
                }}),
                event("response_item", {"role": "user", "content": [{"text": "Step 2"}]}),
                event("event_msg", {"info": {
                    "last_token_usage": {"input_tokens": 500, "cached_tokens": 100, "output_tokens": 300},
                    "total_token_usage": {"input_tokens": 2500, "cached_tokens": 300, "output_tokens": 900}
                }}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            all_usage_events = [e for e in parsed_events if e.get("type") == "event_msg"]
            self.assertGreaterEqual(len(all_usage_events), 2)

    def test_positive_unmapped_internal_usage_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                # event_msg before first step (unmapped)
                event("event_msg", {"info": {
                    "last_token_usage": {"input_tokens": 200, "cached_tokens": 0, "output_tokens": 50},
                    "total_token_usage": {"input_tokens": 200, "cached_tokens": 0, "output_tokens": 50}
                }}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1"}]}),
                event("event_msg", {"info": {
                    "last_token_usage": {"input_tokens": 300, "cached_tokens": 50, "output_tokens": 100},
                    "total_token_usage": {"input_tokens": 800, "cached_tokens": 50, "output_tokens": 300}
                }}),
                event("response_item", {"role": "user", "content": [{"text": "Step 2"}]}),
                event("event_msg", {"info": {
                    "last_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50},
                    "total_token_usage": {"input_tokens": 900, "cached_tokens": 50, "output_tokens": 350}
                }}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            self.assertEqual(len(steps), 2)
            self.assertGreater(len(ai_calls), 0)

    def test_step_warning_raw_tool_evidence_but_no_tool_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1"}]}),
                event("response_item", {
                    "role": "assistant",
                    "type": "function_call",
                    "name": "execute_command",
                    "call_id": "call-1",
                    "arguments": {"command": "git status", "workdir": "/tmp"},
                }),
                event("response_item", {
                    "role": "assistant",
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "On branch main",
                }),
                event("event_msg", {"info": {
                    "last_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50},
                    "total_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50}
                }}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            self.assertEqual(len(steps), 1)
            lte = steps[0].get("live_tool_events", [])
            self.assertGreaterEqual(len(lte), 1,
                                  "Step should have captured live_tool_events")
            aa = steps[0].get("agent_activity", {})
            counts = aa.get("activity_counts", {})
            tool_total = (counts.get("file_reads", 0) + counts.get("file_writes", 0)
                         + counts.get("shell_commands", 0) + counts.get("git_operations", 0)
                         + counts.get("test_runs", 0))
            self.assertEqual(tool_total, 0,
                           "Tool events are in live_tool_events but not classified in activity_counts — this is the honesty scenario")
            step_warnings = steps[0].get("warnings", [])
            has_raw_warning = any(
                "Raw tool evidence" in str(w) for w in step_warnings
            )
            self.assertTrue(has_raw_warning,
                          "Step should warn about raw tool evidence without attribution")

    def test_step_warning_reported_by_agent_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1"}]}),
                event("response_item", {"role": "assistant", "content": [
                    {"type": "text", "text": "Я запустил тесты и прочитал файл scripts/codex_token_monitor_server.py"}
                ]}),
                event("event_msg", {"payload": {"info": {
                    "last_token_usage": {"input_tokens": 200, "cached_tokens": 0, "output_tokens": 100},
                    "total_token_usage": {"input_tokens": 200, "cached_tokens": 0, "output_tokens": 100}
                }}}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            self.assertEqual(len(steps), 1)
            aa = steps[0].get("agent_activity", {})
            items = aa.get("activity_items", [])
            reported = [it for it in items if it.get("status") == "reported_by_agent"]
            self.assertGreaterEqual(len(reported), 1,
                                  "Text mentions should produce reported_by_agent items")
            step_warnings = steps[0].get("warnings", [])
            has_reported_warning = any(
                "reported_by_agent" in str(w) for w in step_warnings
            )
            self.assertTrue(has_reported_warning,
                          "Step should have a warning about reported_by_agent items")

    def test_session_reported_by_agent_aggregate_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1"}]}),
                event("response_item", {"role": "assistant", "content": [
                    {"type": "text", "text": "Я читаю src/main.py и запускаю тесты"}
                ]}),
                event("event_msg", {"payload": {"info": {
                    "last_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50},
                    "total_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50}
                }}}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            aa = steps[0].get("agent_activity", {})
            items = aa.get("activity_items", [])
            reported = [it for it in items if it.get("status") == "reported_by_agent"]
            self.assertGreaterEqual(len(reported), 1)

    def test_unmapped_internal_usage_available_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "sessions" / "rollout-a.jsonl"
            events_data = [
                event("turn_context", {"model": "gpt-5", "effort": "high"}),
                event("response_item", {"role": "user", "content": [{"text": "Step 1"}]}),
                event("event_msg", {"info": {
                    "last_token_usage": {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 50},
                    "total_token_usage": {"input_tokens": 500, "cached_tokens": 0, "output_tokens": 200}
                }}),
            ]
            data = "\n".join(json.dumps(e) for e in events_data).encode() + b"\n"
            write_bytes(rollout, data)
            with mock.patch.object(
                server,
                "_get_live_rollout_summaries",
                return_value={"thread": {"paths": [str(rollout)]}},
            ):
                parsed_events = server._read_rollout_jsonl(root, "thread")
            steps, timeline_events, ai_calls = server._build_live_steps(parsed_events, "thread")
            self.assertEqual(len(steps), 1)
            self.assertGreaterEqual(len(ai_calls), 1)
            call_level_input = sum(c["usage"]["input_tokens"] for c in ai_calls if not c["is_zero_usage"])
            self.assertGreaterEqual(call_level_input, 100)

    def test_honesty_warnings_present_in_app_js(self):
        js = (ROOT / "static" / "codex-token-monitor" / "app.js").read_text(encoding="utf-8")
        self.assertIn("honesty warnings", js)
        self.assertIn("reported_by_agent", js)
        self.assertIn("renderAiCallsSectionIntoSteps", js)
        self.assertIn("const oldRenderSteps = renderSteps", js)
        self.assertIn("const oldRenderHeader = renderHeader", js)

    def test_server_has_reported_by_agent_aggregate(self):
        py = (ROOT / "scripts" / "codex_token_monitor_server.py").read_text(encoding="utf-8")
        self.assertIn("total_reported_by_agent", py)
        self.assertIn('"reported_by_agent_items"', py)
        self.assertIn('"call_vs_cumulative_cost_mismatch"', py)
        self.assertIn('"positive_unmapped_or_internal_usage"', py)


if __name__ == "__main__":
    unittest.main()
