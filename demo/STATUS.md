# Demo status

**Date built:** 2026-05-14 / 2026-05-15 (overnight before Friday demo)
**Live target:** SecretVM `beige-ermine.vm.scrtlabs.com` (Intel TDX). IronClaw 0.28.1 + Postgres + Traefik. Boot config: `IRONCLAW_PROFILE=server`, `command=["run","--no-onboard","--auto-approve"]`. Active model: `gpt-oss:120b` on `secretai-jedi.scrtlabs.com:21434`. Compose source: `https://github.com/MrGarbonzo/ironclaw-secretvm-poc/blob/main/drafts/docker-compose.yml`.
**Local fallback:** `C:\dev\secretai-tool-validation\ironclaw-test\docker-compose.yml` (same image, same model). Used for overnight build; still works if the live VM is unavailable on demo day.

## TL;DR

End-to-end flow works on the live VM: a CLI-managed routine fires on cron inside the SecretVM, the agent uses its built-in `http` tool to fetch real data (CoinGecko prices, HN Algolia headlines), and posts a formatted message to Telegram via the same `http` tool. Confirmed live by 7 demo-tick fires at 04:48 → 05:00 UTC on 2026-05-15 (5/7 clean, 2/7 cold-start summary parse blips), plus initial fires of morning-digest, news-briefing, and price-update on creation.

There is no Telegram channel pairing involved - the bot token + chat ID are baked into the routine prompt, and the agent calls `https://api.telegram.org/bot<TOKEN>/sendMessage` over the `http` tool. Cleaner than the channel pairing dance, fewer moving parts.

## Phase A - tool inventory

Verified on `beige-ermine`. `gpt-oss:120b` active on jedi. Doctor 7/0/10. Boot config clean.

The agent has these built-in tools (all available to routine and chat contexts):

| Tool | Permission | Use |
|---|---|---|
| **`http`** | always_allow | All internet egress. No API key needed. |
| `json` | always_allow | Parse responses. |
| `time`, `echo` | always_allow | Utilities. |
| `memory_*` | always_allow | Agent workspace memory. |
| `read_file`, `list_dir`, `apply_patch`, `shell`, `write_file` | ask_each_time | File and shell. Demo doesn't use these. |
| `image_*` | mixed | Not used. |
| `secret_list/delete`, `tool_*`, `skill_*` | various | Meta tools. |

The demo relies on `http` only.

## Phase B - Telegram delivery

Validated overnight on local stack: agent prompted to POST to api.telegram.org over the `http` tool. 12s end-to-end. Same path now confirmed on `beige-ermine` via the four routines.

## Phase C/D/E - the three task prompts

| Task | Prompt | Latency (local) | Notes |
|---|---|---|---|
| price | `tasks/price.txt` | 8s | Two http calls (CoinGecko + Telegram). Cleanest. |
| news | `tasks/news.txt` | 36s | One HN Algolia search → Telegram. Picks 5 most recent AI/crypto stories. |
| digest | `tasks/digest.txt` | ~140s | Three http calls (prices + news + post). Worst latency due to gpt-oss-120b's `assistant` tool hallucination — agent recovers. |

For live-fire on stage, prefer `price` or `news` over `digest`.

## Phase F - scheduling on `beige-ermine`

Routines created via `python demo/setup_routines.py --target ssh --target-arg "root@beige-ermine.vm.scrtlabs.com -i ~/.ssh/beige_ermine_key -o IdentitiesOnly=yes"`. Operator-managed, CLI-driven. Idempotent.

| Routine | Schedule (UTC) | Task | Cooldown | Demo-day status |
|---|---|---|---|---|
| `morning-digest` | `0 0 13 * * *` (13:00 UTC = 09:00 ET) | digest | 1h | active |
| `news-briefing` | `0 0 17 * * *` (17:00 UTC = 13:00 ET) | news | 1h | active |
| `price-update` | `0 0 21 * * *` (21:00 UTC = 17:00 ET) | price | 1h | active |
| `demo-tick` | `0 */2 * * * *` (every 2 minutes) | price | 60s | **disabled** — re-enable for demo |

Live fire confirmed on 2026-05-15: `demo-tick` ran 7 times between 04:48 and 05:00 UTC. 5 of 7 completed with `result_summary='Posted prices to Telegram.'`. The 2 cold-start runs failed at the summary parse step but the underlying http POST still went through (user confirmed visible Telegram delivery during the live test). After validation, `demo-tick` was disabled - re-enable for the demo with:
```
ssh -i ~/.ssh/beige_ermine_key root@beige-ermine.vm.scrtlabs.com 'docker exec docker_wd-ironclaw-1 ironclaw routines enable demo-tick'
```

**The "attention" status on every routine_runs row is misleading.** It just means the routine has no `--notify-channel` configured, so IronClaw doesn't know where to deliver the run summary on its own. The agent already delivered the actual content to Telegram via the `http` tool, so the notify-channel is unused. We can ignore "attention" for the demo.

## Live access cheat sheet (paste-ready)

```powershell
# Health from outside:
curl https://beige-ermine.vm.scrtlabs.com/api/health

# Attestation page (audience-facing slide):
# https://beige-ermine.vm.scrtlabs.com:29343/cpu.html

# SSH:
ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com

# Container name on the VM: docker_wd-ironclaw-1
# Gateway token (in container env, also baked into demo workflow):
#   b7649d308ae092409d4f3052b9d465ccd8d3d1a1867ab4211af2c55dc7d4b30b
```

## Known rough edges (be ready to explain)

1. **gpt-oss:120b hallucinates a tool called `assistant`** mid-task. Behavior varies between calls. The price task self-recovers from one hallucination; the digest task takes 4-5 hallucinated attempts before getting through. The agent ALWAYS eventually completes (or the LLM gives up cleanly), but you'll see "Tool error: Tool assistant not found" in the event stream. This is upstream of IronClaw - it's how OpenAI's gpt-oss-120b harmony format leaks into our tool-call surface. We log it; we don't try to rewrite the model.

2. **Routine summary status is always `attention`** because no notify-channel is wired up. The actual outputs land in Telegram. If you want clean status: configure a notify-channel post-demo. Out of scope for tonight.

3. **The bot token is in the routine prompt (in plain text in the database, and in the model's context window).** Not safe for a multi-tenant deploy or a production bot. Acceptable for this single-user POC with a throwaway bot. Future hardening: store bot token in `secrets` table and reference it from the http tool via the channel WASM credential mechanism.

4. **No HTTP fetch tool with cleaner ergonomics in the registry.** The 27-extension registry has `web_search` (Brave key), `llm_context` (Brave key), `composio` (paid), `nearai` (NEAR auth) - none are no-key. The built-in `http` tool is the only no-credentials internet path, and it's exactly what we need.

5. **Routine fires don't write to `llm_calls`.** The `llm_calls` postgres table only logs chat-API turns, not routine executions. Audit for routines is in `routine_runs` only. Mention this as "known observability gap, fixed upstream in a later release."

6. **Doctor warns about `HEARTBEAT_ENABLED`** on every CLI invocation. Benign — the env var is set but a stale DB setting wins. Heartbeat is off either way. Cosmetic; clear with `ironclaw config reset heartbeat.enabled` if you care.

## Migration provenance (in case anyone asks "how was this built")

1. Built and validated against the local Docker stack overnight on 2026-05-14. Four routines, http tool delivery, demo-tick fired 5x cleanly.
2. SecretVM live deploy `purple-hare` was running on `qwen2.5:72b` from an earlier POC; couldn't be switched to `gpt-oss:120b` via runtime config because env vars (`LLM_BASE_URL`, `LLM_MODEL`) override DB settings on every container restart.
3. Pushed `drafts/docker-compose.yml` updates to GitHub (commit `3f76b56`): changed `command` to headless `run --no-onboard --auto-approve`, added `IRONCLAW_PROFILE=server`, switched LLM target to `secretai-jedi.scrtlabs.com:21434` / `gpt-oss:120b`.
4. Operator redeployed via the SecretVM portal, pulling compose from GitHub. After two false-start VMs (one missing HTTPS, one missing `POSTGRES_PASSWORD` in env), `beige-ermine.vm.scrtlabs.com` came up clean: gateway healthy, attestation page at `:29343/cpu.html` reachable, model `gpt-oss:120b` active.
5. Pushed routines via `setup_routines.py --target ssh ...` (the script wraps the inner `ironclaw routines create` calls in `docker exec -i docker_wd-ironclaw-1` with proper shell quoting for the multi-line prompts).
6. Verified live with 7 demo-tick fires on 2026-05-15 between 04:48 and 05:00 UTC.

## Files in this folder

- `.env.example` / `.env` (gitignored) - Telegram bot token, chat ID, optional `IRONCLAW_BASE` and `IRONCLAW_GATEWAY_TOKEN` for `fire_now.py` against a remote target
- `tasks/price.txt`, `tasks/news.txt`, `tasks/digest.txt` - the three routine prompts (with `{TELEGRAM_BOT_TOKEN}` / `{TELEGRAM_CHAT_ID}` placeholders)
- `setup_routines.py` - idempotent routine setup; `--print` prints the equivalent shell commands; `--target ssh --target-arg "root@host -i key"` runs against a remote VM (auto-wraps with `docker exec -i docker_wd-ironclaw-1`); `--remote-container` overrides if the container name differs
- `fire_now.py` - manual fire of one of the three tasks via the gateway chat API. Local: auto-discovers the gateway token from the container env. Remote: pass `--base` and `--gateway-token`, or set `IRONCLAW_BASE` / `IRONCLAW_GATEWAY_TOKEN` in `demo/.env`.
- `DEMO-SCRIPT.md` - tomorrow's step-by-step demo flow
- `STATUS.md` - this file
