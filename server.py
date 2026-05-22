#!/usr/bin/env python3
"""Tiny static server for the team room with /topics.json auto-discovery.

Serves files from the directory it lives in (which start.sh stages with
viewer.html, index.html, and the topic JSONLs). Adds one endpoint:

  GET /topics.json  ->  [{"name": "...", "mtime": ..., "size": ..., "last_role": "..."}, ...]
"""

import http.server
import json
import os
import sys
from pathlib import Path

ROOM_DIR = Path(__file__).resolve().parent


def topics():
    out = []
    for f in sorted(ROOM_DIR.glob("*.jsonl")):
        try:
            stat = f.stat()
        except FileNotFoundError:
            continue
        last_role = ""
        last_ts = ""
        try:
            with f.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                if size > 0:
                    # Read up to last 8KB to grab the final line cheaply.
                    fh.seek(max(0, size - 8192))
                    chunk = fh.read().splitlines()
                    for line in reversed(chunk):
                        if not line.strip():
                            continue
                        try:
                            msg = json.loads(line)
                            last_role = msg.get("role", "")
                            last_ts = msg.get("ts", "")
                            break
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass
        out.append(
            {
                "name": f.stem,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "last_role": last_role,
                "last_ts": last_ts,
            }
        )
    out.sort(key=lambda t: t["mtime"], reverse=True)
    return out


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] == "/topics.json":
            body = json.dumps(topics()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # Default static-file behavior for everything else.
        return super().do_GET()

    def log_message(self, fmt, *args):
        # Quieter than the stdlib default; only print non-OK responses.
        if args and isinstance(args[1], str) and args[1].startswith("2"):
            return
        super().log_message(fmt, *args)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    os.chdir(ROOM_DIR)
    server = http.server.ThreadingHTTPServer(("", port), Handler)
    print(f"Team room serving on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
