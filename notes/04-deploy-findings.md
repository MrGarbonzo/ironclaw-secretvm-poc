# What we learned from the first live deploy

Deployed to a SecretVM at `purple-hare.vm.scrtlabs.com` (IP 67.43.239.13, medium tier). End-to-end chat through IronClaw → SecretAI verified working. Everything below is from observing the rendered on-VM compose at `/mnt/secure/docker_wd/docker-compose.yaml`.

## On-VM directory layout

```
/mnt/secure/
├── docker_wd/
│   ├── docker-compose.yaml       <- the rewritten compose (with injected Traefik service + labels)
│   ├── .env                       <- env vars for compose interpolation (${VAR} substitution)
│   ├── usr/.env                   <- same env vars, referenced as `env_file:` on every service
│   ├── crypto/
│   └── usr/
├── cert/
│   ├── secret_vm_fullchain.pem    <- TLS cert auto-generated for the VM's *.vm.scrtlabs.com hostname
│   └── secret_vm_private.pem
├── tdx_attestation.txt            <- pre-generated attestation
├── self_report.txt
├── system_info.json
└── ...
```

## SecretVM compose rewriter

What secretvm-cli does to your compose between upload and runtime:

1. **Injects a `traefik:v2.10` service** with ports `80:80` and `443:443`. Mounts `/var/run/docker.sock` and `/mnt/secure/cert`. Configures TLS via an inline `configs:` block.
2. **Adds a `traefik` bridge network** and attaches every service to it.
3. **Injects Traefik labels on every service**, with the host rule set to the VM's auto-assigned hostname (e.g. `purple-hare.vm.scrtlabs.com`):
   ```yaml
   labels:
     - traefik.enable=true
     - traefik.http.routers.<servicename>.rule=Host(`<vm-hostname>`)
     - traefik.http.routers.<servicename>.entrypoints=websecure
     - traefik.http.routers.<servicename>.tls=true
     - traefik.http.services.<servicename>.loadbalancer.server.port=<some_port>
   ```
   The `loadbalancer.server.port` for a service that publishes a port (ironclaw → 3000:3000) is set correctly to the container-side port. For a service without `ports:` (postgres), it's set to a guessed value (we saw `80`) — i.e. **wrong**. Two services with the same `Host()` rule conflict at Traefik.
4. **Adds `env_file: - usr/.env`** to every service.
5. **Adds `SECRETVM_ENABLE_ITA_JWT=1`** (and presumably other internal vars) to the env file.

### Workaround for the postgres Traefik conflict

Set `traefik.enable=false` explicitly on postgres in the repo compose. SecretVM's rewriter respects user-set labels and won't override. This is now in `drafts/docker-compose.yml`.

## Env interpolation precedence (the confusing part)

There are two env files on the VM:

| File | Used for |
|---|---|
| `/mnt/secure/docker_wd/.env` | `${VAR}` interpolation when docker-compose renders the rendered compose |
| `/mnt/secure/docker_wd/usr/.env` | Injected into every container at runtime via `env_file:` |

When both `environment:` (with `${VAR}` interpolation) and `env_file:` define the same variable, **the `environment:` block wins inside the container.**

Practical consequence: even if `usr/.env` contains literal `${POSTGRES_PASSWORD}` (uninterpolated), the container sees the interpolated value from the `environment:` block because compose resolves `${POSTGRES_PASSWORD}` from `.env` (at the compose-file dir) at render time. So the wires connect even though the env_file looks broken on disk.

This is fine in practice — don't waste time trying to "fix" `usr/.env` — but it makes debugging confusing. Trust `docker exec <container> env | grep VAR` over reading the files.

## LLM_BASE_URL — no `/v1` suffix

IronClaw's `openai_compatible` client appends the OpenAI path segments itself (`/v1/chat/completions`, `/v1/models`, etc.). So `LLM_BASE_URL` should be the bare origin:

```env
LLM_BASE_URL=https://secretai-rytn.scrtlabs.com:21434       # correct
LLM_BASE_URL=https://secretai-rytn.scrtlabs.com:21434/v1    # wrong; doubles up to /v1/v1/...
```

The `.env.example` has been corrected.

## SecretAI model availability (as of this deploy)

SecretAI `/v1/models` returned:

| Model | Notes |
|---|---|
| **`qwen2.5:72b`** | **POC default. Strong tool-calling. Works end-to-end with IronClaw.** |
| `qwen3:8b` | Smaller; should also support tools |
| `deepseek-r1:70b` | Reasoning model; tool calling not advertised |
| `gemma3:4b` | Small; limited tool support |
| `llama3.2-vision:latest` | Vision-focused |

`llama3.3:70b` (our initial pick from prior project memory) is **not** on this instance. Always confirm against `/v1/models` before deploying.

## Three secrets that MUST be filled in before deploy

The bare draft `.env.example` has CHANGE_ME placeholders. If you upload it with placeholders left empty, postgres restart-loops with "POSTGRES_PASSWORD must be specified" and ironclaw never becomes healthy. The required three (generated on the VM in this deploy):

- `POSTGRES_PASSWORD` — `openssl rand -hex 24`
- `SECRETS_MASTER_KEY` — `openssl rand -base64 32`
- `GATEWAY_AUTH_TOKEN` — `openssl rand -hex 32`

The `LLM_API_KEY` comes from your SecretAI account.

## Deploy-time verification checklist

After `secretvm-cli vm create`, run these to confirm the deploy is healthy:

```bash
# 1. Public HTTPS health (no auth)
curl -fsS https://<vm>.vm.scrtlabs.com/api/health
# Expect: {"status":"healthy","channel":"gateway"}

# 2. Auth is enforced
curl -sS -o /dev/null -w "%{http_code}\n" -X POST https://<vm>.vm.scrtlabs.com/api/chat/send
# Expect: 401

# 3. Attestation endpoints reachable
curl -fsS -o /dev/null -w "%{http_code}\n" https://<vm>.vm.scrtlabs.com:29343/cpu.html
# Expect: 200

# 4. End-to-end chat through to SecretAI
curl -sS https://<vm>.vm.scrtlabs.com/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:72b","messages":[{"role":"user","content":"Reply with exactly: pong"}]}'
# Expect: {"id":...,"choices":[{"message":{"role":"assistant","content":"pong"}}],...}
```

If step 4 returns `model 'X' not found`, hit `/v1/models` on SecretAI directly to enumerate.
