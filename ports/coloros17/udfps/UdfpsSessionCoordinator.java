package com.android.server.biometrics.sensors.dash;

/** Handler-confined authorized overlay intent, independent of active touch capture resources. */
public final class UdfpsSessionCoordinator {
    private final UdfpsTouchBridgeCore core;
    private final UdfpsTouchBridgeCore.Port port;
    private UdfpsTouchBridgeCore.Target pending;
    private int managedDepth;
    private boolean screenOff;

    public UdfpsSessionCoordinator(UdfpsTouchBridgeCore core, UdfpsTouchBridgeCore.Port port) {
        this.core = core; this.port = port;
    }

    public void show(UdfpsTouchBridgeCore.Target next) {
        if (next != null && UdfpsTouchBridgeCore.isOemStatusReason(next.reason)) return;
        try {
            if (next == null || !next.valid() || !port.enabledForDash() || !port.clientStillLive(next)) {
                clear(); return;
            }
            if (pending == null || !pending.equals(next)) {
                pending = next;
                managed(core::invalidate);
            }
            readinessChanged();
        } catch (RuntimeException | LinkageError failure) { clear(); }
    }

    public void readinessChanged() {
        UdfpsTouchBridgeCore.Target selected = pending;
        if (selected == null) return;
        try {
            if (!port.enabledForDash() || !port.clientStillLive(selected)) { clear(); return; }
            if (screenOff || !port.displayReady(selected)) {
                if (core.armed()) managed(core::invalidate);
                return;
            }
            if (!core.ownsTarget(selected)) {
                managed(() -> core.show(selected));
                // Setup failure explicitly clears pending. A power transition between these
                // two readiness checks may retain the same live authorization for a later wake.
                if (pending == selected && !core.ownsTarget(selected)
                        && (!port.enabledForDash() || !port.clientStillLive(selected)
                            || port.displayReady(selected))) pending = null;
            }
        } catch (RuntimeException | LinkageError failure) { clear(); }
    }

    public void hide(Object owner, int sensorId) {
        if (pending != null && pending.overlayOwner == owner && pending.sensorId == sensorId) clear();
    }

    /** Screen-off broadcast is authoritative even if a display query is briefly stale. */
    public void suspend() {
        screenOff = true;
        if (pending == null) return;
        try {
            if (!port.enabledForDash() || !port.clientStillLive(pending)) { clear(); return; }
            if (core.armed()) managed(core::invalidate);
        } catch (RuntimeException | LinkageError failure) { clear(); }
    }

    public void screenOn() { screenOff = false; readinessChanged(); }

    public void clear() {
        pending = null;
        managed(core::invalidate);
    }

    /** Primary pointer failure is reported before the original core exception cleanup. */
    public void pointerFailed() { pending = null; }
    public void registrationFailed() { pending = null; }

    /** Unplanned capture teardown is terminal; only our suspend/new-show transitions may retain it. */
    public void captureUnregistered() { if (managedDepth == 0) pending = null; }

    public void captureFailure(long generation) {
        if (generation == core.generation()) clear();
    }

    public void motion(long generation, UdfpsTouchBridgeCore.Motion motion) {
        if (generation != core.generation()) return;
        readinessChanged();
        if (generation != core.generation()) return;
        try {
            managed(() -> core.motion(generation, motion));
            if (pending != null && !core.armed()) {
                // Readiness can change between preflight and Core's dispatch check.
                // Native pointer failures explicitly clear pending before reaching here.
                if (!port.enabledForDash() || !port.clientStillLive(pending)
                        || port.displayReady(pending)) pending = null;
            }
        } catch (RuntimeException | LinkageError failure) { clear(); }
    }

    private void managed(Runnable operation) {
        managedDepth++;
        try { operation.run(); }
        finally { managedDepth--; }
    }

    public boolean hasPending() { return pending != null; }
}
