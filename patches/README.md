# patches/

Reserved for any upstream IronClaw patches the POC plan calls for. **Currently empty.**

The plan's gap analysis concluded that no upstream changes are needed for the POC. If that holds, this directory stays empty.

The most likely reasons to populate it later:

1. **In-container attestation passthrough** — if a real demo wants the agent itself to surface its TDX quote on, say, `/api/attestation`, that's a small upstream add.
2. **Stricter outbound network policy** — IronClaw has `NetworkPolicyDecider`. If we want to harden egress (only allow `secretai-rytn.scrtlabs.com`), that's a config layer, not a patch, but might benefit from a small upstream knob.
3. **SecretAI-specific quirks** — if tool-calling, streaming, or response shape on SecretAI diverges from standard OpenAI in any way that breaks IronClaw, that's where a patch would land. None known at planning time.

Until one of these is needed, don't add patches.
