# Gap Analysis Followups

Items where the plan answers "works as-is" but the answer rests on a chain of source-code observations. If anyone challenges the plan, these are the receipts.

## "Onboarding is bypassable headlessly"

Receipts:

- `src/main.rs:362` — `if !cli.no_onboard && let Some(reason) = ironclaw::setup::check_onboard_needed()`. The `--no-onboard` flag short-circuits the auto-wizard.
- `src/setup/README.md:24–32` — auto-detect skips when `ONBOARD_COMPLETED=true` OR any of `DATABASE_URL` / `LIBSQL_PATH` is set OR `~/.ironclaw/ironclaw.db` exists.
- `src/setup/README.md:596` — `KeySource::Env` is a supported master-key source.
- `deploy/ironclaw.service:17–18` — upstream's own production systemd unit runs `ironclaw ... --no-onboard`.
- `Dockerfile.test:58` — even the lightweight test image entry-points to `ironclaw --no-onboard`.

If a future IronClaw version removes `--no-onboard` or changes the bootstrap env precedence, this plan needs revisiting. Worth re-checking on every IronClaw bump.

## "LLM_BACKEND=openai_compatible is clean"

Receipts:

- `.env.example:62–69` — documents the `openai_compatible` path with `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`.
- `crates/ironclaw_llm/` is the extracted multi-provider crate; the provider is selected by `LLM_BACKEND` in `LlmConfig::resolve()`.
- `src/setup/README.md:670–694` ("Remote Server Authentication") explicitly recommends switching off NEAR AI for headless deploys.

The one residual NEAR-AI sneak path:

- `.env.example:45–47` — *"When both NEARAI_BASE_URL and NEARAI_API_KEY are set at startup, IronClaw also bootstraps a persisted `nearai` MCP server using the same base URL and Authorization header."*
- Mitigation: leave both `NEARAI_*` vars unset. Our env example omits them and the compose env block doesn't set them.

If someone adds `NEARAI_BASE_URL` to the env (e.g. copying from `.env.example`), the agent will silently bootstrap an MCP entry that calls back to NEAR. Worth a sanity check post-deploy: `ironclaw mcp list` should be empty (we can run it inside the container with `secretvm-cli vm logs` after triggering, or via the web gateway).

## "No telemetry / call-home"

Receipts:

- `src/observability/mod.rs:33–38` — `ObservabilityConfig::default()` returns `backend: "none"`. The factory at `:44–49` returns `NoopObserver` for any value other than `"log"`.
- README:46 — "no hidden telemetry or data harvesting" (asserted publicly; consistent with source).
- All `releases/latest` URLs in source are for extension registry artifact downloads — gated on the user installing an extension. With no extensions installed, no fetches.

## "Web gateway bearer token is the only auth needed"

Receipts:

- `src/channels/web/CLAUDE.md:16` — *"`platform/auth.rs` — Bearer token middleware (`Authorization: Bearer <GATEWAY_AUTH_TOKEN>`)."*
- `src/channels/web/CLAUDE.md:67–70` — Only `/api/health` and `/oauth/callback` are public; everything else is auth-gated.

OAuth and OIDC are additive (opt-in env vars) — not setting them keeps the auth surface to bearer-only.

## What we haven't verified end-to-end

- That the running `nearaidev/ironclaw:0.28.1` image actually has the Telegram WASM embedded (i.e. the upstream CI build succeeds with `include_bytes!()`). We assume yes because that's the image they publish. If it doesn't, the binary won't start — easy to detect on the first `secretvm-cli vm logs`.
- That `LLM_BACKEND=openai_compatible` against SecretAI's URL succeeds end-to-end. Auth is confirmed standard `Authorization: Bearer <key>` (no x402), and the supported endpoints cover what IronClaw uses (`/v1/chat/completions`, `/v1/models`, tool-calling on `llama3.3:70b`). The only blind spot is whether tool-calling parallelism / JSON-mode behavior matches IronClaw's expectations — easy to confirm in the first end-to-end run.
- That the SecretVM-injected Traefik labels correctly route the `https://<vm>.vm.scrtlabs.com/` to ironclaw:3000 and NOT to anything else (because postgres has no `ports:`, it shouldn't be ambiguous, but worth confirming on the first deploy).
- That whole-disk persistence preserves the `pgdata` named volume across `secretvm-cli vm stop`/`start`. The user confirmed it does for the VM lifetime; should be fine for a POC.
