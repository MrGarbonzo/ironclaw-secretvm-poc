# patches/

Reserved for any upstream IronClaw patches the POC plan calls for. **Currently empty.**

The plan's gap analysis concluded that no upstream changes are needed for the POC. If that holds, this directory stays empty.

The most likely reasons to populate it later:

1. **x402 auth flow** — if SecretInference's x402 gating can't be satisfied by `Authorization: Bearer <key>` alone, IronClaw's OpenAI-compatible client may need a patch to support the x402 challenge-response (or we add a sidecar proxy instead).
2. **In-container attestation passthrough** — if a real demo wants the agent itself to surface its TDX quote on, say, `/api/attestation`, that's a small upstream add.
3. **Stricter outbound network policy** — IronClaw has `NetworkPolicyDecider`. If we want to harden egress (only allow `attestai.io`), that's a config layer, not a patch, but might benefit from a small upstream knob.

Until one of these is needed, don't add patches.
