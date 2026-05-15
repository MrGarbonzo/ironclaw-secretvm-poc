"""Idempotent setup of demo routines for the IronClaw + Telegram Friday demo.

Reads demo/.env, substitutes the bot token + chat id into the prompt files,
deletes any existing routines with these names, and recreates them via
`ironclaw routines create`. Operator-managed only - no agent-driven creation.

Local target: shells out to `docker exec $IRONCLAW_DOCKER_CONTAINER ironclaw ...`.
Live target: print the equivalent commands the operator runs over SSH/secretvm-cli.

Usage:
    python demo/setup_routines.py             # apply against the local stack
    python demo/setup_routines.py --print     # just print the commands, do not run
    python demo/setup_routines.py --target=ssh root@host -i ~/.ssh/key  # over SSH
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
TASKS_DIR = SCRIPT_DIR / "tasks"


def load_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        sys.exit(f"Missing {ENV_FILE}. Copy demo/.env.example to demo/.env and fill values.")
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    for required in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not out.get(required):
            sys.exit(f"{required} not set in {ENV_FILE}")
    return out


def read_prompt(task_name: str, env: dict[str, str]) -> str:
    raw = (TASKS_DIR / f"{task_name}.txt").read_text(encoding="utf-8")
    return raw.replace("{TELEGRAM_BOT_TOKEN}", env["TELEGRAM_BOT_TOKEN"]).replace(
        "{TELEGRAM_CHAT_ID}", env["TELEGRAM_CHAT_ID"]
    )


ROUTINES = [
    {
        "name": "morning-digest",
        "schedule": "0 0 13 * * *",
        "description": "Daily BTC/ETH prices + top AI/crypto headlines",
        "timezone": "UTC",
        "task": "digest",
        "cooldown": 3600,
    },
    {
        "name": "price-update",
        "schedule": "0 0 21 * * *",
        "description": "Afternoon BTC/ETH price update",
        "timezone": "UTC",
        "task": "price",
        "cooldown": 3600,
    },
    {
        "name": "news-briefing",
        "schedule": "0 0 17 * * *",
        "description": "Top 5 AI/crypto stories of the day",
        "timezone": "UTC",
        "task": "news",
        "cooldown": 3600,
    },
    {
        "name": "demo-tick",
        "schedule": "0 */2 * * * *",
        "description": "Demo-only routine that fires every 2 minutes. Delete after demo.",
        "timezone": "UTC",
        "task": "price",
        "cooldown": 60,
    },
]


def make_runner(target: str, target_arg: str | None, remote_container: str):
    """Return a function (argv_list) -> CompletedProcess."""
    if target == "docker":
        prefix = ["docker", "exec", "-i", target_arg or "ironclaw-test-ironclaw-1"]

        def run_docker(argv: list[str], check: bool = True) -> subprocess.CompletedProcess:
            return subprocess.run(prefix + argv, capture_output=True, text=True, check=check)

        return run_docker

    if target == "ssh":
        if not target_arg:
            sys.exit("--target=ssh requires the SSH target string after it")
        ssh_prefix = ["ssh"] + shlex.split(target_arg)
        # SSH joins everything after the host into a single shell command on
        # the remote side, so we have to shell-quote each arg ourselves.
        # Multi-line routine prompts contain newlines, quotes, JSON braces,
        # and URL query strings — without quoting they get mangled.
        def run_ssh(argv: list[str], check: bool = True) -> subprocess.CompletedProcess:
            inner = ["docker", "exec", "-i", remote_container] + argv
            remote_cmd = " ".join(shlex.quote(a) for a in inner)
            return subprocess.run(
                ssh_prefix + [remote_cmd], capture_output=True, text=True, check=check,
            )

        return run_ssh

    if target == "secretvm":
        sys.exit("secretvm-cli does not support exec - use ssh or print")
    sys.exit(f"unknown target {target}")


def print_commands(env: dict[str, str]) -> None:
    """Emit the docker exec lines you'd run on the target host."""
    for r in ROUTINES:
        prompt = read_prompt(r["task"], env)
        print(f"# Routine: {r['name']}")
        print(
            "ironclaw routines delete -y "
            + shlex.quote(r["name"])
            + " || true"
        )
        cmd = (
            "ironclaw routines create"
            f" --name {shlex.quote(r['name'])}"
            f" --schedule {shlex.quote(r['schedule'])}"
            f" --description {shlex.quote(r['description'])}"
            f" --timezone {shlex.quote(r['timezone'])}"
            f" --cooldown {r['cooldown']}"
            f" --prompt {shlex.quote(prompt)}"
        )
        print(cmd)
        print()


def apply(runner, env: dict[str, str]) -> None:
    for r in ROUTINES:
        prompt = read_prompt(r["task"], env)
        print(f"\n=== {r['name']} (schedule='{r['schedule']}', tz='{r['timezone']}') ===")
        # delete-if-exists, ignore failures
        runner(["ironclaw", "routines", "delete", "-y", r["name"]], check=False)
        # create
        result = runner(
            [
                "ironclaw", "routines", "create",
                "--name", r["name"],
                "--schedule", r["schedule"],
                "--description", r["description"],
                "--timezone", r["timezone"],
                "--cooldown", str(r["cooldown"]),
                "--prompt", prompt,
            ],
            check=False,
        )
        if result.returncode != 0:
            print(f"FAILED (exit {result.returncode})")
            print("STDOUT:", result.stdout[:500])
            print("STDERR:", result.stderr[:500])
            sys.exit(1)
        # Strip ANSI debug noise; print just the routine confirmation lines
        for line in result.stdout.splitlines():
            if line.startswith("Created routine") or line.startswith("  "):
                print(line)

    print("\n=== All routines ===")
    listed = runner(["ironclaw", "routines", "list"], check=False)
    print(listed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print", action="store_true",
                        help="Print the commands instead of running them.")
    parser.add_argument("--target", choices=["docker", "ssh"], default="docker",
                        help="docker exec (local) or ssh (live VM).")
    parser.add_argument("--target-arg",
                        help="docker container name OR ssh target+flags (e.g. 'root@host -i key').")
    parser.add_argument("--remote-container", default="docker_wd-ironclaw-1",
                        help="On a SecretVM, the ironclaw container name (default: docker_wd-ironclaw-1).")
    args = parser.parse_args()

    env = load_env()

    if args.print:
        print_commands(env)
        return

    target_arg = args.target_arg or env.get("IRONCLAW_DOCKER_CONTAINER", "ironclaw-test-ironclaw-1")
    runner = make_runner(args.target, target_arg, args.remote_container)
    apply(runner, env)


if __name__ == "__main__":
    main()
