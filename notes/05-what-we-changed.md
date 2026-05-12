# What we changed for IronClaw on SecretVM

Bare minimum. Zero IronClaw source changes — all config.

## Compose

- Pull `nearaidev/ironclaw` from Docker Hub (no fork, no build)
- `command: ["--no-onboard"]` on the ironclaw service
- Sibling `pgvector/pgvector:pg16` service, named volume `pgdata`, no published ports
- `traefik.enable=false` label on postgres (suppresses SecretVM's auto-injected Traefik labels)
- Postgres tuned for 4 GB: `shared_buffers=256MB`, `work_mem=16MB`, `max_connections=20`
- `depends_on: postgres { condition: service_healthy }` on ironclaw
- Publish only `3000:3000` on ironclaw

## Env

- `ONBOARD_COMPLETED=true`
- `DATABASE_URL=postgres://ironclaw:...@postgres:5432/ironclaw`
- `DATABASE_POOL_SIZE=10`
- `SECRETS_MASTER_KEY` set as env var (avoids OS keychain)
- `LLM_BACKEND=openai_compatible`
- `LLM_BASE_URL=https://secretai-rytn.scrtlabs.com:21434` (no `/v1` suffix)
- `LLM_API_KEY=<SecretAI key>`
- `LLM_MODEL=qwen2.5:72b`
- `GATEWAY_ENABLED=true`, `GATEWAY_HOST=0.0.0.0`, `GATEWAY_PORT=3000`, `GATEWAY_AUTH_TOKEN=<random>`
- `SANDBOX_ENABLED=false`, `HEARTBEAT_ENABLED=false`, `EMBEDDING_ENABLED=false`, `CLI_ENABLED=false`
- `TUNNEL_PROVIDER=none`
- `RUST_LOG=ironclaw=info`
- Leave `NEARAI_BASE_URL` and `NEARAI_API_KEY` **unset** (otherwise IronClaw auto-bootstraps a NEAR-AI MCP server)
