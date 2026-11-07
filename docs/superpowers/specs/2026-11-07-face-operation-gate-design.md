# Face operation callback gate

This implements the host-testable callback-lifetime part of the existing
ColorOS Face Unlock feasibility design. It does not register a face provider,
load a matcher, modify a ROM, or perform authentication. The owner authorized
autonomous host work and prohibited phone interaction; that prohibition remains.

The future framework provider will issue one opaque in-process token for each
operation and capture it in that operation's Binder callback. Tokens must never
be reconstructed from untrusted IPC fields. The caller UID must be captured on
the Binder thread before clearing identity or posting work. All gate methods
run on the same framework handler thread that constructed the gate.

`FaceOperationGate` admits callback envelopes only for the active token, its
owner-user engine UID, a strictly increasing positive sequence, and an elapsed
realtime value before the request deadline. Initial support is owner user 0
and a regular application UID 10000–19999. Nonzero crypto operation IDs are
rejected: this proposed software matcher must not service cryptographic requests.

An admitted terminal callback, cancellation, or timeout invalidates the active
token before any later callback can be admitted. A new operation cannot begin
until the same engine acknowledges closure. A verified Binder-death event may
release the matching token without closure acknowledgement. A delayed death,
timeout, closure, or result for an older token must not affect a replacement
request, including one with the same request ID and engine UID.

The gate does not inspect face IDs, matcher scores, templates or HATs. Admitting
an envelope is not a successful match. The future provider must still validate
payloads, engine identity/signature, enrollment persistence, biometric policy,
strong-auth state and lockout through the existing Android clients. It must not
submit a replayed enrollment HAT or manufacture an authentication token.

No adapter or image recipe will reference this component until the isolated
engine, storage, donor ABI, UI, and real device tests from the feasibility design
have passed. Tests exercise actual state transitions and UID/token/sequence/
deadline boundaries on the host without camera or phone access.
