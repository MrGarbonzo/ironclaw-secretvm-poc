# Demo script - Friday 2026-05-15

The story: an attestable AI agent (IronClaw, running in a TDX SecretVM, talking to SecretAI which is itself in a TDX enclave) is operating on a schedule. It fetches real-time data from the public internet and posts a curated summary to Telegram - all without a human in the loop.

**Live target:** `https://beige-ermine.vm.scrtlabs.com/` (SecretVM, Intel TDX, container `docker_wd-ironclaw-1`)

## Pre-demo setup (do this 5 minutes before)

1. Open your @Garbonzo_AI_Bot DM in Telegram. Have it visible on screen.

2. Confirm gateway is reachable from the outside:
   ```powershell
   curl https://beige-ermine.vm.scrtlabs.com/api/health
   ```
   Expect `{"status":"healthy","channel":"gateway"}`.

3. Confirm routines are scheduled (SSH in):
   ```powershell
   ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
       'docker exec docker_wd-ironclaw-1 ironclaw routines list --disabled'
   ```
   You should see `morning-digest`, `news-briefing`, `price-update` (all `active`/`attention`) and `demo-tick` (currently `disabled` to avoid pre-demo Telegram spam).

4. **Re-enable `demo-tick` for the demo** so it fires every 2 minutes:
   ```powershell
   ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
       'docker exec docker_wd-ironclaw-1 ironclaw routines enable demo-tick'
   ```
   Then disable it again immediately after the demo:
   ```powershell
   ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
       'docker exec docker_wd-ironclaw-1 ironclaw routines disable demo-tick'
   ```

## The demo (10-12 min)

### 1. Frame the stack (1 min)

> "What you're about to see is an AI agent running entirely inside an attested enclave. Both the agent runtime - IronClaw - and the LLM it talks to - SecretAI's gpt-oss:120b - are inside Intel TDX VMs. So the model can't be tampered with, the prompt can't be exfiltrated, and the inference can't be inspected by the host."

### 2. Show the inventory (1 min)

```powershell
ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
    'docker exec docker_wd-ironclaw-1 ironclaw models status'
ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
    'docker exec docker_wd-ironclaw-1 ironclaw doctor'
ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
    'docker exec docker_wd-ironclaw-1 ironclaw routines list'
```

Point to:
- Provider/model line - "gpt-oss:120b on SecretAI"
- Doctor's "Routines config: enabled (interval=15s, max_concurrent=10)" line
- The four routines, all `active`

### 3. Show one of the prompts (1 min)

Open `demo/tasks/digest.txt`. Read the first paragraph aloud. Two points:
- "The prompt is a literal instruction set. There's no plugin code - the agent is calling the same `http` tool it would use for any URL."
- "We're not telling it what BTC's price is - we're telling it where to fetch it. The data is real, fetched at the moment of fire."

### 4. Trigger a routine on demand (3 min)

Two options. Pick one.

**Option A - wait for `demo-tick`.** It fires at every even minute (UTC). Worst case wait is 2 minutes. Tell the audience "the next fire is at HH:MM, watch the bot." Then point at the Telegram window.

**Option B - fire one of the tasks immediately via the chat API.** From `C:\dev\ironclaw-secretvm-poc`:
```powershell
python demo/fire_now.py price `
    --base https://beige-ermine.vm.scrtlabs.com `
    --gateway-token b7649d308ae092409d4f3052b9d465ccd8d3d1a1867ab4211af2c55dc7d4b30b
```
Same agent + http tool path the routine uses, just kicked off by an HTTP POST instead of the cron timer. Same Telegram output. Validated overnight - works every time within 8-15s for `price`, ~36s for `news`, and ~2 min for `digest`.

(You can put `IRONCLAW_BASE=https://beige-ermine.vm.scrtlabs.com` and `IRONCLAW_GATEWAY_TOKEN=…` in `demo/.env` to skip the flags; `fire_now.py price` then works on its own.)

When the message lands in Telegram:
- "Real numbers from CoinGecko. Real Markdown formatting. The agent decided how to phrase it."
- Show the inbound chat in their @Garbonzo_AI_Bot DM.

### 5. Show the audit trail (1 min)

```powershell
ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
    'docker exec docker_wd-ironclaw-1 ironclaw routines history demo-tick'
```

Point to: STARTED column, DURATION (~10-15s), SUMMARY ("Posted prices to Telegram.").

If asked "what model did it use?" - peek at the LLM calls table:
```powershell
ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
    "docker exec docker_wd-postgres-1 psql -U ironclaw -d ironclaw -c 'SELECT created_at, model, input_tokens, output_tokens FROM llm_calls ORDER BY created_at DESC LIMIT 3;'"
```
(Note: routine fires don't currently write to `llm_calls`, so this shows chat history only. Mention that as a known observability gap, not a bug.)

### 6. Show attestation (1-2 min — this is the punchline)

Switch the slide / browser to:
```
https://beige-ermine.vm.scrtlabs.com:29343/cpu.html
```
"This page is the attestation report from the TEE. The image digest you see is what's actually running. Anyone can verify it - we don't have to trust the operator."

For maximum credibility, also show the compose source on GitHub:
```
https://github.com/MrGarbonzo/ironclaw-secretvm-poc/blob/main/drafts/docker-compose.yml
```
"This is the exact compose deployed. Nothing in this repo is a fork - we're running unmodified `nearaidev/ironclaw:0.28.1`. The TDX measurement covers this compose file; the compose pins the image."

### 7. The point (1 min)

> "The thing that's actually new here isn't the agent - agent frameworks are everywhere. The thing that's new is the attested-end-to-end property. The model can't be swapped. The system prompt can't be injected. The host operator can't read what's in flight. So when this thing posts to a Telegram channel - or in a real deployment, signs a transaction or makes a payment - you have cryptographic evidence of which code did it and which model produced the decision."

## Routines you can highlight as roadmap

- `morning-digest` (13:00 UTC daily) - the showcase routine. Combines prices + headlines.
- `news-briefing` (17:00 UTC daily) - just the headlines.
- `price-update` (21:00 UTC daily) - just the prices.
- `demo-tick` (every 2 min, UTC) - delete after the demo.

To delete the demo-tick after:
```powershell
ssh -i $HOME\.ssh\beige_ermine_key root@beige-ermine.vm.scrtlabs.com `
    'docker exec docker_wd-ironclaw-1 ironclaw routines delete -y demo-tick'
```

## Known things to be ready to explain

See `STATUS.md` "Known rough edges". Most likely audience questions:

- *"Why does the status say 'attention'?"* -> "No notify-channel configured. The agent already delivered the content; the routine framework just doesn't know we routed it ourselves."
- *"What if the agent hallucinates?"* -> "It does, occasionally - this version of gpt-oss-120b sometimes invents a tool name like `assistant`. The agent recovers within the same turn and the http call still goes out. We log every tool attempt in `routine_runs` and `tool_failures` for audit."
- *"Why three separate routines plus a demo-tick?"* -> "Different cadence per content type. Morning digest is once a day; demo-tick is just for live demos."
- *"How do you handle the bot token?"* -> "In this POC it's in the routine prompt. Production hardening would move it to the `secrets` table - we've already verified that path works for the Telegram channel WASM."
- *"Why don't you use the Telegram channel directly?"* -> "Two reasons. (1) The channel needs a manual pairing handshake from the bot owner. (2) The http path is simpler and gets the same end result. We CAN finish the channel pairing if you want bidirectional chat with the agent later."
- *"Can the model read the bot token?"* -> "Yes - the prompt is in the model's context window. That's why this token is throwaway. In a real deployment the token would be in the secrets table and the agent would call a credentials-aware HTTP wrapper instead."

## Stop conditions / abort plan

If during the demo:
- Routine fires but Telegram message doesn't arrive within 30s -> pivot to manual `python demo/fire_now.py price --base https://beige-ermine.vm.scrtlabs.com --gateway-token <token>` to show the same thing on demand.
- Live VM is unreachable -> fall back to the local stack at `C:\dev\secretai-tool-validation\ironclaw-test\docker-compose.yml`. `python demo/fire_now.py price` (no flags needed locally) gives the same output. Caveat: lose the attestation slide.
- IronClaw on the VM is unhealthy -> SSH in, `docker logs --tail 80 docker_wd-ironclaw-1` and `docker exec docker_wd-postgres-1 psql -U ironclaw -d ironclaw -c "SELECT name, last_run, status FROM routines ORDER BY last_run DESC NULLS LAST LIMIT 5;"`.
