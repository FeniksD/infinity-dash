package com.android.server.biometrics.sensors.dash;

/** Small pure contracts for optional OEM presentation compatibility. */
public final class OemFingerprintUiCompat {
    private OemFingerprintUiCompat() { }

    public enum Result { SKIPPED, DELIVERED, FAILED }
    public interface PointerCall { void invoke() throws Exception; }
    public interface UiPort {
        boolean enabledForDash();
        boolean ownsTarget(UdfpsTouchBridgeCore.Target target);
        boolean clientStillLive(UdfpsTouchBridgeCore.Target target);
        boolean displayReady(UdfpsTouchBridgeCore.Target target);
        void relay(UdfpsTouchBridgeCore.Target target, int reason) throws Exception;
    }

    public static int normalizeEnrollmentTotal(int total, boolean enabled) {
        return enabled && total <= 0 ? -1 : total;
    }

    /** Handler-confined ownership: an old press can never release a replacement UI session. */
    public static final class OwnedRelay {
        private UdfpsTouchBridgeCore.Target pressedTarget;

        public void forget() { pressedTarget = null; }

        /** Primary exceptions propagate unchanged. Optional UI cannot fail the primary operation. */
        public Result pointerThenRelay(PointerCall pointer, UdfpsTouchBridgeCore.Target target,
                                       boolean down, UiPort ui) throws Exception {
            pointer.invoke();
            try {
                if (down) {
                    if (!ui.enabledForDash() || !ui.ownsTarget(target) || !ui.clientStillLive(target)
                            || !ui.displayReady(target)) return Result.SKIPPED;
                    // Binder can fail after delivery. Retain ownership so matching UP can clean up.
                    pressedTarget = target;
                    ui.relay(target, 8);
                } else {
                    if (pressedTarget != target) return Result.SKIPPED;
                    pressedTarget = null; // A failed or repeated UP must never release a replacement.
                    if (!ui.ownsTarget(target) || !ui.clientStillLive(target)) return Result.SKIPPED;
                    // Matching cleanup must work after opt-out or a display power transition.
                    ui.relay(target, 9);
                }
                return Result.DELIVERED;
            } catch (Throwable optionalFailure) {
                return Result.FAILED;
            }
        }
    }
}
