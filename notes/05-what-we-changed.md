# What we changed to run IronClaw on SecretVM

**Headline: zero source changes to IronClaw.** The image is `nearaidev/ironclaw:0.28.1` pulled straight from Docker Hub. The entire adaptation is in the compose file and the env file. Upstream already supports headless deploys — we just walk the paved path with SecretVM-specific seasoning.

If you only read one document in this repo, read this one. The other notes go deeper.

---

## Diff from upstream's prod env (`deploy/env.example`)

Upstream's reference deploy is GCP Compute Engine + Cloud SQL. Our env diverges along four axes:

### LLM backend: NEAR AI Cloud → SecretAI

```diff
-NEARAI_API_KEY=CHANGE_ME
-NEARAI_MODEL=claude-3-5-sonnet-20241022
-NEARAI_BASE_URL=https://cloud-api.near.ai
+LLM_BACKEND=openai_compatible
+LLM_BASE_URL=https://secretai-rytn.scrtlabs.com:21434
+LLM_API_KEY=...                          (SecretAI key)
+LLM_MODEL=qwen2.5:72b
+LLM_REQUEST_TIMEOUT_SECS=180
```

Two non-obvious traps the live deploy taught us:
- `LLM_BASE_URL` is the **bare origin**, no `/v1` suffix. IronClaw's `openai_compatible` client appends `/v1/...` path segments itself.
- **Leave `NEARAI_*` unset.** If both `NEARAI_BASE_URL` and `NEARAI_API_KEY` are set, IronClaw silently auto-bootstraps a NEAR-AI MCP server — i.e. it'd make outbound calls to NEAR AI from inside the TEE. Defensive omission.

### Secrets master key: OS keychain → env var

Upstream's wizard prefers the OS keychain for the AES-256-GCM master key that encrypts the `secrets` table. A TDX VM has no OS keychain. IronClaw already supports `KeySource::Env`:

```env
SECRETS_MASTER_KEY=<openssl rand -base64 32>
```

No upstream change needed — just pick the mode that fits headless.

### Bootstrap: skip the wizard entirely

```env
ONBOARD_COMPLETED=true
DATABASE_BACKEND=postgres
DATABASE_URL=postgres://ironclaw:...@postgres:5432/ironclaw
DATABASE_POOL_SIZE=10                    # down from upstream default 30
```

Combined with `command: ["--no-onboard"]` in the compose. Upstream's own `deploy/ironclaw.service` does exactly the same.

### Disable everything optional

Same as upstream's prod, plus a couple more:

```env
CLI_ENABLED=false
SANDBOX_ENABLED=false        # no Docker-in-Docker workers inside the TEE
HEARTBEAT_ENABLED=false      # no periodic background tasks
EMBEDDING_ENABLED=false      # no semantic search (SecretAI /v1/embeddings is in progress anyway)
TUNNEL_PROVIDER=none         # no outbound ngrok/cloudflared/tailscale
RUST_LOG=ironclaw=info       # never debug/trace in production — gateway SSE stream surfaces user content otherwise
```

All Telegram/Slack/Signal/Discord tokens left unset → those channels stay un-activated.

### Web gateway auth

```env
GATEWAY_ENABLED=true
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=3000
GATEWAY_AUTH_TOKEN=<openssl rand -hex 32>
```

Single shared bearer token. No OAuth, no OIDC. Multiple testers share the same token.

---

## Diff from upstream's compose (`docker-compose.yml`)

Upstream's compose is local-dev only (one Postgres service, no IronClaw). Ours is the deploy unit. Key shape differences:

### Sibling Postgres, tuned for SecretVM medium

```yaml
postgres:
  image: pgvector/pgvector:pg16
  environment:
    POSTGRES_DB: ironclaw
    POSTGRES_USER: ironclaw
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  command:
    - postgres
    - -c
    - shared_buffers=256MB
    - -c
    - work_mem=16MB
    - -c
    - max_connections=20
  volumes:
    - pgdata:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ironclaw -d ironclaw"]
  # SecretVM injects Traefik labels on every service by default.
  # This tells Traefik to ignore postgres, avoiding a duplicate
  # router rule on the same hostname.
  labels:
    - "traefik.enable=false"
```

Upstream prod uses Cloud SQL Auth Proxy. SecretVM has no equivalent, so PG runs in the same compose. The PG tuning matters at the 4 GB tier — defaults would crowd out IronClaw.

### IronClaw service with depends_on + healthcheck gate

```yaml
ironclaw:
  image: nearaidev/ironclaw:0.28.1
  command: ["--no-onboard"]
  depends_on:
    postgres:
      condition: service_healthy
  ports:
    - "3000:3000"
  environment:
    # all the env vars above
```

The `service_healthy` condition is the critical bit — without it, IronClaw races PG init and crashes on first connect.

### Only one published port

`ironclaw` publishes `3000:3000`. Postgres has no `ports:` block — internal docker network only. This (plus `traefik.enable=false` on postgres) makes the gateway the unambiguous public surface.

---

## What we did NOT have to change

Things I expected to fight that turned out to be free:

- **IronClaw source code.** Zero patches. The image is upstream's published `nearaidev/ironclaw`.
- **Attestation.** SecretVM provides `:29343/cpu.html` and `:29343/self.html` natively. No agent-side attestation code. The TDX quote covers the running image digest and the deployed compose.
- **HTTPS termination.** SecretVM auto-injects a `traefik:v2.10` service and assigns a valid-TLS `<adjective>-<animal>.vm.scrtlabs.com` hostname. We just publish port 3000 and Traefik routes to it.
- **Image build / CI.** Pulling upstream's Docker Hub image works. No fork, no GHCR, no digest-rewrite pipeline.
- **The `--no-onboard` flag.** Already existed upstream (see `Dockerfile.test` and `deploy/ironclaw.service`).
- **Headless secrets master key.** `KeySource::Env` mode already supported.
- **OpenAI-compatible LLM backend.** First-class in IronClaw via `LLM_BACKEND=openai_compatible`. SecretAI is OpenAI-compatible via Ollama. Drop-in.

The thesis going in — "this is a config exercise, not a fork" — held up.

---

## Where to dig deeper

- `SECRETVM_POC_PLAN.md` — full gap analysis with source-code citations
- `notes/01-ironclaw-inventory.md` — the IronClaw deployment surface, line-by-line
- `notes/02-secretvm-facts.md` — SecretVM platform facts (size tiers, attestation endpoints, persistence semantics)
- `notes/03-gap-followups.md` — the receipts behind every "works as-is" claim
- `notes/04-deploy-findings.md` — what we learned from the actual live deploy: SecretVM's compose rewriter, env-file precedence quirks, model availability
- `drafts/docker-compose.yml`, `drafts/.env.example` — the runnable artifacts
