// Copyright (C) 2026 FeniksD
// SPDX-License-Identifier: Apache-2.0
package com.android.server.biometrics.sensors.face.dash;

import java.util.concurrent.atomic.AtomicReference;

public final class FaceOperationGateTest {
    private static int cases;
    private static int failures;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static FaceOperationGate.Token open(FaceOperationGate gate) {
        FaceOperationGate.Token token = gate.begin(0, 10123, 9,
                FaceOperationGate.Operation.AUTHENTICATE, 0, 100, 200);
        check(token != null, "valid owner request must be admitted");
        return token;
    }

    private static void run(String name, Runnable test) {
        cases++;
        try {
            test.run();
        } catch (Throwable error) {
            failures++;
            System.err.println(name + ": " + error);
        }
    }

    public static void main(String[] args) throws Exception {
        run("current callback admission", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(gate.phase() == FaceOperationGate.Phase.ACTIVE, "active phase");
            check(gate.receive(token, 10123, 1, 100, false), "first callback");
            check(gate.receive(token, 10123, 2, 199, false), "later callback");
        });
        run("owner application and noncrypto admission boundaries", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            check(gate.begin(1, 10123, 9, FaceOperationGate.Operation.ENROLL,
                    0, 100, 200) == null, "other user");
            for (int uid : new int[]{-1, 0, 1000, 9999, 20000, 100001}) {
                check(gate.begin(0, uid, 9, FaceOperationGate.Operation.ENROLL,
                        0, 100, 200) == null, "non-owner-app UID " + uid);
            }
            check(gate.begin(0, 10123, -1, FaceOperationGate.Operation.ENROLL,
                    0, 100, 200) == null, "negative request");
            check(gate.begin(0, 10123, 9, null, 0, 100, 200) == null, "missing operation");
            for (FaceOperationGate.Operation operation : FaceOperationGate.Operation.values()) {
                check(gate.begin(0, 10123, 9, operation, 7, 100, 200) == null,
                        "crypto operation");
            }
            check(gate.begin(0, 10123, 9, FaceOperationGate.Operation.ENROLL,
                    0, -1, 200) == null, "invalid clock");
            check(gate.begin(0, 10123, 9, FaceOperationGate.Operation.ENROLL,
                    0, 100, 100) == null, "already expired");
            check(gate.begin(0, 10123, 9, FaceOperationGate.Operation.ENROLL,
                    0, 100, 99) == null, "past deadline");
            check(gate.phase() == FaceOperationGate.Phase.IDLE, "refusals leave gate idle");
            open(gate);
        });
        run("UID range endpoints and request zero", () -> {
            for (int uid : new int[]{10000, 19999}) {
                FaceOperationGate gate = new FaceOperationGate();
                FaceOperationGate.Token token = gate.begin(0, uid, 0,
                        FaceOperationGate.Operation.ENROLL, 0, 0, 1);
                check(token != null, "valid boundary UID");
                check(gate.receive(token, uid, 1, 0, true), "boundary callback");
            }
        });
        run("wrong caller cannot consume sequence", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(!gate.receive(token, 10124, 1, 101, true), "wrong UID");
            check(gate.phase() == FaceOperationGate.Phase.ACTIVE, "wrong UID cannot terminate");
            check(gate.receive(token, 10123, 1, 101, false), "valid same sequence remains usable");
        });
        run("foreign gate token cannot consume sequence", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            FaceOperationGate.Token foreign = open(new FaceOperationGate());
            check(!gate.receive(foreign, 10123, 1, 101, true), "foreign token");
            check(gate.receive(token, 10123, 1, 101, false), "current token");
        });
        run("duplicate and out of order callbacks", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(!gate.receive(token, 10123, 0, 101, false), "zero sequence");
            check(!gate.receive(token, 10123, -1, 101, false), "negative sequence");
            check(gate.receive(token, 10123, 1, 101, false), "sequence one");
            check(!gate.receive(token, 10123, 1, 102, true), "duplicate terminal callback");
            check(gate.receive(token, 10123, 3, 103, false), "sequence gap allowed");
            check(!gate.receive(token, 10123, 2, 104, false), "out of order");
            check(gate.receive(token, 10123, 4, 105, false), "next sequence");
        });
        run("deadline is exclusive", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(gate.receive(token, 10123, 1, 199, false), "before deadline");
            check(!gate.receive(token, 10123, 2, 200, true), "at deadline");
            check(gate.phase() == FaceOperationGate.Phase.CLOSING, "timeout closes admission");
            check(gate.acknowledgeClosed(token, 10123), "timeout can release after closure");
        });
        run("callback before request start is rejected", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(!gate.receive(token, 10123, 1, 99, true), "old timestamp");
            check(gate.phase() == FaceOperationGate.Phase.ACTIVE, "early callback cannot terminate");
            check(gate.receive(token, 10123, 1, 100, false), "valid timestamp");
        });
        run("terminal callback closes admission before reuse", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(gate.receive(token, 10123, 1, 101, true), "terminal callback");
            check(gate.phase() == FaceOperationGate.Phase.CLOSING, "terminal phase");
            check(!gate.receive(token, 10123, 2, 102, false), "nothing after terminal");
            check(gate.begin(0, 10123, 10, FaceOperationGate.Operation.AUTHENTICATE,
                    0, 102, 200) == null, "no reuse before engine closure");
            check(gate.acknowledgeClosed(token, 10123), "closure acknowledgement");
            open(gate);
        });
        run("cancellation waits for matching engine closure", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(gate.cancel(token), "cancel current");
            check(!gate.cancel(token), "cancel idempotence");
            check(!gate.receive(token, 10123, 1, 101, true), "canceled result");
            check(!gate.acknowledgeClosed(token, 10124), "other engine closure");
            check(gate.begin(0, 10123, 10, FaceOperationGate.Operation.ENROLL,
                    0, 101, 200) == null, "canceled engine still closing");
            check(gate.acknowledgeClosed(token, 10123), "same engine closure");
            check(gate.phase() == FaceOperationGate.Phase.IDLE, "closed");
        });
        run("only current timeout can close a request", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(!gate.expire(token, 199), "not expired yet");
            check(gate.phase() == FaceOperationGate.Phase.ACTIVE, "still active");
            check(gate.expire(token, 200), "timeout");
            check(!gate.expire(token, 201), "already closing");
            check(gate.acknowledgeClosed(token, 10123), "close timeout");
        });
        run("stale events cannot affect reused request ID", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token old = open(gate);
            check(gate.cancel(old), "cancel old");
            check(gate.acknowledgeClosed(old, 10123), "close old");
            FaceOperationGate.Token current = open(gate);
            check(old != current, "fresh capability");
            check(!gate.cancel(old), "stale cancel");
            check(!gate.acknowledgeClosed(old, 10123), "stale closure");
            check(!gate.engineDied(old), "stale death");
            check(!gate.expire(old, 1000), "stale timeout");
            check(!gate.receive(old, 10123, 99, 101, true), "stale result");
            check(gate.receive(current, 10123, 1, 101, false), "new request still works");
        });
        run("verified engine death releases active or closing token", () -> {
            for (boolean cancelFirst : new boolean[]{false, true}) {
                FaceOperationGate gate = new FaceOperationGate();
                FaceOperationGate.Token old = open(gate);
                if (cancelFirst) check(gate.cancel(old), "cancel before death");
                check(gate.engineDied(old), "current engine death");
                check(gate.phase() == FaceOperationGate.Phase.IDLE, "death releases gate");
                FaceOperationGate.Token current = open(gate);
                check(!gate.engineDied(old), "old death cannot release replacement");
                check(gate.receive(current, 10123, 1, 101, false), "replacement works");
            }
        });
        run("null and premature closure never release active gate", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(!gate.receive(null, 10123, 1, 101, true), "null result token");
            check(!gate.cancel(null), "null cancel");
            check(!gate.expire(null, 300), "null timeout");
            check(!gate.engineDied(null), "null death");
            check(!gate.acknowledgeClosed(null, 10123), "null closure");
            check(!gate.acknowledgeClosed(token, 10123), "unsolicited closure");
            check(gate.receive(token, 10123, 1, 101, false), "active request intact");
        });
        run("active request cannot be replaced", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            check(gate.begin(0, 10123, 10, FaceOperationGate.Operation.ENROLL,
                    0, 101, 200) == null, "busy gate");
            check(gate.receive(token, 10123, 1, 101, false), "old active request intact");
        });
        run("wrong thread cannot mutate gate", () -> {
            FaceOperationGate gate = new FaceOperationGate();
            FaceOperationGate.Token token = open(gate);
            AtomicReference<Throwable> failure = new AtomicReference<>();
            Thread worker = new Thread(() -> {
                Runnable[] actions = {
                    () -> gate.phase(),
                    () -> gate.begin(0, 10123, 10, FaceOperationGate.Operation.ENROLL, 0, 101, 200),
                    () -> gate.receive(token, 10123, 1, 101, true),
                    () -> gate.cancel(token),
                    () -> gate.expire(token, 300),
                    () -> gate.acknowledgeClosed(token, 10123),
                    () -> gate.engineDied(token)
                };
                try {
                    for (Runnable action : actions) {
                        boolean threw = false;
                        try { action.run(); } catch (IllegalStateException expected) { threw = true; }
                        check(threw, "wrong-thread operation must throw");
                    }
                } catch (Throwable error) { failure.set(error); }
            });
            worker.start();
            try { worker.join(5000); } catch (InterruptedException error) {
                Thread.currentThread().interrupt(); throw new AssertionError(error);
            }
            check(!worker.isAlive(), "worker terminated");
            check(failure.get() == null, "worker checks: " + failure.get());
            check(gate.receive(token, 10123, 1, 101, false), "failed cross-thread calls had no effect");
        });
        if (failures != 0) throw new AssertionError(failures + "/" + cases + " cases failed");
        System.out.println("FaceOperationGateTest: " + cases + " cases passed");
    }
}
