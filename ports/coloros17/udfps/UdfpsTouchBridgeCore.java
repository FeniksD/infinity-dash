package com.android.server.biometrics.sensors.dash;

import java.util.Objects;

/** Offline spike: single-finger, portrait-only state machine. Not installed on the phone. */
public final class UdfpsTouchBridgeCore {
    public enum Action { DOWN, MOVE, UP, POINTER_DOWN, POINTER_UP, CANCEL }

    public static final class Target {
        final Object overlayOwner, client;
        final long requestId;
        final int sensorId, userId, reason, displayId, width, height;
        final float centerX, centerY, radius;
        public Target(Object owner, Object client, long request, int sensor, int user, int reason,
                      int display, float x, float y, float radius, int width, int height) {
            overlayOwner = owner; this.client = client; requestId = request; sensorId = sensor;
            userId = user; this.reason = reason; displayId = display; centerX = x; centerY = y;
            this.radius = radius; this.width = width; this.height = height;
        }
        public Object client() { return client; }
        public long requestId() { return requestId; }
        public int sensorId() { return sensorId; }
        @Override public boolean equals(Object object) {
            if (!(object instanceof Target)) return false;
            Target other = (Target) object;
            return overlayOwner == other.overlayOwner && client == other.client
                    && requestId == other.requestId && sensorId == other.sensorId
                    && userId == other.userId && reason == other.reason && displayId == other.displayId
                    && centerX == other.centerX && centerY == other.centerY && radius == other.radius
                    && width == other.width && height == other.height;
        }
        @Override public int hashCode() { return System.identityHashCode(client); }
        boolean valid() {
            return overlayOwner != null && client != null && requestId > 0 && sensorId >= 0 && userId >= 0
                    && displayId == 0 && reason >= 1 && reason <= 4
                    && Float.isFinite(centerX) && Float.isFinite(centerY)
                    && Float.isFinite(radius) && radius > 0 && width > 0 && height > 0
                    && centerX - radius >= 0 && centerY - radius >= 0
                    && centerX + radius <= width && centerY + radius <= height;
        }
        boolean contains(Motion motion) {
            double dx = motion.x - centerX, dy = motion.y - centerY;
            return dx * dx + dy * dy <= (double) radius * radius;
        }
    }

    /** Coordinates/times come from MotionEvent, not from raw getevent or a timer. */
    public static final class Motion {
        final Action action;
        final int displayId, rotation, pointerId, pointerCount;
        final boolean touchscreenFinger;
        final float x, y, minor, major, orientation;
        final long eventTime, downTime;
        public Motion(Action action, int display, int rotation, boolean finger, int pointer,
                      int count, float x, float y, float minor, float major, float orientation,
                      long time, long downTime) {
            this.action = action; displayId = display; this.rotation = rotation;
            touchscreenFinger = finger; pointerId = pointer; pointerCount = count;
            this.x = x; this.y = y; this.minor = minor; this.major = major;
            this.orientation = orientation; eventTime = time; this.downTime = downTime;
        }
        public int pointerId() { return pointerId; }
        public float x() { return x; }
        public float y() { return y; }
        public float minor() { return minor; }
        public float major() { return major; }
        public float orientation() { return orientation; }
        public long eventTime() { return eventTime; }
        public long downTime() { return downTime; }
    }

    public interface Port {
        boolean enabledForDash();
        boolean clientStillLive(Target target);
        boolean displayReady(Target target);
        long uptimeMillis();
        void register(long generation) throws Exception;
        void unregister() throws Exception;
        // Android port uses IFingerprintService, whose provider rechecks requestId on dispatch.
        void pointerDown(Target target, Motion motion) throws Exception;
        void pointerUp(Target target, Motion motion) throws Exception;
    }

    private final Port port;
    private Target target;
    private Motion held;
    private Motion observedDown;
    private long generation;
    private boolean registered;
    private boolean blockedGesture;

    public UdfpsTouchBridgeCore(Port port) { this.port = Objects.requireNonNull(port); }

    /** Run every method on the fingerprint handler. Returns a token for listener callbacks. */
    public long show(Target next) {
        if (registered && target != null && target.equals(next) && port.enabledForDash()
                && port.clientStillLive(next) && port.displayReady(next)) return generation;
        stop();
        if (next == null || !next.valid() || !port.enabledForDash()
                || !port.clientStillLive(next) || !port.displayReady(next)) return generation;
        target = next;
        try {
            // Mark before calling register: a partly-failed registration must still be removed.
            registered = true;
            port.register(generation);
        } catch (Exception | LinkageError e) {
            stop();
        }
        return generation;
    }

    public void hide(Object owner, int sensorId) {
        if (target != null && target.overlayOwner == owner && target.sensorId == sensorId) stop();
    }

    /** Cancellation, screen off, user switch, display rotation, or opt-out. */
    public void invalidate() { stop(); }
    public void invalidate(long token) { if (token == generation) stop(); }

    public void motion(long token, Motion motion) {
        if (target == null || !registered || token != generation || motion == null) return;
        // A gesture cancellation is not the end of an authorized visible overlay session.
        if (motion.action == Action.CANCEL) {
            if (!port.enabledForDash() || !port.clientStillLive(target) || !port.displayReady(target)) {
                stop();
            } else {
                release(null);
                observedDown = null;
                blockedGesture = false;
            }
            return;
        }
        if (!port.enabledForDash() || !port.clientStillLive(target) || !port.displayReady(target)) {
            stop(); return;
        }
        if (motion.displayId != target.displayId) return;
        if (motion.rotation != 0) { stop(); return; }
        if (!motion.touchscreenFinger) return;
        if (motion.pointerCount != 1 || motion.action == Action.POINTER_DOWN
                || motion.action == Action.POINTER_UP) {
            release(motion);
            observedDown = null;
            blockedGesture = true;
            return;
        }
        if (!Float.isFinite(motion.x) || !Float.isFinite(motion.y)) { stop(); return; }

        switch (motion.action) {
            case DOWN -> {
                release(motion);
                if (target == null) return;
                observedDown = motion;
                blockedGesture = false;
                if (target.contains(motion)) press(motion);
            }
            case MOVE -> {
                if (observedDown == null || blockedGesture) return;
                if (motion.pointerId != observedDown.pointerId || motion.downTime != observedDown.downTime) {
                    release(motion); observedDown = null; blockedGesture = true; return;
                }
                if (held == null) {
                    if (target.contains(motion)) press(motion);
                } else if (!target.contains(motion)) {
                    release(motion);
                    observedDown = null;
                    blockedGesture = true; // Do not reenter until the next genuine DOWN.
                } else held = motion;
            }
            case UP -> {
                release(motion);
                observedDown = null;
                blockedGesture = false;
            }
            default -> { }
        }
    }

    private void press(Motion motion) {
        held = motion; // Retain before Binder call, so failure can attempt release.
        try { port.pointerDown(target, motion); }
        catch (Exception | LinkageError e) { stop(); }
    }

    private void release(Motion latest) {
        if (held == null || target == null) return;
        Target previous = target;
        long time = latest == null ? port.uptimeMillis() : latest.eventTime;
        boolean samePointer = latest != null && latest.pointerId == held.pointerId;
        Motion up = new Motion(Action.UP, held.displayId, held.rotation, held.touchscreenFinger,
                held.pointerId, 1, samePointer ? latest.x : held.x,
                samePointer ? latest.y : held.y, held.minor, held.major, held.orientation,
                time, held.downTime);
        held = null; // Never duplicate an UP even when Binder fails.
        try { port.pointerUp(previous, up); }
        catch (Exception | LinkageError e) {
            // Fail closed: release was attempted with the original request; never target a new one.
            clearRegistration();
        }
    }

    private void stop() {
        release(null); // Intentionally not gated: opt-out while pressed must still release.
        clearRegistration();
    }

    private void clearRegistration() {
        generation++;
        target = null;
        held = null;
        observedDown = null;
        blockedGesture = false;
        if (registered) {
            registered = false;
            try { port.unregister(); } catch (Exception | LinkageError ignored) { }
        }
    }

    public boolean armed() { return registered && target != null; }
    public boolean pointerHeld() { return held != null; }
    public long generation() { return generation; }
    /** Bounded diagnostic caller may report decisions; never includes coordinates or identifiers. */
    public String diagnosticState(long token, Motion motion) {
        return "armed=" + armed() + " sameGeneration=" + (token == generation)
                + " held=" + pointerHeld() + " downObserved=" + (observedDown != null)
                + " gestureBlocked=" + blockedGesture
                + " sameDisplay=" + (target != null && target.displayId == motion.displayId)
                + " inside=" + (target != null && target.contains(motion))
                + " enabled=" + port.enabledForDash()
                + " clientLive=" + (target != null && port.clientStillLive(target))
                + " screenReady=" + (target != null && port.displayReady(target));
    }
}
