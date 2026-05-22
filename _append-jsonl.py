#!/usr/bin/env python3
"""Locked append to a topic's JSONL transcript.

Usage:
  _append-jsonl.py <topic_jsonl_path> <role> <model> <content> [--round N] [--prompt-id ID]

Acquires fcntl.flock on <topic_jsonl_path>.lock for the duration of the write.
This is the single canonical writer used by ask-claude.sh, ask-codex.sh, log.sh,
orchestrate.py, and the server — keeps interleaving safe even when both agents
finish at the exact same millisecond.
"""

import argparse
import datetime
import fcntl
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="absolute path to <topic>.jsonl")
    parser.add_argument("role")
    parser.add_argument("model")
    parser.add_argument("content")
    parser.add_argument("--round", type=int, default=None)
    parser.add_argument("--prompt-id", default=None)
    args = parser.parse_args()

    target = Path(args.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")

    msg = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role": args.role,
        "model": args.model,
        "content": args.content,
    }
    if args.round is not None:
        msg["round"] = args.round
    if args.prompt_id is not None:
        msg["prompt_id"] = args.prompt_id

    line = json.dumps(msg, ensure_ascii=False) + "\n"

    with open(lock_path, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write(line)
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
