package com.android.server.biometrics.sensors.dash;

import java.util.ArrayList;
import java.util.List;

/** Pure contract tests: no Android, input, HAL, or biometric data access. */
public final class OemFingerprintUiCompatTest {
    private static int checks;
    private static final UdfpsTouchBridgeCore.Target TARGET = new UdfpsTouchBridgeCore.Target(
            new Object(), new Object(), 1, 0, 0, 2, 0, 638, 2060, 110, 1280, 2772);
    private static void check(boolean value, String description) {
        checks++;
        if (!value) throw new AssertionError(description);
    }
    private static void enrollment() {
        for (int value : new int[] {1, 42, Integer.MAX_VALUE, 0, -1, -7, Integer.MIN_VALUE}) {
            check(OemFingerprintUiCompat.normalizeEnrollmentTotal(value, false) == value,
                    "disabled gate retains original enrollment total");
            check(OemFingerprintUiCompat.normalizeEnrollmentTotal(value, true)
                            == (value > 0 ? value : -1),
                    "enabled gate preserves positive total and exposes genuine callback fallback");
        }
    }
    private static final class Ui implements OemFingerprintUiCompat.UiPort {
        final List<String> calls = new ArrayList<>();
        final OemFingerprintUiCompat.OwnedRelay relay = new OemFingerprintUiCompat.OwnedRelay();
        boolean enabled = true, owned = true, live = true, ready = true;
        boolean failGate, failRelay, linkageRelay;
        @Override public boolean enabledForDash() {
            calls.add("enabled");
            if (failGate) throw new IllegalStateException("test gate failure");
            return enabled;
        }
        @Override public boolean ownsTarget(UdfpsTouchBridgeCore.Target target) {
            calls.add("owned"); return owned;
        }
        @Override public boolean clientStillLive(UdfpsTouchBridgeCore.Target target) {
            calls.add("live"); return live;
        }
        @Override public boolean displayReady(UdfpsTouchBridgeCore.Target target) {
            calls.add("ready"); return ready;
        }
        @Override public void relay(UdfpsTouchBridgeCore.Target target, int reason) throws Exception {
            calls.add("show:" + reason);
            if (failRelay) throw new Exception("test optional relay failure");
            if (linkageRelay) throw new NoClassDefFoundError("test optional linkage failure");
        }
    }
    private static OemFingerprintUiCompat.Result invoke(Ui ui, boolean down) throws Exception {
        return ui.relay.pointerThenRelay(() -> ui.calls.add("primary"), TARGET, down, ui);
    }
    private static void pointer() throws Exception {
        Ui down = new Ui();
        check(invoke(down, true) == OemFingerprintUiCompat.Result.DELIVERED
                        && down.calls.equals(List.of("primary", "enabled", "owned", "live", "ready", "show:8")),
                "successful standard down precedes revalidation and one OEM touch-down notification");
        Ui up = new Ui();
        invoke(up, true); up.calls.clear();
        check(invoke(up, false) == OemFingerprintUiCompat.Result.DELIVERED
                        && up.calls.equals(List.of("primary", "owned", "live", "show:9")),
                "successful standard up precedes one OEM touch-up notification");
        for (int gate = 0; gate < 4; gate++) {
            Ui ui = new Ui();
            switch (gate) {
                case 0 -> ui.enabled = false;
                case 1 -> ui.owned = false;
                case 2 -> ui.live = false;
                case 3 -> ui.ready = false;
            }
            check(invoke(ui, true) == OemFingerprintUiCompat.Result.SKIPPED
                            && ui.calls.get(0).equals("primary")
                            && ui.calls.stream().noneMatch(s -> s.startsWith("show:")),
                    "each failed relay gate skips UI without skipping primary pointer call");
        }
        Ui failedPrimary = new Ui();
        Exception primaryFailure = new Exception("test primary failure");
        try {
            failedPrimary.relay.pointerThenRelay(() -> { throw primaryFailure; }, TARGET, true, failedPrimary);
            throw new AssertionError("primary exception swallowed");
        } catch (Exception caught) {
            check(caught == primaryFailure && failedPrimary.calls.isEmpty(),
                    "original primary exception propagates without UI calls");
        }
        Ui linkedPrimary = new Ui();
        LinkageError primaryLinkage = new NoClassDefFoundError("test primary linkage failure");
        try {
            linkedPrimary.relay.pointerThenRelay(() -> { throw primaryLinkage; }, TARGET, true, linkedPrimary);
            throw new AssertionError("primary linkage error swallowed");
        } catch (LinkageError caught) {
            check(caught == primaryLinkage && linkedPrimary.calls.isEmpty(),
                    "original primary linkage failure propagates without UI calls");
        }
        Ui failedRelay = new Ui(); failedRelay.failRelay = true;
        check(invoke(failedRelay, true) == OemFingerprintUiCompat.Result.FAILED
                        && failedRelay.calls.stream().filter("primary"::equals).count() == 1,
                "optional relay exception never fails or repeats the standard pointer call");
        Ui linkedRelay = new Ui(); invoke(linkedRelay, true); linkedRelay.linkageRelay = true;
        check(invoke(linkedRelay, false) == OemFingerprintUiCompat.Result.FAILED,
                "optional relay linkage error is isolated from primary pointer success");
        Ui failedGate = new Ui(); failedGate.failGate = true;
        check(invoke(failedGate, true) == OemFingerprintUiCompat.Result.FAILED
                        && failedGate.calls.equals(List.of("primary", "enabled")),
                "optional gate exception never fails the successful standard pointer call");
    }
    private static final class Hybrid implements UdfpsTouchBridgeCore.Port, OemFingerprintUiCompat.UiPort {
        final UdfpsTouchBridgeCore core = new UdfpsTouchBridgeCore(this);
        final OemFingerprintUiCompat.OwnedRelay relay = new OemFingerprintUiCompat.OwnedRelay();
        int downs, ups, relays, unregistered;
        boolean failUi, failPrimary;
        OemFingerprintUiCompat.Result result;
        @Override public boolean enabledForDash() { return true; }
        @Override public boolean ownsTarget(UdfpsTouchBridgeCore.Target target) { return core.ownsTarget(target); }
        @Override public boolean clientStillLive(UdfpsTouchBridgeCore.Target target) { return true; }
        @Override public boolean displayReady(UdfpsTouchBridgeCore.Target target) { return true; }
        @Override public long uptimeMillis() { return 200; }
        @Override public void register(long generation) { }
        @Override public void unregister() { unregistered++; relay.forget(); }
        @Override public void pointerDown(UdfpsTouchBridgeCore.Target target,
                                          UdfpsTouchBridgeCore.Motion motion) throws Exception {
            result = relay.pointerThenRelay(() -> {
                downs++;
                if (failPrimary) throw new Exception("primary failure");
            }, target, true, this);
        }
        @Override public void pointerUp(UdfpsTouchBridgeCore.Target target,
                                        UdfpsTouchBridgeCore.Motion motion) throws Exception {
            result = relay.pointerThenRelay(() -> ups++, target, false, this);
        }
        @Override public void relay(UdfpsTouchBridgeCore.Target target, int reason) throws Exception {
            relays++;
            if (failUi) throw new Exception("optional failure");
            core.show(new UdfpsTouchBridgeCore.Target(target.overlayOwner, target.client,
                    target.requestId, target.sensorId, target.userId, reason, target.displayId,
                    target.centerX, target.centerY, target.radius, target.width, target.height));
        }
    }
    private static UdfpsTouchBridgeCore.Motion event(UdfpsTouchBridgeCore.Action action) {
        return new UdfpsTouchBridgeCore.Motion(action, 0, 0, true, 0, 1,
                638, 2060, 12, 20, 0, 100, 100);
    }
    private static void integration() {
        Hybrid h = new Hybrid();
        check(!h.core.ownsTarget(TARGET) && !h.core.ownsTarget(null), "inactive core owns no relay target");
        long generation = h.core.show(TARGET);
        UdfpsTouchBridgeCore.Target equalButDifferent = new UdfpsTouchBridgeCore.Target(TARGET.overlayOwner,
                TARGET.client, 1, 0, 0, 2, 0, 638, 2060, 110, 1280, 2772);
        check(h.core.ownsTarget(TARGET) && !h.core.ownsTarget(equalButDifferent),
                "relay ownership requires the exact active target object");
        h.core.motion(generation, event(UdfpsTouchBridgeCore.Action.DOWN));
        check(h.downs == 1 && h.relays == 1 && h.core.pointerHeld() && h.core.generation() == generation
                        && h.result == OemFingerprintUiCompat.Result.DELIVERED,
                "relayed status cannot recurse into another pointer call or disarm held session");
        h.core.motion(generation, event(UdfpsTouchBridgeCore.Action.UP));
        check(h.ups == 1 && h.relays == 2 && h.core.armed() && !h.core.pointerHeld()
                        && h.core.generation() == generation,
                "relayed up status preserves the active session for another physical press");
        h.failUi = true;
        h.core.motion(generation, event(UdfpsTouchBridgeCore.Action.DOWN));
        check(h.downs == 2 && h.core.pointerHeld() && h.core.armed()
                        && h.result == OemFingerprintUiCompat.Result.FAILED,
                "optional UI failure cannot trigger core release or unregister");
        h.core.hide(TARGET.overlayOwner, 0);
        check(h.ups == 2 && h.unregistered == 1 && !h.core.ownsTarget(TARGET),
                "actual hide still releases and invalidates after optional UI failure");
        Hybrid failing = new Hybrid(); failing.failPrimary = true;
        long failedGeneration = failing.core.show(TARGET);
        failing.core.motion(failedGeneration, event(UdfpsTouchBridgeCore.Action.DOWN));
        check(failing.downs == 1 && failing.ups == 1 && failing.unregistered == 1 && !failing.core.armed(),
                "standard pointer failure retains original fail-closed release and cleanup");
    }
    private static void ownership() throws Exception {
        Ui cleanup = new Ui(); invoke(cleanup, true); cleanup.calls.clear();
        cleanup.enabled = false; cleanup.ready = false;
        check(invoke(cleanup, false) == OemFingerprintUiCompat.Result.DELIVERED
                        && cleanup.calls.equals(List.of("primary", "owned", "live", "show:9")),
                "matching owned UI up cleans up after opt-out and screen transition");
        cleanup.calls.clear();
        check(invoke(cleanup, false) == OemFingerprintUiCompat.Result.SKIPPED
                        && cleanup.calls.equals(List.of("primary")),
                "matching UI up cannot be sent twice");
        Ui orphan = new Ui();
        check(invoke(orphan, false) == OemFingerprintUiCompat.Result.SKIPPED
                        && orphan.calls.equals(List.of("primary")),
                "no UI up is invented without an owned UI down");
        Ui wrong = new Ui(); invoke(wrong, true); wrong.calls.clear();
        UdfpsTouchBridgeCore.Target other = new UdfpsTouchBridgeCore.Target(new Object(), new Object(),
                2, 0, 0, 2, 0, 638, 2060, 110, 1280, 2772);
        check(wrong.relay.pointerThenRelay(() -> wrong.calls.add("primary"), other, false, wrong)
                        == OemFingerprintUiCompat.Result.SKIPPED
                        && wrong.calls.equals(List.of("primary")),
                "another target cannot release the owned UI press");
        check(invoke(wrong, false) == OemFingerprintUiCompat.Result.DELIVERED,
                "mismatched callback leaves legitimate owner able to release");
        Ui stale = new Ui(); invoke(stale, true); stale.owned = false;
        check(invoke(stale, false) == OemFingerprintUiCompat.Result.SKIPPED,
                "stale owner never changes replacement UI");
        stale.owned = true;
        check(invoke(stale, false) == OemFingerprintUiCompat.Result.SKIPPED,
                "stale release clears ownership rather than replaying into a later session");
        Ui finished = new Ui(); invoke(finished, true); finished.live = false;
        check(invoke(finished, false) == OemFingerprintUiCompat.Result.SKIPPED,
                "finished client cannot receive an OEM UI notification");
        Ui uncertain = new Ui(); uncertain.failRelay = true;
        check(invoke(uncertain, true) == OemFingerprintUiCompat.Result.FAILED,
                "uncertain down delivery is reported as optional failure");
        uncertain.failRelay = false;
        check(invoke(uncertain, false) == OemFingerprintUiCompat.Result.DELIVERED,
                "uncertain Binder down delivery still allows matching cleanup");
        Ui forgotten = new Ui(); invoke(forgotten, true); forgotten.relay.forget();
        check(invoke(forgotten, false) == OemFingerprintUiCompat.Result.SKIPPED,
                "unregister forgets residual UI ownership");
        Ui skipped = new Ui(); skipped.enabled = false; invoke(skipped, true); skipped.enabled = true;
        check(invoke(skipped, false) == OemFingerprintUiCompat.Result.SKIPPED,
                "a skipped UI down never acquires ownership");
    }
    public static void main(String[] args) throws Exception {
        if (args.length == 0 || "enrollment".equals(args[0])) enrollment();
        if (args.length == 0 || "pointer".equals(args[0])) pointer();
        if (args.length == 0 || "integration".equals(args[0])) integration();
        if (args.length == 0 || "ownership".equals(args[0])) ownership();
        System.out.println("PASS " + checks + " OEM UI compatibility checks; no device access");
    }
}
