"""Manually fire one of the demo tasks RIGHT NOW via the gateway chat API.

Useful as a live-demo fallback when you don't want to wait for the scheduled
fire. This is NOT how routines normally execute (they run inside IronClaw's
routine engine, not via /api/chat/send), but it produces the same Telegram
output because both paths share the same agent + http tool.

Usage:
    python demo/fire_now.py price          # default
    python demo/fire_now.py news
    python demo/fire_now.py digest
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
TASKS_DIR = SCRIPT_DIR / "tasks"


def load_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        sys.exit(f"Missing {ENV_FILE}.")
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def fire(task: str, env: dict[str, str], gateway_token: str) -> None:
    base = env.get("IRONCLAW_BASE", "http://127.0.0.1:3030").rstrip("/")
    prompt = (TASKS_DIR / f"{task}.txt").read_text(encoding="utf-8")
    prompt = prompt.replace("{TELEGRAM_BOT_TOKEN}", env["TELEGRAM_BOT_TOKEN"]).replace(
        "{TELEGRAM_CHAT_ID}", env["TELEGRAM_CHAT_ID"]
    )

    hdrs = {"Authorization": f"Bearer {gateway_token}", "Content-Type": "application/json"}
    sse = requests.get(
        f"{base}/api/chat/events",
        params={"token": gateway_token},
        stream=True,
        timeout=240,
    )
    if sse.status_code != 200:
        sys.exit(f"SSE failed: HTTP {sse.status_code}")

    send = requests.post(f"{base}/api/chat/send", headers=hdrs, json={"content": prompt}, timeout=10)
    if send.status_code not in (200, 202):
        sys.exit(f"send failed: HTTP {send.status_code} {send.text[:200]}")

    print(f"Fired '{task}'. Watching event stream...")
    current = ""
    deadline = time.monotonic() + 240
    try:
        for raw in sse.iter_lines(decode_unicode=True):
            if time.monotonic() > deadline:
                print("TIMEOUT")
                break
            if raw is None or raw == "":
                current = ""
                continue
            if raw.startswith(":") or raw.startswith("id:"):
                continue
            if raw.startswith("event:"):
                current = raw[len("event:"):].strip()
                continue
            if raw.startswith("data:"):
                try:
                    ev = json.loads(raw[len("data:"):].lstrip())
                except json.JSONDecodeError:
                    continue
                if current == "tool_started":
                    name = ev.get("name") or ev.get("tool")
                    detail = (ev.get("detail") or "")[:80]
                    print(f"  -> {name}: {detail}")
                elif current == "tool_completed":
                    name = ev.get("name") or ev.get("tool")
                    succ = ev.get("success")
                    err = (ev.get("error") or "")[:120]
                    print(f"  <- {name} success={succ} {err}")
                elif current == "status" and (ev.get("message") or "").lower() == "done":
                    print("DONE")
                    break
    finally:
        sse.close()


def main() -> None:
    task = sys.argv[1] if len(sys.argv) > 1 else "price"
    if task not in ("price", "news", "digest"):
        sys.exit("task must be one of: price, news, digest")

    env = load_env()
    container = env.get("IRONCLAW_DOCKER_CONTAINER", "ironclaw-test-ironclaw-1")

    # Pull GATEWAY_AUTH_TOKEN from the running container - avoids putting it
    # in demo/.env where the user might commit it by accident.
    import subprocess
    res = subprocess.run(
        ["docker", "exec", container, "printenv", "GATEWAY_AUTH_TOKEN"],
        capture_output=True, text=True, check=True,
    )
    gateway_token = res.stdout.strip()
    if not gateway_token:
        sys.exit("Could not read GATEWAY_AUTH_TOKEN from the container.")

    fire(task, env, gateway_token)


if __name__ == "__main__":
    main()
