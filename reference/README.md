# reference/

Known-good SecretVM deployment artifacts, used as the template for the IronClaw POC shape.

## secretornot/

Copied from `C:\dev\secretornot` (the "SecretRelay" deployment the user pointed to). The router is deployed to `ivory-horse.vm.scrtlabs.com`.

Files of interest:
- `docker-compose.yaml` — single-service compose. Image pinned by `@sha256:` digest. No Traefik labels (SecretVM injects them on the VM). Env passthrough via `${VAR}` references.
- `.env.example` — flat KEY=VALUE env file. Real secrets live in `.env` (gitignored), example uses placeholders.
- `Dockerfile` — simple multi-stage-free Python image; copies code, installs deps, exposes one port.
- `.dockerignore` — excludes `.venv/`, `.git/`, training data, secrets.
- `.github/workflows/docker-publish.yml` — the SecretVM CI convention:
  1. Build image on push to `main`.
  2. Push to GHCR with `latest` and `sha-<commit>` tags.
  3. Sed `image:` line in `docker-compose.yaml` to the new `@sha256:...` digest.
  4. Commit the updated compose back to `main`.
  - This is what makes the deployment attestable: the on-VM compose pins an immutable digest that matches what CI built.
- `README.md` / `PLAN.md` — context only.

## Conventions extracted (apply to IronClaw POC)

1. **Image-by-digest, not tag.** Compose uses `ghcr.io/<owner>/<repo>@sha256:<digest>`. Tags are mutable; digests aren't. CI rewrites the digest on every build.
2. **No Traefik labels in the repo compose.** SecretVM injects ingress on its side. Memory note: SecretVM rewrites docker-compose and injects Traefik router labels — check on-VM compose, not repo.
3. **Env passthrough is dumb and flat.** `.env` file at the repo root, `environment:` block in compose references `${VAR}`. No layered config, no profiles, no overrides.
4. **Bind-mount for things that need to persist across deploys or be inspected from outside the image** (e.g. `./feedback.jsonl`). Named volumes weren't used by SecretRelay — but IronClaw needs Postgres, so we will need them.
5. **`restart: unless-stopped`** on every service.
6. **Single host port mapping** when the service needs to be reachable directly. SecretVM exposes whatever is published.
7. **No build context in repo compose** — pulled image only. Builds happen in CI.

## What's not in SecretRelay that IronClaw needs

- A second container (Postgres) → named volume for `pgdata`.
- A startup-order dependency (`depends_on` with healthcheck) for the agent to wait for PG.
- A non-interactive bootstrap path (SecretRelay is stateless and stateless-bootstrap; IronClaw has an onboarding wizard).
- Attestation retrieval surface — SecretRelay relies on the SecretVM host for this; IronClaw will do the same.
