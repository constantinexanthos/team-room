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

ROOM_DIR = Path(os.environ.get("TEAM_ROOM_DIR", Path(__file__).resolve().parent))

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
# Projects (v3)
# ---------------------------------------------------------------------------

PROJECT_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
RECENTS_LIMIT = 10


def _project_path(project_id: str) -> Path:
    return ROOM_DIR / f"{project_id}.project.json"


def _topic_meta_path(topic_id: str) -> Path:
    return ROOM_DIR / f"{topic_id}.topic.json"


def _slugify_workspace(workspace: str) -> str:
    """Derive a stable slug from the workspace dir basename."""
    base = os.path.basename(os.path.normpath(workspace)).lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", base).strip("-")
    return slug or "project"


def _parse_github_url(url: str) -> tuple[str, str] | None:
    """Parse a github URL or ssh remote into (owner, repo). Returns None on bad input."""
    if not url:
        return None
    u = url.strip()
    if u.startswith("git@"):
        # git@github.com:owner/repo.git -> github.com:owner/repo
        u = u[4:].replace(":", "/", 1)
        u = "https://" + u
    if u.endswith(".git"):
        u = u[:-4]
    if u.endswith("/"):
        u = u[:-1]
    # Now expect https://github.com/owner/repo (or similar host)
    m = re.match(r"^https?://[^/]+/([^/]+)/([^/]+)$", u)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if not owner or not repo:
        return None
    return owner, repo


def _default_clone_path(owner: str, repo: str) -> str:
    """Default location for a fresh clone."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    base = Path(home) / "team-room-clones"
    return str(base / f"{owner}-{repo}")


def _git_remote_matches(workspace: str, url: str) -> bool:
    """True if the workspace's origin URL points at the same repo as `url`."""
    have = _detect_git_remote(workspace)
    if not have:
        return False
    want_parsed = _parse_github_url(url)
    have_parsed = _parse_github_url(have)
    if not want_parsed or not have_parsed:
        return have == url
    return want_parsed == have_parsed


def _clone_repo(url: str, dest: str, timeout: int = 120) -> tuple[bool, str]:
    """Run `git clone <url> <dest>`. Returns (ok, error_message)."""
    parent = os.path.dirname(dest)
    try:
        Path(parent).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"could not create parent dir {parent}: {e}"
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "50", url, dest],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"git clone timed out after {timeout}s"
    except OSError as e:
        return False, f"git clone failed to start: {e}"
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}"
        return False, f"git clone failed: {err}"
    return True, ""


def _detect_git_remote(workspace: str) -> str | None:
    """Best-effort: read origin URL from `git -C <workspace> remote get-url origin`."""
    try:
        proc = subprocess.run(
            ["git", "-C", workspace, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return None
        url = proc.stdout.strip()
        if not url:
            return None
        # Normalize git@github.com:foo/bar.git → https://github.com/foo/bar
        if url.startswith("git@"):
            host_path = url[4:].replace(":", "/", 1)
            url = f"https://{host_path}"
        if url.endswith(".git"):
            url = url[:-4]
        return url
    except (OSError, subprocess.TimeoutExpired):
        return None


def _load_project(project_id: str) -> dict | None:
    p = _project_path(project_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_project(project: dict) -> None:
    p = _project_path(project["id"])
    _atomic_write_state(p, project)


def _all_projects() -> list[dict]:
    out = []
    for p in ROOM_DIR.glob("*.project.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def _load_topic_meta(topic_id: str) -> dict | None:
    p = _topic_meta_path(topic_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_topic_meta(topic_meta: dict) -> None:
    _atomic_write_state(_topic_meta_path(topic_meta["id"]), topic_meta)


def _ensure_unique_project_id(base_slug: str) -> str:
    """Pick a project id that doesn't collide with an existing project file."""
    candidate = base_slug
    n = 2
    while _project_path(candidate).exists():
        candidate = f"{base_slug}-{n}"
        n += 1
    return candidate


def _project_topic_count(project_id: str) -> int:
    count = 0
    for p in ROOM_DIR.glob("*.topic.json"):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
            if meta.get("project_id") == project_id:
                count += 1
        except (OSError, json.JSONDecodeError):
            continue
    return count


def _topics_for_project(project_id: str) -> list[dict]:
    """Return list of topic dicts (with last_message_at / last_role / status) for a project."""
    out = []
    for p in sorted(ROOM_DIR.glob("*.topic.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("project_id") != project_id:
            continue
        topic_id = meta["id"]
        jsonl = ROOM_DIR / f"{topic_id}.jsonl"
        last_ts = None
        last_role = None
        msg_count = 0
        if jsonl.exists():
            try:
                with jsonl.open("rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    if size > 0:
                        # Count lines (cheap) and grab last role/ts from final line.
                        fh.seek(0)
                        for line in fh:
                            if line.strip():
                                msg_count += 1
                        fh.seek(max(0, size - 8192))
                        chunk = fh.read().splitlines()
                        for line in reversed(chunk):
                            if not line.strip():
                                continue
                            try:
                                msg = json.loads(line)
                                last_role = msg.get("role")
                                last_ts = msg.get("ts")
                                break
                            except json.JSONDecodeError:
                                continue
            except OSError:
                pass
        # Status (cheap shared-lock read)
        status = "idle"
        try:
            state_json, state_lock, _ = _state_paths(topic_id)
            if state_json.exists():
                with open(state_lock, "w") as lockf:
                    fcntl.flock(lockf, fcntl.LOCK_SH)
                    try:
                        status = _read_state(state_json).get("status", "idle")
                    finally:
                        fcntl.flock(lockf, fcntl.LOCK_UN)
        except OSError:
            pass
        out.append({
            "id": topic_id,
            "project_id": project_id,
            "created_at": meta.get("created_at"),
            "last_message_at": last_ts,
            "last_role": last_role,
            "message_count": msg_count,
            "status": status,
        })
    out.sort(key=lambda t: (t["last_message_at"] or t["created_at"] or ""), reverse=True)
    return out


def _migrate_legacy_topics_if_needed() -> None:
    """If no projects exist but topics do, create a 'legacy' project and bind all
    orphaned topics to it. Idempotent and cheap on subsequent boots."""
    if any(ROOM_DIR.glob("*.project.json")):
        return
    orphan_jsonls = list(ROOM_DIR.glob("*.jsonl"))
    if not orphan_jsonls:
        return

    legacy = {
        "id": "legacy",
        "name": "Legacy",
        "workspace": os.environ.get("HOME") or "/",
        "github_url": None,
        "created_at": _now_utc_iso(),
        "last_opened_at": _now_utc_iso(),
    }
    _save_project(legacy)

    for jsonl in orphan_jsonls:
        topic_id = jsonl.stem
        if _load_topic_meta(topic_id) is not None:
            continue
        _save_topic_meta({
            "id": topic_id,
            "project_id": "legacy",
            "created_at": _now_utc_iso(),
        })


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
        full_path = self.path
        path = full_path.split("?", 1)[0]
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
        # v3 — projects + topics
        if path == "/projects":
            return self._handle_list_projects()
        if path.startswith("/projects/"):
            rest = path[len("/projects/"):]
            return self._handle_get_project(rest)
        if path == "/recents":
            return self._handle_recents()
        if path == "/health":
            return self._handle_health()
        if path == "/topics":
            qs = full_path.split("?", 1)[1] if "?" in full_path else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p) if qs else {}
            project_id = params.get("project_id")
            return self._handle_list_topics(project_id)
        # Default static-file behavior (serves the React app from dist/)
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/prompt":
            return self._handle_prompt()
        if path == "/topic":
            return self._handle_topic()
        if path == "/projects":
            return self._handle_create_project()
        if path == "/projects/from-github":
            return self._handle_create_from_github()
        if path.startswith("/projects/") and path.endswith("/open"):
            project_id = path[len("/projects/"):-len("/open")]
            return self._handle_open_project(project_id)
        self._send_json(404, {"error": "not found"})

    def do_PATCH(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/projects/"):
            project_id = path[len("/projects/"):]
            return self._handle_patch_project(project_id)
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/projects/"):
            project_id = path[len("/projects/"):]
            return self._handle_delete_project(project_id)
        if path.startswith("/topics/"):
            topic_id = path[len("/topics/"):]
            return self._handle_delete_topic(topic_id)
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

    # --- Projects (v3) -----------------------------------------------------

    def _handle_list_projects(self):
        projects = _all_projects()
        for p in projects:
            p["topic_count"] = _project_topic_count(p["id"])
        projects.sort(key=lambda p: p.get("last_opened_at") or "", reverse=True)
        return self._send_json(200, projects)

    def _handle_recents(self):
        projects = _all_projects()
        projects.sort(key=lambda p: p.get("last_opened_at") or "", reverse=True)
        return self._send_json(200, projects[:RECENTS_LIMIT])

    def _handle_health(self):
        """Probe the local Claude + Codex CLIs. Tells the UI whether the
        agents are actually reachable so users know responses come from
        their local subscriptions, not from us."""

        def probe(cmd: list[str]) -> dict:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=5,
                )
                if proc.returncode != 0:
                    return {"ok": False, "version": None, "error": (proc.stderr or proc.stdout or "").strip()[:200]}
                version = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
                return {"ok": True, "version": version, "error": None}
            except FileNotFoundError:
                return {"ok": False, "version": None, "error": "CLI not found on PATH"}
            except subprocess.TimeoutExpired:
                return {"ok": False, "version": None, "error": "version probe timed out"}
            except OSError as e:
                return {"ok": False, "version": None, "error": str(e)}

        return self._send_json(200, {
            "claude": probe(["claude", "--version"]),
            "codex": probe(["codex", "--version"]),
        }, no_store=True)

    def _handle_get_project(self, project_id: str):
        if not project_id or not PROJECT_ID_RE.match(project_id):
            return self._send_json(400, {"error": "invalid project id"})
        project = _load_project(project_id)
        if project is None:
            return self._send_json(404, {"error": "project not found"})
        project["topic_count"] = _project_topic_count(project_id)
        topics_list = _topics_for_project(project_id)
        return self._send_json(200, {"project": project, "topics": topics_list})

    def _handle_create_project(self):
        data = self._read_json_body()
        if data is None:
            return self._send_json(400, {"error": "invalid json body"})

        workspace = data.get("workspace")
        if not isinstance(workspace, str) or not workspace.strip():
            return self._send_json(400, {"error": "workspace required"})
        workspace = os.path.expanduser(workspace)
        if not os.path.isdir(workspace):
            return self._send_json(400, {"error": f"workspace is not a directory: {workspace}"})

        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            name = os.path.basename(os.path.normpath(workspace)) or "project"

        github_url = data.get("github_url")
        if not isinstance(github_url, str) or not github_url.strip():
            github_url = _detect_git_remote(workspace)

        base_slug = _slugify_workspace(workspace)
        project_id = _ensure_unique_project_id(base_slug)
        now = _now_utc_iso()
        project = {
            "id": project_id,
            "name": name.strip(),
            "workspace": workspace,
            "github_url": github_url,
            "created_at": now,
            "last_opened_at": now,
        }
        _save_project(project)
        project["topic_count"] = 0
        return self._send_json(201, project)

    def _handle_create_from_github(self):
        """Create a project from a GitHub URL.

        Body: {github_url: required, target_dir: optional, name: optional}

        Behavior:
          1. If target_dir provided AND exists as a git repo whose origin matches
             github_url -> reuse it; no clone.
          2. If target_dir provided AND does not exist -> clone there.
          3. If target_dir omitted -> derive ~/team-room-clones/<owner>-<repo>;
             reuse if existing+matching, else clone.
        """
        data = self._read_json_body()
        if data is None:
            return self._send_json(400, {"error": "invalid json body"})

        github_url = data.get("github_url")
        if not isinstance(github_url, str) or not github_url.strip():
            return self._send_json(400, {"error": "github_url required"})
        github_url = github_url.strip()

        parsed = _parse_github_url(github_url)
        if parsed is None:
            return self._send_json(
                400,
                {"error": "could not parse GitHub URL; expected https://github.com/owner/repo"},
            )
        owner, repo = parsed

        target_dir = data.get("target_dir")
        if target_dir is not None and not isinstance(target_dir, str):
            return self._send_json(400, {"error": "target_dir must be a string"})
        if not target_dir:
            target_dir = _default_clone_path(owner, repo)
        target_dir = os.path.expanduser(target_dir)

        if os.path.isdir(target_dir):
            # Existing dir — must be a git repo whose origin matches.
            if not os.path.isdir(os.path.join(target_dir, ".git")):
                return self._send_json(
                    409,
                    {
                        "error": f"target_dir {target_dir} exists but is not a git repo; "
                        "either delete it, point at the correct local clone, or pick a different target_dir.",
                    },
                )
            if not _git_remote_matches(target_dir, github_url):
                actual = _detect_git_remote(target_dir) or "(no origin)"
                return self._send_json(
                    409,
                    {
                        "error": f"target_dir {target_dir} is a git repo but origin is {actual}, "
                        f"not the requested {github_url}.",
                    },
                )
            # Reuse existing clone.
        else:
            # Clone fresh.
            ok, err = _clone_repo(github_url, target_dir)
            if not ok:
                return self._send_json(500, {"error": err})

        # Build the project via the normal create flow.
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            name = repo

        base_slug = _slugify_workspace(target_dir)
        project_id = _ensure_unique_project_id(base_slug)
        now = _now_utc_iso()
        project = {
            "id": project_id,
            "name": name.strip(),
            "workspace": target_dir,
            "github_url": github_url,
            "created_at": now,
            "last_opened_at": now,
        }
        _save_project(project)
        project["topic_count"] = 0
        return self._send_json(201, project)

    def _handle_patch_project(self, project_id: str):
        if not PROJECT_ID_RE.match(project_id):
            return self._send_json(400, {"error": "invalid project id"})
        project = _load_project(project_id)
        if project is None:
            return self._send_json(404, {"error": "project not found"})
        data = self._read_json_body()
        if data is None:
            return self._send_json(400, {"error": "invalid json body"})

        for field in ("name", "workspace", "github_url"):
            if field in data:
                value = data[field]
                if field == "workspace":
                    if not isinstance(value, str) or not value.strip():
                        return self._send_json(400, {"error": "workspace must be a non-empty string"})
                    expanded = os.path.expanduser(value)
                    if not os.path.isdir(expanded):
                        return self._send_json(400, {"error": f"workspace not a directory: {expanded}"})
                    project[field] = expanded
                elif value is None or isinstance(value, str):
                    project[field] = value
                else:
                    return self._send_json(400, {"error": f"{field} must be string or null"})
        _save_project(project)
        project["topic_count"] = _project_topic_count(project_id)
        return self._send_json(200, project)

    def _handle_delete_project(self, project_id: str):
        if not PROJECT_ID_RE.match(project_id):
            return self._send_json(400, {"error": "invalid project id"})
        p = _project_path(project_id)
        if not p.exists():
            return self._send_json(404, {"error": "project not found"})
        try:
            p.unlink()
        except OSError as e:
            return self._send_json(500, {"error": f"could not delete: {e}"})
        # Topics' meta files stay (orphaned). User can reassign later.
        self.send_response(204)
        self.end_headers()

    def _handle_delete_topic(self, topic_id: str):
        """Delete a topic: its JSONL transcript, meta file, state, workspace,
        orchestrator log, and locks. Refuses if an iteration is in flight."""
        if not topic_id or not TOPIC_NAME_RE.match(topic_id):
            return self._send_json(400, {"error": "invalid topic id"})
        # Check state — refuse if a round is in flight.
        state_json, state_lock, jsonl = _state_paths(topic_id)
        if state_json.exists():
            try:
                state = _read_state(state_json)
                if state.get("status") not in (None, "idle") and not _is_stale_crashed(state):
                    return self._send_json(409, {"error": "iteration in flight; wait for it to finish"})
            except OSError:
                pass
        # Delete everything for this topic
        room = ROOM_DIR
        candidates = [
            jsonl,
            state_json,
            state_lock,
            room / f"{topic_id}.state.json.tmp",
            room / f"{topic_id}.workspace.json",
            room / f"{topic_id}.orchestrate.log",
            room / f"{topic_id}.jsonl.lock",
            _topic_meta_path(topic_id),
        ]
        errors = []
        for path in candidates:
            try:
                if path.exists():
                    path.unlink()
            except OSError as e:
                errors.append(f"{path.name}: {e}")
        if errors:
            return self._send_json(500, {"error": "; ".join(errors)})
        self.send_response(204)
        self.end_headers()

    def _handle_open_project(self, project_id: str):
        if not PROJECT_ID_RE.match(project_id):
            return self._send_json(400, {"error": "invalid project id"})
        project = _load_project(project_id)
        if project is None:
            return self._send_json(404, {"error": "project not found"})
        project["last_opened_at"] = _now_utc_iso()
        _save_project(project)
        project["topic_count"] = _project_topic_count(project_id)
        return self._send_json(200, project)

    def _handle_list_topics(self, project_id: str | None):
        if project_id is None:
            # No filter → return all topics with their meta
            out = []
            for p in sorted(ROOM_DIR.glob("*.topic.json")):
                try:
                    meta = json.loads(p.read_text(encoding="utf-8"))
                    out.extend(_topics_for_project(meta.get("project_id", "")))
                except (OSError, json.JSONDecodeError):
                    continue
            # dedupe in case
            seen = set()
            unique = []
            for t in out:
                if t["id"] not in seen:
                    seen.add(t["id"])
                    unique.append(t)
            return self._send_json(200, unique)
        if not PROJECT_ID_RE.match(project_id):
            return self._send_json(400, {"error": "invalid project id"})
        return self._send_json(200, _topics_for_project(project_id))

    # --- POST /topic -------------------------------------------------------

    def _handle_topic(self):
        data = self._read_json_body()
        if data is None:
            return self._send_json(400, {"error": "invalid json body"})

        name = (data.get("name") or "").strip()
        workspace = data.get("workspace")
        project_id = data.get("project_id")

        if not name or not TOPIC_NAME_RE.match(name):
            return self._send_json(400, {"error": "invalid topic name"})
        if workspace is not None and not isinstance(workspace, str):
            return self._send_json(400, {"error": "workspace must be a string"})
        if project_id is not None and (not isinstance(project_id, str) or not PROJECT_ID_RE.match(project_id)):
            return self._send_json(400, {"error": "invalid project_id"})

        # If project_id provided, ensure it exists and default workspace from it.
        project = None
        if project_id:
            project = _load_project(project_id)
            if project is None:
                return self._send_json(400, {"error": f"project '{project_id}' does not exist"})
            if not workspace:
                workspace = project["workspace"]

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

        # Write topic meta (v3) so project membership persists.
        if project_id:
            try:
                _save_topic_meta({
                    "id": name,
                    "project_id": project_id,
                    "created_at": _now_utc_iso(),
                })
            except OSError as e:
                return self._send_json(
                    500, {"error": f"could not write topic meta: {e}"}
                )

        return self._send_json(
            201,
            {"name": name, "url": f"/?topic={name}", "project_id": project_id},
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
    _migrate_legacy_topics_if_needed()
    server = http.server.ThreadingHTTPServer(("", port), Handler)
    print(f"Team room serving on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
