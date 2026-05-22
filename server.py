#!/usr/bin/env python3
"""Tiny static server for the team room with /topics.json auto-discovery.

Serves files from the directory it lives in (which start.sh stages with
viewer.html, index.html, and the topic JSONLs). Endpoints:

  GET  /topics.json         -> [{"name": "...", "mtime": ..., "size": ..., "last_role": "..."}, ...]
  GET  /status/<topic>      -> current iteration state for a topic (v2)
  POST /prompt              -> kick off an iteration (v2)
  POST /topic               -> create a new topic (v2)
"""

import datetime
import fcntl
import http.server
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOM_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

TOPIC_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
STALE_CRASH_SECONDS = 10 * 60  # 10 minutes


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso8601(ts: str) -> datetime.datetime | None:
    """Parse a `YYYY-MM-DDTHH:MM:SSZ` string. Returns None on failure."""
    if not ts:
        return None
    try:
        # Accept the trailing-Z form we always write; also tolerate `+00:00`.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _default_state() -> dict:
    return {
        "status": "idle",
        "prompt_id": None,
        "started_at": None,
        "orchestrator_pid": None,
        "claude_done": False,
        "codex_done": False,
        "last_error": None,
    }


def _state_paths(topic: str) -> tuple[Path, Path, Path]:
    """Return (state_json, state_lock, jsonl) paths for a topic."""
    return (
        ROOM_DIR / f"{topic}.state.json",
        ROOM_DIR / f"{topic}.state.lock",
        ROOM_DIR / f"{topic}.jsonl",
    )


def _read_state(state_json: Path) -> dict:
    """Read state file or return default-idle if missing/corrupt."""
    if not state_json.exists():
        return _default_state()
    try:
        with state_json.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return _default_state()


def _atomic_write_state(state_json: Path, payload: dict) -> None:
    """Atomic-replace state.json. Caller must hold the state lock."""
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{state_json.name}.",
        suffix=".tmp",
        dir=str(state_json.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, state_json)
    except Exception:
        # Best-effort cleanup if rename failed.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _process_alive(pid: int | None) -> bool:
    """Cheap liveness check — os.kill(pid, 0) raises if dead."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else; treat as alive.
        return True
    except OSError:
        return False


def _is_stale_crashed(state: dict) -> bool:
    """True iff state is non-idle, the orchestrator pid is dead, and the
    started_at timestamp is older than STALE_CRASH_SECONDS."""
    if state.get("status") in (None, "idle"):
        return False
    if _process_alive(state.get("orchestrator_pid")):
        return False
    started = _parse_iso8601(state.get("started_at") or "")
    if started is None:
        # No timestamp to age-check — refuse to mark stale yet; treat as alive.
        return False
    age = datetime.datetime.now(datetime.timezone.utc) - started
    return age.total_seconds() >= STALE_CRASH_SECONDS


def _find_repo_file(name: str) -> Path | None:
    """Locate a repo-root file (e.g. _append-jsonl.py, orchestrate.py).

    Tries ROOM_DIR first (dev: server.py running from repo root), then
    ROOM_DIR.parent (prod: start.sh staged server.py into .team-room/, while
    the helper python scripts stayed at the repo root)."""
    for candidate in (ROOM_DIR / name, ROOM_DIR.parent / name):
        if candidate.exists():
            return candidate
    return None


def _append_jsonl(topic_jsonl: Path, role: str, model: str, content: str,
                  prompt_id: str | None = None, round_n: int | None = None) -> None:
    """Append a message to a topic JSONL via the canonical locked appender."""
    appender = _find_repo_file("_append-jsonl.py")
    if appender is None:
        raise RuntimeError("_append-jsonl.py not found next to server.py")
    cmd = [sys.executable, str(appender), str(topic_jsonl), role, model, content]
    if round_n is not None:
        cmd += ["--round", str(round_n)]
    if prompt_id is not None:
        cmd += ["--prompt-id", prompt_id]
    subprocess.run(cmd, check=True)


def _spawn_orchestrator(topic: str, prompt_id: str, log_path: Path) -> int | None:
    """Spawn orchestrate.py detached. Returns the child PID, or None if the
    orchestrator script isn't available (test/dev fallback)."""
    orch = _find_repo_file("orchestrate.py")
    if orch is None:
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(orch), "--topic", topic, "--prompt-id", prompt_id],
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            cwd=str(ROOM_DIR),
        )
    finally:
        # Popen dup'd the fd; we can close ours.
        log_fh.close()
    return proc.pid


# ---------------------------------------------------------------------------
# topics.json (existing)
# ---------------------------------------------------------------------------


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
        # Read iteration status (shared lock) for input-lock UI hints.
        status = "idle"
        try:
            state_json, state_lock, _ = _state_paths(f.stem)
            if state_json.exists():
                with open(state_lock, "w") as lockf:
                    fcntl.flock(lockf, fcntl.LOCK_SH)
                    try:
                        status = _read_state(state_json).get("status", "idle")
                    finally:
                        fcntl.flock(lockf, fcntl.LOCK_UN)
        except OSError:
            pass
        out.append(
            {
                "name": f.stem,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "last_role": last_role,
                "last_ts": last_ts,
                "status": status,
            }
        )
    out.sort(key=lambda t: t["mtime"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


class Handler(http.server.SimpleHTTPRequestHandler):
    # --- response helpers --------------------------------------------------

    def _send_json(self, status: int, payload: dict, *, no_store: bool = True) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    # --- routing -----------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/topics.json":
            body = json.dumps(topics()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/status/"):
            topic = path[len("/status/"):]
            return self._handle_status(topic)
        # Default static-file behavior for everything else.
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/prompt":
            return self._handle_prompt()
        if path == "/topic":
            return self._handle_topic()
        self._send_json(404, {"error": "not found"})

    # --- /status/<topic> ---------------------------------------------------

    def _handle_status(self, topic: str):
        if not topic or not TOPIC_NAME_RE.match(topic):
            return self._send_json(400, {"error": "invalid topic name"})
        state_json, state_lock, _ = _state_paths(topic)
        # Use a shared lock for pure reads. Open the lock file in write mode
        # so we can create it if it doesn't exist (siblings may not yet).
        with open(state_lock, "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_SH)
            try:
                state = _read_state(state_json)
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)
        return self._send_json(200, state)

    # --- POST /prompt ------------------------------------------------------

    def _handle_prompt(self):
        data = self._read_json_body()
        if data is None:
            return self._send_json(400, {"error": "invalid json body"})

        topic = (data.get("topic") or "").strip()
        content = data.get("content")
        workspace = data.get("workspace")

        if not topic or not TOPIC_NAME_RE.match(topic):
            return self._send_json(400, {"error": "invalid topic name"})
        if not isinstance(content, str) or not content.strip():
            return self._send_json(400, {"error": "content required"})
        if workspace is not None and not isinstance(workspace, str):
            return self._send_json(400, {"error": "workspace must be a string"})

        state_json, state_lock, topic_jsonl = _state_paths(topic)
        workspace_json = ROOM_DIR / f"{topic}.workspace.json"
        log_path = ROOM_DIR / f"{topic}.orchestrate.log"

        with open(state_lock, "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                state = _read_state(state_json)
                stale_recovered = False

                if state.get("status") not in (None, "idle"):
                    if _is_stale_crashed(state):
                        # Recovery: emit a system message and reset state.
                        try:
                            _append_jsonl(
                                topic_jsonl,
                                role="system",
                                model="system",
                                content=(
                                    "orchestrator crashed mid-round "
                                    f"(pid={state.get('orchestrator_pid')}, "
                                    f"status={state.get('status')}, "
                                    f"started_at={state.get('started_at')}); "
                                    "resetting state to idle."
                                ),
                            )
                        except (subprocess.CalledProcessError, RuntimeError, OSError) as e:
                            # Don't block recovery on a logging failure.
                            sys.stderr.write(f"recovery log write failed: {e}\n")
                        # Persist the reset so even if we error below, we don't
                        # leave a phantom non-idle state behind.
                        _atomic_write_state(state_json, _default_state())
                        state = _default_state()
                        stale_recovered = True
                    else:
                        return self._send_json(
                            409,
                            {
                                "error": "iteration in progress",
                                "status": state.get("status"),
                            },
                        )

                # Workspace file creation (only if arg provided AND file missing).
                if workspace and not workspace_json.exists():
                    try:
                        _atomic_write_state(
                            workspace_json,
                            {
                                "workspace": workspace,
                                "created_at": _now_utc_iso(),
                            },
                        )
                    except OSError as e:
                        return self._send_json(
                            500, {"error": f"could not write workspace file: {e}"}
                        )

                prompt_id = secrets.token_hex(4)

                # Append Costa's message to the JSONL with the prompt_id so
                # the orchestrator (and viewer) can group the iteration.
                try:
                    _append_jsonl(
                        topic_jsonl,
                        role="costa",
                        model="human",
                        content=content,
                        prompt_id=prompt_id,
                    )
                except (subprocess.CalledProcessError, RuntimeError, OSError) as e:
                    return self._send_json(
                        500, {"error": f"could not append costa message: {e}"}
                    )

                # Spawn the orchestrator detached. Capture PID immediately.
                try:
                    pid = _spawn_orchestrator(topic, prompt_id, log_path)
                except OSError as e:
                    return self._send_json(
                        500, {"error": f"could not spawn orchestrator: {e}"}
                    )

                if pid is None:
                    # Orchestrate.py is not present yet (parallel impl). Surface
                    # this honestly: still log Costa's message, reset state to
                    # idle, return 202 but flag it so callers can notice during
                    # bring-up. This keeps testing of the lock/state machinery
                    # possible without orchestrate.py being shipped.
                    sys.stderr.write(
                        "warning: orchestrate.py not found; iteration not spawned\n"
                    )
                    new_state = _default_state()
                    new_state["last_error"] = "orchestrate.py not installed"
                    _atomic_write_state(state_json, new_state)
                    payload = {
                        "prompt_id": prompt_id,
                        "warning": "orchestrate.py not found; state left idle",
                    }
                    if stale_recovered:
                        payload["recovered_from_crash"] = True
                    return self._send_json(202, payload)

                # Persist the round-1 state atomically.
                new_state = {
                    "status": "round-1",
                    "prompt_id": prompt_id,
                    "started_at": _now_utc_iso(),
                    "orchestrator_pid": pid,
                    "claude_done": False,
                    "codex_done": False,
                    "last_error": None,
                }
                try:
                    _atomic_write_state(state_json, new_state)
                except OSError as e:
                    # Try to clean up the orphaned orchestrator so it doesn't
                    # run with no state record.
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        pass
                    return self._send_json(
                        500, {"error": f"could not write state: {e}"}
                    )

                payload = {"prompt_id": prompt_id}
                if stale_recovered:
                    payload["recovered_from_crash"] = True
                return self._send_json(202, payload)
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    # --- POST /topic -------------------------------------------------------

    def _handle_topic(self):
        data = self._read_json_body()
        if data is None:
            return self._send_json(400, {"error": "invalid json body"})

        name = (data.get("name") or "").strip()
        workspace = data.get("workspace")

        if not name or not TOPIC_NAME_RE.match(name):
            return self._send_json(400, {"error": "invalid topic name"})
        if workspace is not None and not isinstance(workspace, str):
            return self._send_json(400, {"error": "workspace must be a string"})

        topic_jsonl = ROOM_DIR / f"{name}.jsonl"
        workspace_json = ROOM_DIR / f"{name}.workspace.json"

        try:
            # Touch — preserves any existing transcript intentionally.
            topic_jsonl.touch(exist_ok=True)
        except OSError as e:
            return self._send_json(
                500, {"error": f"could not create topic jsonl: {e}"}
            )

        if not workspace_json.exists():
            ws_path = workspace or os.environ.get("HOME") or "/"
            try:
                _atomic_write_state(
                    workspace_json,
                    {
                        "workspace": ws_path,
                        "created_at": _now_utc_iso(),
                    },
                )
            except OSError as e:
                return self._send_json(
                    500, {"error": f"could not write workspace file: {e}"}
                )

        return self._send_json(
            201,
            {"name": name, "url": f"/viewer.html?topic={name}"},
        )

    # --- logging -----------------------------------------------------------

    def log_message(self, fmt, *args):
        # Quieter than the stdlib default; only print non-OK responses.
        if args and isinstance(args[1], str) and args[1].startswith("2"):
            return
        super().log_message(fmt, *args)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


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
