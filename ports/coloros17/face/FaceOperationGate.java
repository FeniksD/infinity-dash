// Copyright (C) 2026 FeniksD
// SPDX-License-Identifier: Apache-2.0
package com.android.server.biometrics.sensors.face.dash;

/**
 * Filters callback lifetimes on one framework handler thread.
 *
 * <p>A token is a local capability captured by a per-operation Binder callback,
 * never deserialized from the engine. The caller must capture the Binder UID
 * before posting to this gate. Admission is not an authentication decision.
 * Payload validation and all Android biometric policy remain the provider's job.
 * This component is not integrated into a ROM or a provider.
 */
public final class FaceOperationGate {
    public enum Operation { ENROLL, AUTHENTICATE }
    public enum Phase { IDLE, ACTIVE, CLOSING }

    public static final class Token {
        private final int engineUid;
        private final long startedAt;
        private final long deadline;

        private Token(int engineUid, long startedAt, long deadline) {
            this.engineUid = engineUid;
            this.startedAt = startedAt;
            this.deadline = deadline;
        }
    }

    private final Thread owner = Thread.currentThread();
    private Token active;
    private Token closing;
    private long lastSequence;

    public Token begin(int userId, int engineUid, long requestId, Operation operation,
            long cryptoOperationId, long now, long deadline) {
        requireOwner();
        if (active != null || closing != null || userId != 0
                || engineUid < 10000 || engineUid > 19999 || requestId < 0
                || operation == null || cryptoOperationId != 0
                || now < 0 || deadline <= now) {
            return null;
        }
        active = new Token(engineUid, now, deadline);
        lastSequence = 0;
        return active;
    }

    /** Returns only whether this already-validated callback envelope is current. */
    public boolean receive(Token token, int callerUid, long sequence, long now,
            boolean terminal) {
        requireOwner();
        if (token == null || token != active || callerUid != token.engineUid
                || sequence <= lastSequence || now < token.startedAt) {
            return false;
        }
        if (now >= token.deadline) {
            closeActive();
            return false;
        }
        lastSequence = sequence;
        if (terminal) closeActive();
        return true;
    }

    public boolean cancel(Token token) {
        requireOwner();
        if (token == null || token != active) return false;
        closeActive();
        return true;
    }

    public boolean expire(Token token, long now) {
        requireOwner();
        if (token == null || token != active || now < token.deadline) return false;
        closeActive();
        return true;
    }

    public boolean acknowledgeClosed(Token token, int callerUid) {
        requireOwner();
        if (token == null || token != closing || callerUid != token.engineUid) return false;
        closing = null;
        return true;
    }

    /** Called only from a verified linkToDeath callback captured for this token. */
    public boolean engineDied(Token token) {
        requireOwner();
        if (token == null || (token != active && token != closing)) return false;
        active = null;
        closing = null;
        return true;
    }

    public Phase phase() {
        requireOwner();
        return active != null ? Phase.ACTIVE : closing != null ? Phase.CLOSING : Phase.IDLE;
    }

    private void closeActive() {
        closing = active;
        active = null;
    }

    private void requireOwner() {
        if (Thread.currentThread() != owner) {
            throw new IllegalStateException("FaceOperationGate requires its owner thread");
        }
    }
}
