# SecretVM Facts (relevant to the POC)

Confirmed during planning. These are the load-bearing assumptions the plan is built on. Update this file if any are revised.

## Deployment unit

- A SecretVM is created from a docker-compose file + an env file, both uploaded via `secretvm-cli vm create`.
- Default registry is `docker.io` (`-r` flag overrides). Public images like `nearaidev/ironclaw` work without auth.
- `secretvm-cli vm edit <vmId>` swaps in a new compose / env — used for upgrades.
- The `.env` file is uploaded at create/edit time and is NOT in the repo. Real secrets stay out of git.

## Size tiers

| Tier | vCPU | RAM  | Disk  | Price       |
|------|------|------|-------|-------------|
| small  | 1    | 2 GB  | 20 GB  | $0.03/hour |
| medium | 2    | 4 GB  | 40 GB  | $0.06/hour |
| large  | 4    | 8 GB  | 80 GB  | $0.12/hour |

**POC target: medium.** 2 vCPU / 4 GB RAM is tight but workable for PG+pgvector+IronClaw if we keep heavy features off (SANDBOX, HEARTBEAT, EMBEDDING) and tune PG (`shared_buffers ~256 MB`, `work_mem ~16 MB`, `max_connections ~20`). If the agent starts swapping or OOMing once any real workload runs, bump to `large`.

## Persistence

- `secretvm-cli vm create -p` (`--persistence`) persists the **whole VM disk including docker named volumes**.
- So a normal compose-named volume for `pgdata` survives container/VM restart. No bind-mount gymnastics required.

## Ingress (HTTPS)

- Pattern matches existing deployments (e.g. SecretRelay at `https://ivory-horse.vm.scrtlabs.com/`): SecretVM gives the VM an HTTPS URL and routes to the published port from the compose.
- Convention: **only the service you want public should publish a port** (`ports:` block). Everything else (Postgres, internal sidecars) goes on the docker network only — no `ports:`.
- Memory note: SecretVM rewrites the deployed compose on the VM side and injects its own Traefik labels — so we don't need any `traefik.*` labels in the repo compose. **Check the on-VM compose, not the repo, to see what's actually running.**
- For IronClaw: publish `3000` (web gateway) from the `ironclaw` service. Postgres has no `ports:`.

## Attestation

In-VM attestation endpoint runs on the host alongside the VM:

| Endpoint | Returns |
|---|---|
| `https://<vm-url>:29343/cpu.html` | CPU attestation quote (Intel TDX or AMD SEV) |
| `https://<vm-url>:29343/self.html` | Attestation report including runtime + Docker container metadata |
| `https://<vm-url>:29343/gpu.html` | GPU quote (GPU-equipped tiers only) |

- The host generates a TLS cert at VM startup; the cert fingerprint is embedded in the report's `reportdata` field. This binds the HTTPS channel to the attestation — a verifier checks the cert fingerprint matches the attested value.
- Alternative: `secretvm-cli vm attestation <vmId>` retrieves the same data out-of-band.
- **For the POC, IronClaw itself does not need to fetch or expose its quote.** A verifier hits `:29343/cpu.html` or runs `secretvm-cli vm attestation` to confirm the running image digest. This is one of the bigger simplifications — we don't have to patch IronClaw to be attestation-aware.

## What's NOT in scope for SecretVM

- No managed Postgres (so PG runs as a sibling container — confirmed by `secretvm-cli` workflow showing compose-as-deployment-unit).
- No load balancer between VMs (single-VM deployment).
- No native secret store (the secret env file is the only mechanism; we don't get a host-side vault).
- No GPU on small/medium/large tiers in our case (LLM is remote via SecretInference).
