# Face Operation Gate Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this isolated host-only component. Do not interact with the phone or register a provider.

**Goal:** Implement and verify callback lifetime isolation for a future software face provider.

**Architecture:** One thread-confined gate owns one opaque operation token. Active, closing and idle phases prevent stale callbacks and reuse before camera closure. It validates envelopes, not authentication results.

**Tech Stack:** Java without Android dependencies; a Java behavioral harness launched by Python unittest.

**Spec:** `docs/superpowers/specs/2026-11-07-face-operation-gate-design.md`

## Global Constraints

- No phone access, provider registration, image rebuild or installation.
- Owner user 0 and application UID 10000–19999 only; nonzero crypto operation IDs are rejected.
- No HAT, template, matcher score or face ID enters this gate.
- Token identity is local object identity captured by a per-operation callback; no IPC deserialization of tokens.
- All state transitions occur on the constructing thread; wrong-thread use throws without mutation.
- Keep the current fingerprint implementation and ROM recipes unchanged.

## Review Focus

- Delayed closure/death/timeout for an old request cannot cancel a new request with reused IDs.
- Wrong caller UID or foreign token cannot consume a valid sequence or change state.
- The deadline itself is expired; a terminal result closes admission before subsequent callbacks.
- Cancellation never allows reuse of the engine before a matching closure/death event.
- Host test success must not be presented as working Face Unlock or framework integration.

### Task 1: Gate and behavioral checks

**Files:**
- Create `ports/coloros17/face/FaceOperationGate.java`.
- Create `ports/coloros17/face/FaceOperationGateTest.java`.
- Create `ports/coloros17/face/README.md`.
- Create `tests/test_coloros17_face_gate.py`.

**Interfaces:**
- Produces `FaceOperationGate`, `Operation {ENROLL, AUTHENTICATE}`, `Phase {IDLE, ACTIVE, CLOSING}`, and opaque `Token`.
- `begin(int userId, int engineUid, long requestId, Operation operation, long cryptoOperationId, long now, long deadline)` returns a fresh `Token` or null on refusal.
- `receive(Token token, int callerUid, long sequence, long now, boolean terminal)` returns whether an envelope may be forwarded; it does not decide authentication.
- `cancel(Token)`, `expire(Token,long now)`, `acknowledgeClosed(Token,int callerUid)`, and `engineDied(Token)` return whether the matching transition occurred; `phase()` reports state.

- [x] Write tests for valid admission, invalid begin inputs, wrong UID/token, replay/out-of-order sequences, deadline boundaries, terminal/cancel closure, stale closure/death/timeout after reuse, and cross-thread rejection. Write only API stubs needed to compile.
- [x] Run `python3 -B -m unittest discover -s tests -p test_coloros17_face_gate.py -v`. Expected: a behavioral failure because the stub refuses a valid request.
- [x] Implement the state transitions with fresh token identity and no Android or matcher dependency.
- [x] Run the same command. Expected: all Java cases and the Python wrapper pass.
- [x] Run `MYSTIC_SOURCE_ROOT=<verified readers> COLOROS_NATIVE_TOOL_DIR=/usr/bin python3 -B -m unittest discover -s tests`. Expected: full host suite passes; report any actual skips or failures.
- [x] Document the integration boundary and commit. Do not deploy.

## Final review

After the task passes, obtain a read-only review from its starting commit. Fix Important/Critical findings with failing regression tests before publishing the source. This review does not authorize deployment.

Final review: no Critical/Important findings; one documentation minor recorded in `ports/coloros17/face/validation.json`. The component remains unintegrated.
