# IronClaw Deployment Inventory

Read against IronClaw **v0.28.1** (`C:\dev\ironclaw-main`, tarball snapshot, no commit hash).

This file is the longer-form companion to the inventory section of the main plan. Most of the substantive findings are duplicated into `SECRETVM_POC_PLAN.md`; this file holds the references and details that don't fit there.

## Authoritative upstream files

- `README.md` — install, configuration, architecture overview
- `CLAUDE.md` — project structure, current limitations, dev workflow
- `AGENTS.md` — coding rules
- `Dockerfile` — multi-stage `runtime` and `runtime-staging` images (default target `runtime-staging`)
- `Dockerfile.worker` — sandbox worker image (only needed when `SANDBOX_ENABLED=true`; **not used in POC**)
- `Dockerfile.test` — minimal libsql gateway-only image — uses `ENTRYPOINT ["ironclaw", "--no-onboard"]` and is the closest thing upstream has to a "headless POC" reference
- `docker-compose.yml` — local-dev Postgres only; not a production deploy unit
- `deploy/setup.sh`, `deploy/ironclaw.service`, `deploy/cloud-sql-proxy.service`, `deploy/env.example` — upstream's GCP Compute Engine production deploy template. `ironclaw.service` runs the container with `--no-onboard`. `deploy/env.example` is the canonical minimal headless env file.
- `src/setup/README.md` — authoritative spec for the onboarding wizard, including the headless-bootstrap escape hatches
- `src/channels/web/CLAUDE.md` — gateway architecture, auth, route inventory
- `src/main.rs` — startup sequence
- `src/cli/mod.rs` — CLI surface (global flags: `--no-onboard`, `--cli-only`, `--no-db`, `--message`, `--auto-approve`, `--config`)
- `railway.toml` — Railway deploy config, exposes health check at `/api/health`

## CLI flags relevant to headless deploys

| Flag | Effect |
|---|---|
| `--no-onboard` | Suppresses auto-trigger of the setup wizard on startup. **Required for SecretVM.** |
| `--cli-only` | Disables all non-CLI channels: webhooks, WASM channels, HTTP, Signal, relay, gateway, managed tunnel, sandbox orchestrator API. **NOT what we want** — we want the gateway. |
| `--no-db` | Skips DB connection. Testing only. |
| `--auto-approve` | Auto-approves standard (non-destructive) tool actions. |
| `--message <text>` | Single-message-and-exit mode. |
| `--config <path>` | Optional TOML config path. |

## Image build details

- Default image target is `runtime-staging` — includes pre-built WASM tools and channels under `~/.ironclaw/{tools,channels}`. `wasm-builder` skips Telegram explicitly because Telegram is embedded in the main binary via `include_bytes!` at compile time.
- Build uses `cargo-chef` for dependency caching, `wasm32-wasip2` target, `wasm-tools` for component packaging.
- Non-root user: `ironclaw` (UID 1000), HOME=`/home/ironclaw`, state at `/home/ironclaw/.ironclaw/`.
- `EXPOSE 3000`, default `RUST_LOG=ironclaw=info`, `ENTRYPOINT ["ironclaw"]`.
- Builds Debian-glibc, not Alpine-musl (libSQL has segfault-on-reopen issues with static musl linking).

## Bootstrap path WITHOUT the wizard

From `src/setup/README.md` lines 22–32 and `src/main.rs` line 362:

> Auto-detection via `check_onboard_needed()` in `main.rs`. Skips onboarding when `ONBOARD_COMPLETED` env var is set (written to `~/.ironclaw/.env` by the wizard). Otherwise triggers when no database is configured: `DATABASE_URL` env var is set, `LIBSQL_PATH` env var is set, or `~/.ironclaw/ironclaw.db` exists on disk.
> The `--no-onboard` CLI flag suppresses auto-detection.

So either `--no-onboard` OR `ONBOARD_COMPLETED=true` bypasses the wizard. Either way, the agent then requires its config from env, and bails with a helpful error if anything required is missing.

### Bootstrap env vars to seed directly

These are normally written to `~/.ironclaw/.env` by the wizard. To deploy headlessly, write them yourself:

```env
IRONCLAW_PROFILE=local          # optional but recommended; loads a built-in profile
DATABASE_BACKEND=postgres       # or libsql
DATABASE_URL=postgres://ironclaw:...@postgres:5432/ironclaw
SECRETS_MASTER_KEY=...          # 32-byte key, base64 encoded (Env key source)
ONBOARD_COMPLETED=true          # belt-and-suspenders alongside --no-onboard

LLM_BACKEND=openai_compatible
LLM_BASE_URL=https://secretai-rytn.scrtlabs.com:21434/v1   # SecretAI
LLM_API_KEY=...
LLM_MODEL=llama3.3:70b          # SecretAI's tool-calling-capable model

# Web gateway
GATEWAY_ENABLED=true
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=3000
GATEWAY_AUTH_TOKEN=...          # bearer token for the web UI

# Disable everything optional
CLI_ENABLED=false
SANDBOX_ENABLED=false
HEARTBEAT_ENABLED=false
EMBEDDING_ENABLED=false
TUNNEL_PROVIDER=none            # no ngrok/cloudflared/tailscale launching

# Logging
RUST_LOG=ironclaw=info
```

This is essentially `deploy/env.example` with the LLM provider swapped from NEAR AI Cloud to SecretAI (OpenAI-compatible via Ollama, standard Bearer auth).

### Secrets master key

The wizard supports three KeySources: `Keychain`, `Env`, `None`. For SecretVM (no OS keychain), we set `SECRETS_MASTER_KEY` directly in `.env`. The key encrypts the `secrets` table in the database (AES-256-GCM). Without it, the secrets-backed features (Telegram tokens, OAuth refresh tokens, MCP server creds) are unavailable — fine for the POC since we don't use any of those.

Format expected by the code: 32 bytes base64. We can generate one with `openssl rand -base64 32`.

## External network calls

Out-of-the-box network egress from the agent process:

| Destination | Triggered by | POC handling |
|---|---|---|
| LLM provider endpoint (default NEAR AI) | Every LLM call | **Repoint to SecretAI**: `LLM_BACKEND=openai_compatible`, `LLM_BASE_URL=https://secretai-rytn.scrtlabs.com:21434/v1` |
| NEAR AI auth / session refresh | `LLM_BACKEND=nearai` only | Disabled (different backend) |
| OAuth endpoints (Google/GitHub/Apple/NEAR) | `OAUTH_ENABLED=true` or user-initiated | Disabled |
| `github.com/nearai/ironclaw/releases/latest/...` | Extension registry install | Don't install extensions |
| MCP servers | User-added MCP entries | Don't add any |
| Tunnel provider (ngrok/cloudflared/tailscale) | `TUNNEL_PROVIDER != none` | `TUNNEL_PROVIDER=none` |
| Telegram / Slack / Signal APIs | Those channels enabled | Channels disabled |
| Webhook callers (inbound) | `HTTP_PORT` enabled | Webhook port not exposed |

With everything optional disabled, the only outbound calls the agent makes are to the LLM endpoint. Telemetry is off by default (`ObservabilityConfig::backend` defaults to `"none"` → `NoopObserver`). No auto-update behavior in the binary itself (the README mentions `ironclaw-update`, which is a separate installer-supplied shim).

## Ports

| Port | Purpose | When exposed |
|---|---|---|
| 3000 | Web gateway HTTP (axum) | `GATEWAY_ENABLED=true` |
| 8080 | HTTP webhook channel | `HTTP_PORT` set, webhook channel enabled |
| 50051 | Orchestrator internal HTTP API | `SANDBOX_ENABLED=true` only |
| 9876 | OAuth callback listener | OAuth flows only |

For the POC: only **3000** is exposed (and 5432 internally to the postgres sibling, not host).

## Host-only / interactive dependencies (the problem list)

1. **OS keychain access** for secrets master key — not available in a TDX VM. Mitigated by `SECRETS_MASTER_KEY` env var (KeySource::Env).
2. **Browser OAuth for NEAR AI** — `http://127.0.0.1:9876` callback unreachable from a remote browser. Setup spec explicitly calls this out (lines 672–694). Mitigated by using a non-NEAR-AI LLM backend.
3. **Interactive TTY for the wizard** — mitigated by `--no-onboard`.
4. **OS service install** (`ironclaw service install`) — launchd/systemd integration on a host OS. Not relevant; we use docker-compose.
5. **Telegram getUpdates polling for owner binding** — interactive bootstrap step. Mitigated by disabling Telegram.
6. **PID lock at `~/.ironclaw/ironclaw.pid`** — can become stale across container restarts. Need a strategy: either delete it in entrypoint, or mount `~/.ironclaw` on a tmpfs/named volume that survives restarts cleanly.

## Quirks / build-time gotchas

- `scripts/build-all.sh` builds `channels-src/telegram` first because the main binary embeds its WASM via `include_bytes!()`. Building from source requires either running this script first or having the WASM pre-built. **Not relevant if we pull a pre-built image from GHCR.**
- The main Dockerfile's `builder` stage does NOT run `build-all.sh`. The wasm-builder stage explicitly skips Telegram. So if you build the upstream Dockerfile from a clean checkout, the Telegram WASM must already be present in the repo (it appears to be checked in). Worth confirming when we actually try to build.

## Architecture summary (one paragraph)

The IronClaw binary is the agent runtime — a Rust process that owns the LLM/tool loop, channel I/O, and persistence. PostgreSQL+pgvector is the durable store (workspace, settings, secrets, history, jobs); libSQL is the alternative single-file backend. The binary exposes a web gateway (axum, port 3000) with bearer-token auth, an HTTP webhook channel (port 8080), and optionally an orchestrator-side API (port 50051) used to manage Docker-sandboxed worker containers. WASM tools and channels live under `~/.ironclaw/`. The default LLM backend is NEAR AI but it speaks every major provider (OpenAI, Anthropic, Gemini, Bedrock, Ollama) and any OpenAI-compatible endpoint via `LLM_BACKEND=openai_compatible`. Onboarding is interactive by default but the `--no-onboard` flag plus environment variables (`DATABASE_URL`, `SECRETS_MASTER_KEY`, `LLM_*`) lets you bring up the agent fully headless.
