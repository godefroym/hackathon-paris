#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Mock local server for fact-check stream. "
            "Receives POST /api/stream/fact-check and prints payloads."
        )
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument(
        "--path",
        default="/api/stream/fact-check",
        help="Expected POST path (default: /api/stream/fact-check)",
    )
    parser.add_argument(
        "--output-jsonl",
        default="",
        help="Optional JSONL file to append received payloads",
    )
    return parser.parse_args()


def format_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def make_handler(expected_path: str, output_jsonl: str):
    output_path = Path(output_jsonl) if output_jsonl else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: Any) -> None:
            return

        def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != expected_path:
                self._write_json(
                    404,
                    {
                        "ok": False,
                        "error": "unexpected_path",
                        "expected_path": expected_path,
                        "received_path": self.path,
                    },
                )
                return

            raw_length = self.headers.get("Content-Length", "0")
            try:
                body_length = int(raw_length)
            except ValueError:
                body_length = 0

            raw_bytes = self.rfile.read(max(body_length, 0))
            raw_text = raw_bytes.decode("utf-8", errors="replace")

            parsed_payload: dict[str, Any] | None = None
            parse_error = ""
            try:
                maybe_payload = json.loads(raw_text) if raw_text else {}
                if isinstance(maybe_payload, dict):
                    parsed_payload = maybe_payload
                else:
                    parsed_payload = {"value": maybe_payload}
            except json.JSONDecodeError as exc:
                parse_error = str(exc)

            print("\n[mock-fact-check-receiver]")
            print(f"time_utc={format_utc_now()} path={self.path}")
            if parse_error:
                print(f"invalid_json={parse_error}")
                print(f"raw={raw_text}")
            else:
                print(json.dumps(parsed_payload, ensure_ascii=False, indent=2))

            if output_path and parsed_payload is not None:
                with output_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(parsed_payload, ensure_ascii=False) + "\n")

            self._write_json(
                200,
                {
                    "ok": True,
                    "received_path": self.path,
                    "timestamp_utc": format_utc_now(),
                    "parse_error": parse_error or None,
                },
            )

    return Handler


def main() -> int:
    args = parse_args()
    handler = make_handler(args.path, args.output_jsonl)
    server = ReusableThreadingHTTPServer((args.host, args.port), handler)
    print(
        "[mock-fact-check-receiver] listening "
        f"http://{args.host}:{args.port}{args.path}"
    )
    if args.output_jsonl:
        print(f"[mock-fact-check-receiver] writing JSONL to {args.output_jsonl}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock-fact-check-receiver] stop requested (Ctrl+C)")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
