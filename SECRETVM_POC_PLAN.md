# IronClaw on SecretVM — POC Plan

**Owner:** Secret Network Foundation
**Status:** Planning / drafts only — no production code yet.
**Upstream read against:** IronClaw v0.28.1 (`C:\dev\ironclaw-main`, no git checkout — version from `Cargo.toml`).
**Date:** 2026-05-11

---

## Goal

Run a single IronClaw agent inside one SecretVM (Intel TDX confidential VM), using SecretAI (secretai-rytn.scrtlabs.com:21434) as its LLM backend, reachable via the web gateway over the SecretVM-provided HTTPS URL, with TDX attestation independently verifiable.

Success looks like: a user navigates to `https://<adjective-animal>.vm.scrtlabs.com/`, authenticates with a bearer token, chats with IronClaw, and IronClaw routes every LLM call to SecretAI. Anyone can run `secretvm-cli vm attestation <vmId>` (or hit `:29343/cpu.html`) to confirm what image is actually running.

Out of scope: Telegram/Slack/Signal channels, Docker-sandboxed workers (orchestrator/Docker-in-Docker), routines, MCP servers, OAuth/OIDC, semantic embeddings, heartbeat, multi-user, multi-VM, HA, custom domains.

---

## Architecture summary

```
                ┌──────────────────────────────────────────────┐
                │  SecretVM (Intel TDX, medium tier)           │
                │                                              │
                │   ┌────────────────────────────────────┐     │
                │   │  ironclaw container               ─┼─→ SecretAI (also a TDX VM,
                │   │   - Rust agent, axum gateway       │     OpenAI-compatible via Ollama)
                │   │   - port 3000 (published)          │
                │   │   - env: LLM_BACKEND=openai_compatible
                │   └─────────┬──────────────────────────┘     │
                │             │ DATABASE_URL                   │
                │   ┌─────────▼──────────────┐                 │
                │   │ postgres container     │                 │
                │   │  pgvector/pgvector:pg16│                 │
                │   │  no published port     │                 │
                │   │  volume: pgdata        │                 │
                │   └────────────────────────┘                 │
                │                                              │
                │  Host attestation server :29343 (built-in)   │
                └──────────────┬──────────────────────────┬────┘
                               │ HTTPS                    │ HTTPS
                               ▼                          ▼
                   https://<vm>.vm.scrtlabs.com/   https://<vm>.vm.scrtlabs.com:29343/cpu.html
                   (web gateway, bearer-token auth) (attestation quote)

       Egress (one destination): https://secretai-rytn.scrtlabs.com:21434/v1
       (SecretAI, OpenAI-compatible via Ollama, also TEE-hosted)
```

Two containers in one SecretVM. SecretVM provides the HTTPS URL and the attestation endpoint for free. PG state persists in a named volume that survives container restarts (whole-disk persistence via `secretvm-cli vm create -p`). End-to-end confidentiality: agent runtime is in TDX, LLM inference is in TDX.

---

## Component inventory

### Containers we run

| Container | Image | Purpose | Public port | Internal port | State |
|---|---|---|---|---|---|
| `ironclaw` | `nearaidev/ironclaw:<version>@sha256:<digest>` | Agent runtime, web gateway | 3000 (published) | 3000 | Stateless (state in PG) |
| `postgres` | `pgvector/pgvector:pg16` | Persistence | none | 5432 | Volume: `pgdata` |

### What lives where

- **Postgres** holds: workspace memory, settings, encrypted secrets, message history, jobs, embeddings (disabled in POC), routines (disabled).
- **`~/.ironclaw/` inside the ironclaw container** holds: WASM tools/channels bundled in the image, the PID lock file, and (normally) the bootstrap `.env`. We avoid making this a persistent volume so PID lock doesn't get stuck across restarts.
- **`pgdata` named volume** is the only durable storage that needs to survive container restart.

### External network calls (egress, runtime, minimal config)

| Destination | Why | Required? |
|---|---|---|
| `https://secretai-rytn.scrtlabs.com:21434/...` (SecretAI) | Every LLM call | **Yes — load-bearing** |
| Docker Hub `nearaidev/ironclaw`, `pgvector/pgvector` | Image pulls at VM create / restart | **Yes — at deploy time only** |
| Anything else | n/a | **No** — telemetry off, no MCP, no extensions, no tunnel, no NEAR AI, no OAuth |

### Secrets / credentials at boot

| Name | Source | Notes |
|---|---|---|
| `DATABASE_URL` | env file uploaded with the VM | PG sibling, internal Docker DNS (`postgres:5432`). |
| `POSTGRES_PASSWORD` | env file | Used by PG container init and DATABASE_URL. |
| `SECRETS_MASTER_KEY` | env file | 32-byte base64 (`openssl rand -base64 32`). Wizard `KeySource::Env`. |
| `LLM_API_KEY` | env file | SecretAI API key. Sent as `Authorization: Bearer <key>` — standard OpenAI-compatible auth, no x402. |
| `GATEWAY_AUTH_TOKEN` | env file | Bearer token for the web UI. Generate with `openssl rand -hex 32`. |

All five live in the env file that `secretvm-cli` uploads at create time. None of them are in the repo.

### Ports

- **3000** — IronClaw web gateway. Published. The single public-facing port the SecretVM compose declares.
- **5432** — Postgres. NOT published. Container-to-container only via the docker network.
- **29343** — Host-side TDX attestation server. Always exposed by SecretVM itself, outside our compose.

### Host-only / interactive dependencies (resolved)

| Dependency | Status | Resolution |
|---|---|---|
| OS keychain for secrets master key | Resolved | Use `SECRETS_MASTER_KEY` env var (`KeySource::Env`). |
| Browser OAuth (NEAR AI) | Resolved | `LLM_BACKEND=openai_compatible` instead. Don't set `NEARAI_*`. |
| Interactive TTY for the wizard | Resolved | `--no-onboard` flag in entrypoint + `ONBOARD_COMPLETED=true`. |
| Telegram getUpdates owner binding | Not applicable | Telegram disabled. |
| Stale PID lock at `~/.ironclaw/ironclaw.pid` | Resolved | Don't persist `~/.ironclaw/`. PID file dies with the container. |

---

## Gap analysis

Five upstream-side concerns were called out by the user, plus a handful I surfaced while reading. Status code: **OK** = works as-is, **ADAPT** = needs a small POC-side adaptation (env hygiene, entrypoint glue, etc.), **PATCH** = needs upstream change. **None of the items below need upstream patches.**

### 1. `ironclaw onboard` wizard (browser OAuth + system keychain) — **OK**

The interactive wizard is real, but upstream already supports a headless bypass:

- `--no-onboard` CLI flag suppresses auto-trigger (`src/main.rs` line 362). `ONBOARD_COMPLETED=true` is a belt-and-suspenders alternative.
- `KeySource::Env` is a supported mode for the secrets master key (`src/setup/README.md` line 596 + Step 2 decision tree). `SECRETS_MASTER_KEY` env avoids the OS keychain entirely.
- Browser OAuth is **only triggered by `LLM_BACKEND=nearai`**. Using `openai_compatible` skips it (`src/setup/README.md`'s remote-server-auth section explicitly recommends this for headless deploys).
- Upstream's own production deploy (`deploy/ironclaw.service`) runs `ironclaw --no-onboard` with API-key auth. **We are walking a paved path.**

**No upstream changes needed.** Bootstrap is fully env-driven.

### 2. LLM backend swap to OpenAI-compatible (SecretAI) — **ADAPT (env hygiene only)**

SecretAI exposes an OpenAI-compatible surface via Ollama at `https://secretai-rytn.scrtlabs.com:21434`. Supported endpoints: `/v1/chat/completions` (with streaming), `/v1/completions`, `/v1/models`, tool/function calling on select models (e.g. `llama3.3:70b`). `/v1/responses` returns 404, and `/v1/embeddings` is still in progress — neither blocks the POC because IronClaw's `openai_compatible` backend uses `/v1/chat/completions` and we have embeddings disabled. Auth is standard `Authorization: Bearer <key>` — **no x402 handshake involved.**

The `LLM_BACKEND=openai_compatible` path works directly via `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` (`crates/ironclaw_llm/CLAUDE.md` and `.env.example`).

One residual NEAR-AI behavior to avoid: `.env.example` notes that *"When both NEARAI_BASE_URL and NEARAI_API_KEY are set at startup, IronClaw also bootstraps a persisted `nearai` MCP server."* So we must **leave both `NEARAI_*` variables unset** in our env file. The `.env.example` in this repo (drafts/.env.example) does this by omission.

**No upstream changes needed.** Just don't set NEARAI_* env vars.

### 3. PostgreSQL inside the TDX VM — **OK**

IronClaw treats `DATABASE_URL` as a generic Postgres connection string. The upstream's own `docker-compose.yml` uses `pgvector/pgvector:pg16` as a sibling for local dev. Nothing in the code assumes PG is on the same host or external.

For the **medium tier (2 vCPU / 4 GB RAM)** we need to tune PG so it doesn't eat the agent's headroom:
- `shared_buffers=256MB`
- `work_mem=16MB`
- `max_connections=20`
- `DATABASE_POOL_SIZE=10` (IronClaw side; default 30 is multi-tenant)

`shared_buffers` is set via PG command flags or a small `postgresql.conf` overlay. POC compose draft uses `command:` flags to keep it simple.

**No upstream changes needed.** Tuning is config-only.

### 4. WASM channel build (`include_bytes!()` for Telegram) — **OK (not relevant)**

The README warns that `./scripts/build-all.sh` must run before `cargo build` because the main binary embeds Telegram WASM via `include_bytes!()`. This matters only if we build from source.

We pull pre-built `nearaidev/ironclaw` from Docker Hub. The image already contains the bundled WASM. Telegram won't be activated anyway (channels not configured). **Non-issue for the POC.**

Flag in the plan only because the README mentions it: if we ever fork and build our own image, the CI pipeline must mirror SecretRelay's pattern — full build inside CI (where `build-all.sh` runs cleanly), then push image-by-digest.

### 5. Telemetry / auto-update / call-home — **OK (refuted as a concern)**

- `src/observability/mod.rs` defaults the observability backend to `"none"` → `NoopObserver`. Zero overhead, discards everything. No external sink.
- No background update checker in the binary. The `ironclaw-update` referenced in the README is an installer-supplied shim, not part of the agent.
- All `releases/latest` URLs in the source tree are for **extension downloads** (registry installer). Don't install extensions and nothing fetches from GitHub.
- `RUST_LOG=ironclaw=info` (default in `runtime` image) keeps logs to status only. We should **NOT** set debug/trace in production — `RUST_LOG=ironclaw=trace` and the gateway's `/api/logs/events` SSE stream could surface user content. The POC env sets `RUST_LOG=ironclaw=info`.

**No upstream changes needed.** TEE confidentiality posture is intact.

### 6. Web gateway authentication — **OK (with a UX caveat)**

`Authorization: Bearer $GATEWAY_AUTH_TOKEN` (`src/channels/web/CLAUDE.md`). `/api/health` is unauthenticated. The token is a fixed env-var bearer; no DB lookups, no OAuth required.

**UX caveat for the POC:** browsers won't send `Authorization` on a top-level navigation, so loading `https://<vm>.vm.scrtlabs.com/` directly will return 401. Options for the POC, in increasing complexity:

1. **Use a browser extension** that injects the Authorization header (e.g. ModHeader). Cheapest.
2. **Use the OpenAI-compatible proxy via curl/SDK**: IronClaw exposes `/v1/chat/completions` (see `openai_compat.rs` in the web gateway). Headless usage from a Python/JS SDK works fine with bearer auth.
3. **Front the gateway with a small auth-shim container** (caddy/nginx) that does basic-auth or token-in-cookie. Adds a third container.

POC pick: **option 1 (browser extension) for the demo, option 2 for any programmatic verification.** Documented but no code change needed.

### 7. PID lock survival across restarts — **OK (with deploy convention)**

IronClaw writes `~/.ironclaw/ironclaw.pid` and refuses to start if it sees a live PID file. If we put `~/.ironclaw/` on a persistent volume, a hard kill leaves a stale lock that blocks restart.

**Resolution:** Don't make `~/.ironclaw/` a persistent volume. The image already populates it (WASM tools/channels live there in `runtime-staging`); on container restart it's repopulated from the image layer. Only PG state needs persistence.

### 8. Image digest pinning — **OK (deploy hygiene)**

SecretRelay convention: compose pins `image: <registry>/<repo>@sha256:<digest>`. We adopt the same. The POC draft uses `nearaidev/ironclaw:0.28.1` (tag form) as a placeholder; at actual deploy time we resolve to a digest via `docker manifest inspect` and update the compose. Mirrors the SecretRelay CI digest-pinning pattern.

### 9. Attestation surface — **OK (provided by SecretVM)**

`https://<vm>:29343/cpu.html`, `:29343/self.html` are built into the SecretVM host. The `self.html` attestation report includes the deployed compose and image digests, so it inherently attests "this is the image we said we'd run." We need to do nothing inside IronClaw to expose attestation.

---

## Minimal POC config

### Compose shape (`drafts/docker-compose.yml`)

Two services:

- `ironclaw` — pulled from Docker Hub, digest-pinned, publishes 3000, `depends_on` postgres health, restart unless-stopped, all env via passthrough.
- `postgres` — pgvector/pgvector:pg16, named volume `pgdata`, healthcheck, no published ports.

Conventions mirror SecretRelay (`reference/secretornot/docker-compose.yaml`): no Traefik labels, no build context, restart policy, env passthrough. Differences: two services instead of one, named volume for PG state, depends_on with healthcheck for boot ordering.

### Env file (`drafts/.env.example`)

Headless-bootstrap env: `--no-onboard`, `SECRETS_MASTER_KEY` env mode, `LLM_BACKEND=openai_compatible` pointing at SecretAI (`https://secretai-rytn.scrtlabs.com:21434/v1`), `LLM_MODEL=llama3.3:70b` (tool-calling-capable), gateway bearer token, all optional features disabled (`SANDBOX_ENABLED=false`, `HEARTBEAT_ENABLED=false`, `EMBEDDING_ENABLED=false`, `TUNNEL_PROVIDER=none`, `CLI_ENABLED=false`).

Real values stay out of git. The example file uses `CHANGE_ME` placeholders.

### Disabled or stubbed features

| Feature | How disabled |
|---|---|
| Docker-in-Docker worker sandbox | `SANDBOX_ENABLED=false` |
| Heartbeat (background) | `HEARTBEAT_ENABLED=false` |
| Semantic embeddings | `EMBEDDING_ENABLED=false` |
| Routines (cron) | Not configured (no routines added; engine starts idle) |
| MCP servers | Not configured (none added) |
| Tunneling (ngrok/cloudflared/tailscale) | `TUNNEL_PROVIDER=none` |
| Telegram/Slack/Signal/HTTP webhook channels | Tokens unset; channels stay un-activated |
| TUI / CLI mode | `CLI_ENABLED=false` (gateway-only) |
| OAuth login (Google/GitHub/Apple/NEAR) | `OAUTH_ENABLED` unset (default false) |
| Auto-approval of tool actions | `--auto-approve` flag NOT passed |

### Image / runtime details

- **Image:** `nearaidev/ironclaw:0.28.1` (placeholder — pin to a specific `@sha256:...` digest before actual deploy)
- **Entrypoint override:** `["ironclaw", "--no-onboard"]` (mirrors `deploy/ironclaw.service`)
- **Ports:** publish `3000:3000` on ironclaw, nothing on postgres
- **Volumes:** `pgdata:/var/lib/postgresql/data` (named volume — survives via `--persistence`)
- **Networks:** default compose network is fine

---

## Open questions

Most of the original open questions resolved once SecretAI was confirmed as the LLM backend. Remaining:

1. **Which SecretAI model to use.** The draft env pins `llama3.3:70b` (per prior project usage and known tool-calling support). Confirm this is the right choice — and whether SecretAI's tool-calling support on `llama3.3:70b` covers everything IronClaw expects (parallel tool calls, JSON mode if used, etc.). Fallbacks if needed: hit `/v1/models` on SecretAI to enumerate.
2. **Exact image digest to pin.** The POC drafts use `nearaidev/ironclaw:0.28.1` as a tag-based placeholder. At deploy time we resolve to a digest via `docker manifest inspect nearaidev/ironclaw:0.28.1` and update `drafts/docker-compose.yml`.
3. **Whether to expose `/v1/chat/completions` publicly.** IronClaw's gateway includes an OpenAI-compatible proxy at `/v1/...`. With bearer auth it could be useful for testing, but it makes the agent indistinguishable from a plain proxy from the outside. Leave it on; document that the bearer token gates all `/v1/` traffic too.
4. **Whether to use `IRONCLAW_IN_DOCKER=true` for the restart loop.** The `.env.example` notes this enables a Docker-aware exit-code-based restart. Compose `restart: unless-stopped` handles this externally already. Default in our draft: leave it off; rely on compose restart policy.
5. **Where to publish our own forked image, if we ever need one.** For the POC we use upstream's `nearaidev/ironclaw` directly. If patching becomes necessary later, mirror SecretRelay's GHCR + digest-rewrite CI flow.

---

## Sequenced task list

Effort: S = under a day, M = 1–3 days, L = a week or more. Origin: **config** = no upstream change, **fork** = requires a patched IronClaw fork.

| # | Task | Effort | Origin | Notes |
|---|---|---|---|---|
| 1 | Confirm `LLM_MODEL=llama3.3:70b` (or pick alt) by hitting `https://secretai-rytn.scrtlabs.com:21434/v1/models` with the SecretAI key | S | config | Verifies tool-calling capability for the chosen model. |
| 2 | Resolve a specific `nearaidev/ironclaw` image digest, update compose | S | config | One-shot deploy hygiene step. |
| 3 | Real `.env` from `drafts/.env.example`: generate `SECRETS_MASTER_KEY`, `GATEWAY_AUTH_TOKEN`, `POSTGRES_PASSWORD`, set `LLM_API_KEY` | S | config | Keep this file out of git. |
| 4 | `secretvm-cli vm create -n ironclaw-poc -t medium -d drafts/docker-compose.yml -e .env -p -s` | S | config | First create. `-p` for persistence, `-s` for TLS. |
| 5 | Smoke test: `curl https://<vm>.vm.scrtlabs.com/api/health` returns 200 | S | config | First sanity check. |
| 6 | Bearer-authenticated `curl` to `/api/chat/send`, verify LLM call routes to SecretAI (check container logs via `secretvm-cli vm logs`) | S | config | End-to-end golden path. |
| 7 | Browser test with ModHeader (or equivalent): load web UI, log in with bearer, chat | S | config | Demo UX. |
| 8 | Pull attestation: `curl https://<vm>.vm.scrtlabs.com:29343/cpu.html` + `:29343/self.html`. Confirm image digest in report matches deployed compose | S | config | The "attested" claim, validated. |
| 9 | (If demoing) write a tiny `client_demo.py` that uses the OpenAI SDK against `https://<vm>.vm.scrtlabs.com/v1` with the bearer token | S | config | Followup. |
| 10 | Document POC verification steps as a runbook in `notes/` | S | config | Followup. |
| 11 | Decide on upgrade/redeploy flow: `secretvm-cli vm edit` vs new VM. Document | S | config | Followup. |

The drafts in this repo (`drafts/docker-compose.yml`, `drafts/.env.example`) cover everything needed to attempt tasks 1–9.

---

## Next decision points

1. **Approve / revise this plan.** Most of all, the gap analysis: do you agree nothing here needs an upstream patch?
2. **Confirm the SecretAI model choice.** Draft uses `llama3.3:70b`. If you want a different model, easy swap in `.env`.
3. **Pin an image digest.** Either I do it now from `docker manifest inspect nearaidev/ironclaw:0.28.1`, or we wait until you're ready to create the VM.
4. **Pick the demo path.** Bearer-via-browser-extension is cheapest. A reverse-proxy auth shim is more polished but adds a third container.
