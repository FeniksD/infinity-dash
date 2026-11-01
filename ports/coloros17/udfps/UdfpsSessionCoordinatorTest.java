package com.android.server.biometrics.sensors.dash;

/** Pure readiness/lifecycle tests; no Android, native input or biometric data access. */
public final class UdfpsSessionCoordinatorTest {
    private static int checks;
    private static final Object OWNER = new Object(), CLIENT = new Object();
    private static UdfpsTouchBridgeCore.Target target(int reason) {
        return new UdfpsTouchBridgeCore.Target(OWNER, CLIENT, 1, 0, 0, reason,
                0, 638, 2060, 110, 1280, 2772);
    }
    private static UdfpsTouchBridgeCore.Motion event(UdfpsTouchBridgeCore.Action action) {
        return new UdfpsTouchBridgeCore.Motion(action, 0, 0, true, 0, 1,
                638, 2060, 12, 20, 0, 100, 100);
    }
    private static void check(boolean value, String description) {
        checks++;
        if (!value) throw new AssertionError(description);
    }
    private static final class Fixture implements UdfpsTouchBridgeCore.Port {
        final UdfpsTouchBridgeCore core = new UdfpsTouchBridgeCore(this);
        final UdfpsSessionCoordinator coordinator = new UdfpsSessionCoordinator(core, this);
        boolean enabled = true, live = true, ready = true;
        boolean failDown, failUp, failRegister, failGate;
        boolean turnOffAfterReadyRead;
        boolean turnOffInRegister;
        int registrations, unregistrations, downs, ups;
        @Override public boolean enabledForDash() {
            if (failGate) throw new IllegalStateException("test gate failure");
            return enabled;
        }
        @Override public boolean clientStillLive(UdfpsTouchBridgeCore.Target target) { return live; }
        @Override public boolean displayReady(UdfpsTouchBridgeCore.Target target) {
            boolean current = ready;
            if (turnOffAfterReadyRead) { turnOffAfterReadyRead = false; ready = false; }
            return current;
        }
        @Override public long uptimeMillis() { return 200; }
        @Override public void register(long generation) throws Exception {
            registrations++;
            if (turnOffInRegister) ready = false;
            if (failRegister) {
                coordinator.registrationFailed();
                throw new Exception("test registration failure");
            }
        }
        @Override public void unregister() {
            unregistrations++;
            coordinator.captureUnregistered();
        }
        @Override public void pointerDown(UdfpsTouchBridgeCore.Target target,
                                          UdfpsTouchBridgeCore.Motion motion) throws Exception {
            downs++;
            if (failDown) {
                coordinator.pointerFailed();
                throw new Exception("test native pointer failure");
            }
        }
        @Override public void pointerUp(UdfpsTouchBridgeCore.Target target,
                                        UdfpsTouchBridgeCore.Motion motion) throws Exception {
            ups++;
            if (failUp) {
                coordinator.pointerFailed();
                throw new Exception("test native release failure");
            }
        }
        void show() { coordinator.show(target(4)); }
        void down() { coordinator.motion(core.generation(), event(UdfpsTouchBridgeCore.Action.DOWN)); }
    }
    private static void offShowThenWake() {
        Fixture f = new Fixture(); f.ready = false; f.show();
        check(f.coordinator.hasPending() && !f.core.armed() && f.registrations == 0,
                "validated off/AOD show remains pending without input capture");
        long old = f.core.generation();
        f.ready = true; f.coordinator.readinessChanged();
        check(f.coordinator.hasPending() && f.core.armed() && f.registrations == 1 && f.downs == 0,
                "same live session arms when ready without pointer or authentication calls");
        f.coordinator.motion(old, event(UdfpsTouchBridgeCore.Action.DOWN));
        f.coordinator.motion(f.core.generation(), event(UdfpsTouchBridgeCore.Action.MOVE));
        check(f.downs == 0, "wake never replays old down or accepts orphan move");
        f.down(); check(f.downs == 1, "first fresh down after wake reaches current session");
    }
    private static void suspendAndResume() {
        Fixture f = new Fixture(); f.show(); f.down(); long old = f.core.generation();
        f.ready = false; f.coordinator.readinessChanged();
        check(f.coordinator.hasPending() && !f.core.armed() && f.ups == 1 && f.unregistrations == 1,
                "power/portrait loss releases and suspends while preserving valid pending session");
        f.coordinator.readinessChanged();
        check(f.ups == 1 && f.registrations == 1, "repeated not-ready events do not recapture or duplicate release");
        f.ready = true; f.coordinator.readinessChanged();
        check(f.core.armed() && f.core.generation() != old && f.registrations == 2 && f.downs == 1,
                "ready transition registers a fresh generation without replaying held finger");
        f.coordinator.motion(old, event(UdfpsTouchBridgeCore.Action.DOWN));
        f.coordinator.motion(f.core.generation(), event(UdfpsTouchBridgeCore.Action.MOVE));
        check(f.downs == 1, "old callback and orphan move cannot reactivate resumed session");
        f.down(); check(f.downs == 2, "fresh down after suspend resumes normal capture");
    }
    private static void clearingAndStatus() {
        Fixture hidden = new Fixture(); hidden.ready = false; hidden.show();
        hidden.coordinator.hide(new Object(), 0);
        check(hidden.coordinator.hasPending(), "unrelated hide cannot clear pending owner");
        hidden.coordinator.hide(OWNER, 0); hidden.ready = true; hidden.coordinator.readinessChanged();
        check(!hidden.coordinator.hasPending() && !hidden.core.armed(), "matching hide clears offscreen pending session");
        Fixture dead = new Fixture(); dead.ready = false; dead.show(); dead.live = false;
        dead.ready = true; dead.coordinator.readinessChanged(); dead.live = true; dead.coordinator.readinessChanged();
        check(!dead.coordinator.hasPending() && !dead.core.armed(), "dead client is discarded and cannot rearm later");
        Fixture optOut = new Fixture(); optOut.show(); optOut.down(); optOut.enabled = false;
        optOut.coordinator.readinessChanged(); optOut.enabled = true; optOut.coordinator.readinessChanged();
        check(!optOut.coordinator.hasPending() && !optOut.core.armed() && optOut.ups == 1,
                "opt-out clears pending and releases; reenable requires a new legitimate show");
        Fixture clear = new Fixture(); clear.ready = false; clear.show(); clear.coordinator.clear();
        clear.ready = true; clear.coordinator.readinessChanged();
        check(!clear.coordinator.hasPending() && !clear.core.armed(),
                "user-switch/shutdown/display-removal clear prevents later rearm");
        for (int reason : new int[] {8, 9, 10}) {
            Fixture status = new Fixture(); status.show(); status.down(); long generation = status.core.generation();
            status.coordinator.show(target(reason));
            check(status.coordinator.hasPending() && status.core.pointerHeld()
                            && status.core.generation() == generation && status.ups == 0,
                    "OEM status does not mutate pending or active session");
        }
        Fixture invalid = new Fixture(); invalid.show(); invalid.down(); invalid.coordinator.show(target(99));
        check(!invalid.coordinator.hasPending() && !invalid.core.armed() && invalid.ups == 1,
                "unknown invalid show still fails closed");
    }
    private static void cancelAndFailures() {
        Fixture cancel = new Fixture(); cancel.show(); cancel.down();
        cancel.coordinator.motion(cancel.core.generation(), event(UdfpsTouchBridgeCore.Action.CANCEL));
        check(cancel.coordinator.hasPending() && cancel.core.armed() && !cancel.core.pointerHeld() && cancel.ups == 1,
                "gesture cancel releases without discarding legitimate visible session");
        cancel.down(); check(cancel.downs == 2, "gesture cancel permits a fresh physical down");
        Fixture stale = new Fixture(); stale.show(); long old = stale.core.generation();
        stale.ready = false; stale.coordinator.readinessChanged(); stale.ready = true; stale.coordinator.readinessChanged();
        stale.coordinator.captureFailure(old);
        check(stale.coordinator.hasPending() && stale.core.armed(), "old input lease failure cannot clear new capture generation");
        stale.coordinator.captureFailure(stale.core.generation());
        stale.coordinator.readinessChanged();
        check(!stale.coordinator.hasPending() && !stale.core.armed(), "current input failure clears pending and prevents auto retry");
        Fixture down = new Fixture(); down.show(); down.failDown = true; down.down();
        down.failDown = false; down.coordinator.readinessChanged();
        check(!down.coordinator.hasPending() && !down.core.armed() && down.downs == 1 && down.ups == 1,
                "native down failure stays closed through readiness events");
        down.show(); down.down();
        check(down.core.armed() && down.downs == 2, "new legitimate show permits retry after native failure");
        Fixture up = new Fixture(); up.show(); up.down(); up.failUp = true;
        up.ready = false; up.coordinator.readinessChanged(); up.failUp = false;
        up.ready = true; up.coordinator.readinessChanged();
        check(!up.coordinator.hasPending() && !up.core.armed() && up.registrations == 1,
                "native up failure during managed suspend clears pending without recursive stop or auto retry");
        Fixture registration = new Fixture(); registration.failRegister = true; registration.show();
        registration.failRegister = false; registration.coordinator.readinessChanged();
        check(!registration.coordinator.hasPending() && !registration.core.armed() && registration.registrations == 1,
                "failed registration cannot create a readiness retry loop");
        Fixture registerRace = new Fixture(); registerRace.failRegister = true; registerRace.turnOffInRegister = true;
        registerRace.show(); registerRace.failRegister = false; registerRace.ready = true;
        registerRace.coordinator.readinessChanged();
        check(!registerRace.coordinator.hasPending() && !registerRace.core.armed() && registerRace.registrations == 1,
                "registration failure is terminal even when display becomes not-ready in the same call");
        Fixture unexpected = new Fixture(); unexpected.show(); unexpected.core.invalidate();
        unexpected.coordinator.readinessChanged();
        check(!unexpected.coordinator.hasPending() && !unexpected.core.armed(),
                "unmanaged core teardown clears pending");
        Fixture gate = new Fixture(); gate.show(); gate.failGate = true; gate.coordinator.readinessChanged();
        check(!gate.coordinator.hasPending() && !gate.core.armed(), "readiness gate exception fails closed");
    }
    private static void readinessRace() {
        Fixture setupRace = new Fixture(); setupRace.turnOffAfterReadyRead = true; setupRace.show();
        check(setupRace.coordinator.hasPending() && !setupRace.core.armed() && setupRace.registrations == 0,
                "readiness loss between coordinator and core show retains authorized pending target");
        setupRace.ready = true; setupRace.coordinator.readinessChanged();
        check(setupRace.core.armed() && setupRace.downs == 0,
                "setup readiness race resumes observation without authentication calls");
        Fixture race = new Fixture(); race.show(); race.turnOffAfterReadyRead = true;
        race.down();
        check(race.coordinator.hasPending() && !race.core.armed() && race.downs == 0,
                "readiness loss between preflight and core dispatch suspends pending instead of discarding it");
        race.ready = true; race.coordinator.readinessChanged(); race.down();
        check(race.core.armed() && race.downs == 1,
                "readiness race still requires a fresh down after resume");
        Fixture malformed = new Fixture(); malformed.show();
        malformed.coordinator.motion(malformed.core.generation(), new UdfpsTouchBridgeCore.Motion(
                UdfpsTouchBridgeCore.Action.DOWN, 0, 0, true, 0, 1,
                Float.NaN, 2060, 12, 20, 0, 100, 100));
        check(!malformed.coordinator.hasPending() && !malformed.core.armed(),
                "unexplained capture stop while still ready remains fail-closed");
        Fixture broadcast = new Fixture(); broadcast.show(); broadcast.down();
        broadcast.coordinator.suspend(); broadcast.coordinator.readinessChanged();
        check(broadcast.coordinator.hasPending() && !broadcast.core.armed() && broadcast.ups == 1,
                "screen-off broadcast wins over stale ready query until screen-on signal");
        broadcast.coordinator.show(target(4));
        check(!broadcast.core.armed(), "new show cannot bypass an observed screen-off state");
        broadcast.coordinator.screenOn();
        check(broadcast.core.armed() && broadcast.downs == 1,
                "screen-on signal resumes observation without replaying touch");
    }
    public static void main(String[] args) {
        offShowThenWake(); suspendAndResume(); clearingAndStatus(); cancelAndFailures();
        readinessRace();
        System.out.println("PASS " + checks + " readiness coordinator checks; no device access");
    }
}
