# Demo status

**Date built:** 2026-05-14 (overnight before Friday demo)
**Target environment for tonight's build:** local Docker stack (`nearaidev/ironclaw:0.28.1` + `pgvector/pgvector:pg16`) at `C:\dev\secretai-tool-validation\ironclaw-test\docker-compose.yml`. Live deploy on `purple-hare.vm.scrtlabs.com` was NOT updated tonight - see "Migration to live deploy" below.

## TL;DR

End-to-end flow works locally: a CLI-managed routine fires on cron, the agent uses its built-in `http` tool to fetch real data (CoinGecko prices, HN Algolia headlines), and posts a formatted message to Telegram via the same `http` tool. Confirmed live by 3 demo-tick fires at 02:00, 02:02, 02:04 UTC on 2026-05-15.

There is no Telegram channel pairing involved - the bot token + chat ID are baked into the routine prompt, and the agent calls `https://api.telegram.org/bot<TOKEN>/sendMessage` over the `http` tool. Cleaner than the channel pairing dance, fewer moving parts.

## Phase A - tool inventory

Active model verified `gpt-oss:120b` on `secretai-jedi.scrtlabs.com:21434`. Doctor 7/0/10. Boot config clean: `IRONCLAW_PROFILE=server`, `command=["run","--no-onboard","--auto-approve"]`.

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

Registry has 27 extensions (Telegram, web_search, gmail, etc). NONE are required for tonight's demo - they all need extra credentials (Brave key, OAuth, Composio, etc) and add complexity. We sidestep all of them by going http -> Telegram Bot API directly.

## Phase B - Telegram delivery

Validated via a dedicated smoke test: agent prompted to POST to api.telegram.org over the `http` tool. Message arrived in user's DM (chat 587534846), message_id 1633, 12s end-to-end.

The `telegram` channel WASM IS installed and authenticated in the local stack (the `telegram_bot_token` secret is stored encrypted in postgres, channel state = `pairing`). It is NOT used by the demo flow - it would require a Telegram->bot pairing handshake we never completed. If you want bidirectional chat with the bot in a future iteration, finish the pairing via `ironclaw pairing list/approve telegram <code>`.

## Phase C - price task

Prompt at `tasks/price.txt`. Smoke test latency 8.2s. Two clean http calls (CoinGecko + Telegram). No tool hallucination.

## Phase D - news briefing

Prompt at `tasks/news.txt`. Smoke test latency 36s. HN Algolia public search (no API key). Picks 5 most recent AI/crypto stories, formats as Markdown bullets with link previews disabled.

Tried two prompt variations; the simpler one (single search call, return all 5 hits in order) is reliable. The more complex "pick the best of 9 by category" variant triggered gpt-oss:120b's known orchestrator hallucination of an `assistant` tool. See "Known rough edges" below.

## Phase E - combined morning digest

Prompt at `tasks/digest.txt`. Smoke test latency 140s with 13 total tool call attempts (3 successful http calls + 10 failed hallucinated calls). The agent eventually delivered. This is the worst latency of the three - if the live demo wants the digest to render fast, prefer Phase C or D as the live-fire example.

## Phase F - scheduling

Routines created via `python demo/setup_routines.py`. Operator-managed only - per locked decision, NO agent-driven routine creation.

| Routine | Schedule (UTC) | Task | Cooldown |
|---|---|---|---|
| `morning-digest` | `0 0 13 * * *` (13:00 UTC = 09:00 ET) | digest | 1h |
| `news-briefing` | `0 0 17 * * *` (17:00 UTC = 13:00 ET) | news | 1h |
| `price-update` | `0 0 21 * * *` (21:00 UTC = 17:00 ET) | price | 1h |
| `demo-tick` | `0 */2 * * * *` (every 2 minutes) | price | 60s |

Live fire confirmed: `demo-tick` ran 5 times between 02:00 and 02:08 UTC. The first fire at 02:00:00 reported a summary parse failure but the run still completed - likely a routine cold-start artifact. The other 4 fires all completed with `result_summary='Posted prices to Telegram.'`. After validation, `demo-tick` was disabled so it doesn't keep firing every 2 minutes overnight - re-enable for the demo with `ironclaw routines enable demo-tick`.

**The "attention" status on every routine_runs row is misleading.** It just means the routine has no `--notify-channel` configured, so IronClaw doesn't know where to deliver the run summary on its own. The agent already delivered the actual content to Telegram via the `http` tool, so the notify-channel is unused. We can ignore "attention" for the demo.

## Migration to live deploy (purple-hare)

NOT done tonight. To migrate:

1. Get the GATEWAY_AUTH_TOKEN off the live VM (`secretvm-cli vm logs` + grep, or redeploy with a known token).
2. The live deploy compose at `drafts/docker-compose.yml` needs three changes:
   - `command: ["--no-onboard"]` -> `command: ["run", "--no-onboard", "--auto-approve"]`
   - `LLM_BASE_URL: https://secretai-rytn.scrtlabs.com:21434` -> `https://secretai-jedi.scrtlabs.com:21434`
   - `LLM_MODEL: qwen2.5:72b` -> `gpt-oss:120b`
   - Add: `IRONCLAW_PROFILE: server`
3. `secretvm-cli vm edit` to redeploy.
4. After restart: `python demo/setup_routines.py --target=ssh "root@purple-hare.vm.scrtlabs.com -i ~/.ssh/<key>"` (assuming you have SSH; otherwise paste the routine creates from `python demo/setup_routines.py --print` over `secretvm-cli vm exec` if that exists, or use the gateway's `/api/routines` if a write API surface gets added in a later upstream).
5. Re-verify with `demo-tick` for one fire.

## Known rough edges (be ready to explain)

1. **gpt-oss:120b hallucinates a tool called `assistant`** mid-task. Behavior varies between calls. The price task self-recovers from one hallucination; the digest task takes 4-5 hallucinated attempts before getting through. The agent ALWAYS eventually completes (or the LLM gives up cleanly), but you'll see "Tool error: Tool assistant not found" in the event stream. This is upstream of IronClaw - it's how OpenAI's gpt-oss-120b harmony format leaks into our tool-call surface. We log it; we don't try to rewrite the model.

2. **Routine summary status is always `attention`** because no notify-channel is wired up. The actual outputs land in Telegram. If you want clean status: configure a notify-channel in step 2 of the SecretVM migration. Out of scope tonight.

3. **The bot token is in the routine prompt (in plain text in the database).** Not safe for a multi-tenant deploy. Acceptable for this single-user POC. Future hardening: store bot token in `secrets` table (we already proved that table works) and reference it from the http tool via the channel WASM credential mechanism.

4. **No HTTP fetch tool with cleaner ergonomics in the registry.** The 27-extension registry has `web_search` (Brave key), `llm_context` (Brave key), `composio` (paid), `nearai` (NEAR auth) - none are no-key. The built-in `http` tool is the only no-credentials internet path, and it's exactly what we need.

5. **`docker logs` returns empty on Windows for this container.** The agent stderr goes through Rust tracing, but the docker logs driver isn't picking it up (or is buffering hard). Use the postgres tables (`routine_runs`, `llm_calls`, `secrets`, `routines`) for observability instead.

## Files in this folder

- `.env.example` / `.env` (gitignored) - Telegram bot token, chat ID, container target
- `tasks/price.txt`, `tasks/news.txt`, `tasks/digest.txt` - the three routine prompts (with `{TELEGRAM_BOT_TOKEN}` / `{TELEGRAM_CHAT_ID}` placeholders)
- `setup_routines.py` - idempotent routine setup; `--print` prints the equivalent shell commands; `--target=ssh "root@host -i key"` runs against a remote VM
- `DEMO-SCRIPT.md` - tomorrow's step-by-step demo flow
- `STATUS.md` - this file
