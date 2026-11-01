package com.android.server.biometrics.sensors.dash;

import java.util.ArrayList;
import java.util.List;

/** No phone access. Exercises privacy/lifecycle and request ownership, not biometric results. */
public final class UdfpsTouchBridgeCoreTest {
    private static int checks;
    private static final Object OWNER = new Object(), CLIENT = new Object();
    private static UdfpsTouchBridgeCore.Target target(long request) {
        return new UdfpsTouchBridgeCore.Target(OWNER, CLIENT, request, 0, 0, 2, 0,
                638, 2060, 110, 1280, 2772);
    }
    private static UdfpsTouchBridgeCore.Motion event(UdfpsTouchBridgeCore.Action action,
                                                     float x, float y, long time) {
        return new UdfpsTouchBridgeCore.Motion(action, 0, 0, true, 4, 1,
                x, y, 12, 20, .25f, time, 100);
    }
    private static final class FakePort implements UdfpsTouchBridgeCore.Port {
        boolean enabled = true, live = true, screen = true, registered;
        boolean throwRegister, throwDown, throwUp;
        int registerCount, unregisterCount;
        final List<String> calls = new ArrayList<>();
        final List<UdfpsTouchBridgeCore.Motion> motions = new ArrayList<>();
        @Override public boolean enabledForDash() { return enabled; }
        @Override public boolean clientStillLive(UdfpsTouchBridgeCore.Target target) { return live; }
        @Override public boolean displayReady(UdfpsTouchBridgeCore.Target target) { return screen; }
        @Override public long uptimeMillis() { return 900; }
        @Override public void register(long generation) throws Exception {
            registerCount++; registered = true;
            if (throwRegister) throw new Exception("registration failed");
        }
        @Override public void unregister() { unregisterCount++; registered = false; }
        @Override public void pointerDown(UdfpsTouchBridgeCore.Target t,
                                          UdfpsTouchBridgeCore.Motion m) throws Exception {
            calls.add("down:" + t.requestId()); motions.add(m);
            if (throwDown) throw new Exception("Binder failed after possible submission");
        }
        @Override public void pointerUp(UdfpsTouchBridgeCore.Target t,
                                        UdfpsTouchBridgeCore.Motion m) throws Exception {
            calls.add("up:" + t.requestId()); motions.add(m);
            if (throwUp) throw new Exception("Binder failed");
        }
    }
    private static void check(boolean condition, String description) {
        checks++;
        if (!condition) throw new AssertionError(description);
    }
    private static void testGateAndInvalidTarget() {
        FakePort p = new FakePort(); p.enabled = false;
        UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        b.show(target(1)); check(!b.armed() && p.registerCount == 0, "off never registers");
        p.enabled = true; p.live = false;
        b.show(target(1)); check(!b.armed(), "finished client never registers");
        p.live = true;
        b.show(new UdfpsTouchBridgeCore.Target(OWNER, CLIENT, 1, 0, 0, 99, 0,
                638, 2060, 110, 1280, 2772));
        check(!b.armed(), "unsupported reason fails closed");
        b.show(new UdfpsTouchBridgeCore.Target(OWNER, CLIENT, 1, 0, 0, 2, 0,
                638, Float.NaN, 110, 1280, 2772));
        check(!b.armed(), "invalid geometry fails closed");
        b.show(new UdfpsTouchBridgeCore.Target(OWNER, CLIENT, 1, 0, -1, 2, 0,
                638, 2060, 110, 1280, 2772));
        check(!b.armed(), "invalid user cannot arm a biometric touch bridge");
    }
    private static void testRealDownUpAndDwell() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        check(b.show(target(7)) == g && p.registerCount == 1 && p.calls.size() == 1,
                "repeated identical show preserves active gesture and single listener");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.MOVE, 640, 2062, 2100));
        check(p.calls.equals(List.of("down:7")), "move/long dwell never synthesizes extra downs");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.UP, 640, 2062, 2500));
        check(p.calls.equals(List.of("down:7", "up:7")), "balanced physical gesture");
        check(p.motions.get(1).eventTime() == 2500 && p.motions.get(1).downTime() == 100,
                "actual event time and gesture time retained");
        check(b.armed() && !b.pointerHeld(), "another gesture can use same active overlay");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 2600));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.DOWN,
                0, 0, true, 9, 1, 640, 2060, 10, 20, 0, 2700, 2700));
        check(p.motions.get(3).pointerId() == 4 && p.motions.get(3).downTime() == 100,
                "new DOWN after lost UP releases original pointer and gesture");
    }
    private static void testObservedDownMayEnterButNoReentry() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 10, 10, 100));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 200));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.UP, 638, 2060, 300));
        check(p.calls.equals(List.of("down:7", "up:7")),
                "observed single-pointer DOWN may enter sensor on MOVE");
        check(p.motions.get(0).eventTime() == 200 && p.motions.get(0).downTime() == 100,
                "entry uses actual MOVE time with original gesture downTime");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 400));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.MOVE, 800, 2060, 500));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 600));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.UP, 638, 2060, 700));
        check(p.calls.equals(List.of("down:7", "up:7", "down:7", "up:7")),
                "leaving circle releases, no reentry before a fresh DOWN");
    }
    private static void testPendingGestureIdentityAndInvalidation() {
        for (int kind = 0; kind < 6; kind++) {
            FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
            long g = b.show(target(7));
            if (kind != 0) b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 10, 10, 100));
            if (kind == 1) b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.MOVE,
                    0, 0, true, 8, 1, 638, 2060, 12, 20, 0, 150, 100));
            if (kind == 2) b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.MOVE,
                    0, 0, true, 4, 1, 638, 2060, 12, 20, 0, 150, 101));
            if (kind == 3) b.motion(g, event(UdfpsTouchBridgeCore.Action.UP, 10, 10, 150));
            if (kind == 4) b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.CANCEL,
                    -1, -1, false, -1, 0, Float.NaN, Float.NaN, 0, 0, 0, 150, 100));
            if (kind == 5) b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.POINTER_DOWN,
                    0, 0, true, 4, 2, 10, 10, 12, 20, 0, 150, 100));
            b.motion(g, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 200));
            check(p.calls.isEmpty(), "orphan/mismatched/ended/cancelled/multitouch MOVE cannot enter");
            b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 300));
            check(p.calls.equals(List.of("down:7")), "fresh DOWN restores eligibility after invalid gesture");
        }
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long old = b.show(target(7)); b.motion(old, event(UdfpsTouchBridgeCore.Action.DOWN, 10, 10, 100));
        long next = b.show(target(8));
        b.motion(old, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 200));
        b.motion(next, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 200));
        check(p.calls.isEmpty(), "pending DOWN cannot cross session generation");
    }
    private static void testHideOptOutAndOwnership() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7)); b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        b.hide(new Object(), 0); check(b.pointerHeld(), "other overlay cannot cancel owner");
        p.enabled = false; b.hide(OWNER, 0);
        check(p.calls.equals(List.of("down:7", "up:7")), "hide releases even after opt-out");
        check(!b.armed() && p.unregisterCount == 1, "hide unregisters listener");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 300));
        check(p.calls.size() == 2, "late callback cannot activate hidden overlay");
    }
    private static void testReplacementAndStaleQueue() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long old = b.show(target(7)); b.motion(old, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        long fresh = b.show(target(8));
        b.motion(old, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 200));
        check(p.calls.equals(List.of("down:7", "up:7")), "replacement releases original request only");
        b.motion(fresh, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 300));
        check(p.calls.get(2).equals("down:8"), "fresh owner has fresh request");
        b.motion(old, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.CANCEL,
                -1, -1, false, -1, 0, Float.NaN, Float.NaN, 0, 0, 0, 350, 100));
        check(b.armed() && b.pointerHeld() && p.calls.size() == 3,
                "stale synthetic cancellation cannot release a replacement request");
        p.live = false; b.motion(fresh, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 400));
        check(!b.armed() && p.calls.get(3).equals("up:8"), "stale lifecycle disarms, releases same id");
    }
    private static void testRotateStillStopsSession() {
        for (int test = 0; test < 1; test++) {
            FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
            long g = b.show(target(7)); b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
            UdfpsTouchBridgeCore.Motion e = new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.MOVE,
                    0, 1, true, 4, 1, 638, 2060, 12, 20, 0, 200, 100);
            b.motion(g, e);
            check(!b.armed() && p.calls.equals(List.of("down:7", "up:7")),
                    "rotation releases and unregisters");
        }
    }
    private static void testSourceFilterAndFailures() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.DOWN,
                1, 0, true, 4, 1, 638, 2060, 12, 20, 0, 100, 100));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.DOWN,
                0, 0, false, 4, 1, 638, 2060, 12, 20, 0, 100, 100));
        check(p.calls.isEmpty(), "other display/mouse/stylus filtered");
        p.throwDown = true;
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        check(!b.armed() && p.calls.equals(List.of("down:7", "up:7")),
                "possibly submitted failed down attempts balancing up and fails closed");
        FakePort q = new FakePort(); q.throwRegister = true;
        UdfpsTouchBridgeCore c = new UdfpsTouchBridgeCore(q); c.show(target(9));
        check(!c.armed() && q.unregisterCount == 1, "partial registration removed");
        q.throwRegister = false; q.throwUp = true;
        long h = c.show(target(9)); c.motion(h, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        c.hide(OWNER, 0);
        check(!c.armed() && !q.registered && q.calls.equals(List.of("down:9", "up:9")),
                "failed up does not leak listener or duplicate release");
        FakePort release = new FakePort(); UdfpsTouchBridgeCore failed = new UdfpsTouchBridgeCore(release);
        long token = failed.show(target(10));
        failed.motion(token, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        release.throwUp = true;
        failed.motion(token, event(UdfpsTouchBridgeCore.Action.DOWN, 10, 10, 200));
        failed.motion(token, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 300));
        check(!failed.armed() && release.calls.equals(List.of("down:10", "up:10")),
                "release failure clears target and cannot rearm pending entry");
    }
    private static void testSyntheticCancelWithoutFingerMetadata() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.CANCEL,
                -1, -1, false, -1, 0, Float.NaN, Float.NaN, 0, 0, 0, 200, 100));
        check(b.armed() && !b.pointerHeld() && p.calls.equals(List.of("down:7", "up:7")),
                "synthetic CANCEL releases without source, pointer count, geometry, or display metadata");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 300));
        check(p.calls.equals(List.of("down:7", "up:7", "down:7")),
                "fresh press works after gesture cancellation in same enrollment");
    }
    private static void testUnrelatedMultitouchCannotDestroyOverlay() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 97, 1673, 100));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.POINTER_DOWN,
                0, 0, true, 4, 2, 97, 1673, 12, 20, 0, 200, 100));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.POINTER_UP,
                0, 0, true, 4, 2, 97, 1673, 12, 20, 0, 300, 100));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.UP, 97, 1673, 400));
        check(b.armed() && p.calls.isEmpty(), "irrelevant multitouch leaves active overlay registered");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 500));
        check(p.calls.equals(List.of("down:7")), "sensor press works after irrelevant grip gesture");
    }
    private static void testHeldMultitouchReleasesOnlyGesture() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.POINTER_DOWN,
                0, 0, true, 4, 2, 638, 2060, 12, 20, 0, 200, 100));
        b.motion(g, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.POINTER_UP,
                0, 0, true, 4, 2, 638, 2060, 12, 20, 0, 300, 100));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.UP, 638, 2060, 400));
        check(b.armed() && !b.pointerHeld() && p.calls.equals(List.of("down:7", "up:7")),
                "second finger releases exactly once without destroying enrollment scope");
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 500));
        check(p.calls.equals(List.of("down:7", "up:7", "down:7")), "fresh gesture works after multitouch");
    }
    private static void testNoninteractiveDisplayCannotCapture() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        p.screen = false; b.show(target(7));
        check(!b.armed() && p.registerCount == 0, "offscreen or noninteractive show never arms");
        p.screen = true;
        long g = b.show(target(7));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        p.screen = false;
        b.motion(g, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 200));
        check(!b.armed() && p.calls.equals(List.of("down:7", "up:7")),
                "turning display off while pressed releases and unregisters");
    }
    private static void testRealSessionInvalidationStillStops() {
        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7));
        b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        b.invalidate(g - 1);
        check(b.armed() && b.pointerHeld(), "stale lifecycle event cannot invalidate current session");
        b.invalidate(g);
        check(!b.armed() && p.calls.equals(List.of("down:7", "up:7")),
                "matching session invalidation releases and unregisters");
        long fresh = b.show(target(8));
        b.motion(fresh, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 300));
        p.enabled = false;
        b.motion(fresh, new UdfpsTouchBridgeCore.Motion(UdfpsTouchBridgeCore.Action.CANCEL,
                -1, -1, false, -1, 0, Float.NaN, Float.NaN, 0, 0, 0, 400, 300));
        check(!b.armed() && p.calls.equals(List.of("down:7", "up:7", "down:8", "up:8")),
                "gesture cancel cannot preserve a session after opt-out");
    }
    private static UdfpsTouchBridgeCore.Target statusTarget(int reason) {
        return new UdfpsTouchBridgeCore.Target(new Object(), CLIENT, 7, 0, 0, reason, 0,
                638, 2060, 110, 1280, 2772);
    }
    private static void testOemStatusNotificationsPreserveSession() {
        for (int reason : new int[] {8, 9, 10}) {
            FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
            long generation = b.show(target(7));
            b.motion(generation, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
            long after = b.show(statusTarget(reason));
            check(after == generation && b.armed() && b.pointerHeld()
                            && p.calls.equals(List.of("down:7")) && p.registerCount == 1 && p.unregisterCount == 0,
                    "OEM touch/failure status cannot replace or tear down active held session");
            b.motion(generation, event(UdfpsTouchBridgeCore.Action.UP, 638, 2060, 200));
            b.motion(generation, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 300));
            check(p.calls.equals(List.of("down:7", "up:7", "down:7")),
                    "another physical press works after OEM failure notification");

            FakePort pendingPort = new FakePort(); UdfpsTouchBridgeCore pending = new UdfpsTouchBridgeCore(pendingPort);
            long pendingGeneration = pending.show(target(7));
            pending.motion(pendingGeneration, event(UdfpsTouchBridgeCore.Action.DOWN, 10, 10, 100));
            pending.show(statusTarget(reason));
            pending.motion(pendingGeneration, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 200));
            check(pendingPort.calls.equals(List.of("down:7")) && pending.armed(),
                    "OEM notification preserves pending same-pointer sensor entry");
        }
        FakePort emptyPort = new FakePort(); UdfpsTouchBridgeCore empty = new UdfpsTouchBridgeCore(emptyPort);
        empty.show(statusTarget(10));
        check(!empty.armed() && emptyPort.registerCount == 0, "status notification cannot create a session");

        FakePort p = new FakePort(); UdfpsTouchBridgeCore b = new UdfpsTouchBridgeCore(p);
        long g = b.show(target(7)); b.motion(g, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 100));
        b.show(statusTarget(10)); b.hide(OWNER, 0);
        check(!b.armed() && p.calls.equals(List.of("down:7", "up:7")), "real owner hide still cleans up after status");
        long fresh = b.show(target(8)); b.motion(fresh, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 300));
        b.show(statusTarget(10)); p.enabled = false;
        b.motion(fresh, event(UdfpsTouchBridgeCore.Action.MOVE, 638, 2060, 400));
        check(!b.armed() && p.calls.get(p.calls.size()-1).equals("up:8"), "opt-out still releases after status");
        p.enabled = true;
        long last = b.show(target(9)); b.motion(last, event(UdfpsTouchBridgeCore.Action.DOWN, 638, 2060, 500));
        b.show(statusTarget(99));
        check(!b.armed() && p.calls.get(p.calls.size()-1).equals("up:9"),
                "unknown invalid request still fails closed; only documented statuses are ignored");
    }
    public static void main(String[] args) {
        testOemStatusNotificationsPreserveSession();
        testRealSessionInvalidationStillStops();
        testUnrelatedMultitouchCannotDestroyOverlay(); testHeldMultitouchReleasesOnlyGesture();
        testNoninteractiveDisplayCannotCapture();
        testSyntheticCancelWithoutFingerMetadata();
        testGateAndInvalidTarget(); testRealDownUpAndDwell(); testObservedDownMayEnterButNoReentry();
        testPendingGestureIdentityAndInvalidation();
        testHideOptOutAndOwnership(); testReplacementAndStaleQueue();
        testRotateStillStopsSession(); testSourceFilterAndFailures();
        System.out.println("PASS " + checks + " lifecycle and input checks; no device access");
    }
}
