# ironclaw-secretvm-poc

Deployment evaluation and POC artifacts for running [IronClaw](https://github.com/nearai/ironclaw) (NEAR AI's Rust personal-agent runtime) inside a [SecretVM](https://docs.scrt.network/secret-network-documentation/secret-vm) Intel TDX confidential VM.

This work is for Secret Network Foundation. The goal is to demonstrate IronClaw running inside SecretVM and using [SecretAI](https://secretai-rytn.scrtlabs.com:21434) (TEE-hosted, OpenAI-compatible LLM endpoint backed by Ollama) as its LLM backend, so the agent runtime and the inference are both attested.

## Status

**Live test deploy verified.** End-to-end chat through `https://purple-hare.vm.scrtlabs.com/` to SecretAI (`qwen2.5:72b`) is working on a SecretVM medium tier. See `notes/04-deploy-findings.md` for what we learned from the actual deploy.

(Drafts in this repo have been updated to match what actually works on a SecretVM, not just what looks right on paper.)

## Upstream reference

- Repo: <https://github.com/nearai/ironclaw>
- Local read-only mirror: `C:\dev\ironclaw-main`
- Read against IronClaw **v0.28.1** (from upstream `Cargo.toml`).
  The local mirror at `C:\dev\ironclaw-main` is a tarball-style snapshot, not a git checkout, so no commit hash is pinned here. If a specific commit is required for reproducibility, re-clone upstream and capture `git rev-parse HEAD`.

The upstream tree is **read-only**. All POC output lives in this repo.

## Layout

- `SECRETVM_POC_PLAN.md` — the deliverable: architecture summary, component inventory, gap analysis, minimal POC config, open questions, sequenced task list.
- `notes/05-what-we-changed.md` — **TL;DR for someone who just wants to know what's different from stock IronClaw.** Read this one first.
- `reference/` — copies of SecretRelay deployment artifacts used as a SecretVM template.
- `drafts/` — draft compose file and env example for the SecretVM deployment.
- `notes/` — longer-form research notes (IronClaw architecture deep-dive, SecretVM specifics, live-deploy findings).
- `patches/` — placeholder for any upstream IronClaw patches the plan calls for.

## SecretVM target

- Single VM, medium size tier (assumption).
- Docker-compose deployment unit, attestation quote retrievable.
- LLM backend: SecretAI (OpenAI-compatible at `https://secretai-rytn.scrtlabs.com:21434`, standard Bearer auth).
