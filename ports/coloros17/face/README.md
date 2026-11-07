# Isolated face callback gate

`FaceOperationGate` is host-tested preparation for the proposed software face
provider. It is not registered with Android, compiled into the current image,
or connected to a camera, matching engine or lock screen.

The gate filters stale and replayed callback envelopes. Each operation gets a
fresh opaque token, captured by that operation's callback and death recipient.
Tokens remain in the trusted provider process; do not reconstruct them from
engine-supplied IDs. All methods run on the constructing framework handler
thread. Capture `Binder.getCallingUid()` on the Binder thread before clearing
identity or posting, and pass that captured UID to `receive` or
`acknowledgeClosed`. Never obtain the UID from the message payload.

Cancellation, expiry and terminal callbacks enter `CLOSING`; a new operation
waits for that token's genuine engine-closure acknowledgement. `engineDied` is
only for a verified Binder death notification, not an app-callable command.
The future engine must actually release its camera/native session before
acknowledging closure. This gate cannot establish that external fact.

An admitted envelope is not a match. Validate its operation, user/request IDs,
face ID and payload before admission. The full provider still needs trusted
engine package/signature checks, enrollment persistence, lockout, strong-auth,
camera privacy and Android client policy. The gate stores no HAT, face template,
frame, score or biometric result. It rejects non-owner users, non-application
UIDs and nonzero crypto operation IDs for this initial integration scope.

Run the behavioral tests without a phone:

```sh
python3 -B -m unittest discover -s tests -p test_coloros17_face_gate.py -v
```

Before any ROM integration, the separate matcher/storage prototype, exact
ColorOS provider ABI and UI path, and owner-driven real biometric tests must
pass. Host tests do not establish functioning or certified Face Unlock.
