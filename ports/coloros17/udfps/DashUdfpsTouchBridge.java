package com.android.server.biometrics.sensors.dash;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.display.DisplayManager;
import android.hardware.input.InputManagerGlobal;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;
import android.view.Display;
import android.view.InputDevice;
import android.view.InputChannel;
import android.view.InputEvent;
import android.view.InputEventReceiver;
import android.view.InputMonitor;
import android.view.MotionEvent;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.List;

/**
 * OFFLINE PROTOTYPE. Not installed. Hidden APIs are reflected and audited against donor smali.
 * No logging of coordinates, request IDs, users, biometric data, or events.
 * Core state belongs to the fingerprint Handler; input resources to a dedicated light looper.
 */
@SuppressWarnings("deprecation")
public final class DashUdfpsTouchBridge implements UdfpsTouchBridgeCore.Port {
    private static final String TAG = "DashUdfpsTouchBridge";
    private static final String FLAG = "persist.sys.dash.udfps_touch_bridge";
    private static volatile DashUdfpsTouchBridge instance;
    private static final java.util.concurrent.atomic.AtomicBoolean ENTRY_LOGGED =
            new java.util.concurrent.atomic.AtomicBoolean();
    private static final java.util.concurrent.atomic.AtomicInteger DIAGNOSTIC_COUNT =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicInteger FORWARD_DIAGNOSTIC_COUNT =
            new java.util.concurrent.atomic.AtomicInteger();

    private final Context context;
    private final Handler handler;
    private final DisplayManager displays;
    private final PowerManager power;
    private final Object fingerprintService;
    private final Class<?> pointerContextType;
    private final Class<?> clientType;
    private final Class<?> udfpsType;
    private final Method down;
    private final Method up;
    private final Method properties;
    private final Method getDisplayId;
    private final UdfpsTouchBridgeCore core;
    private final HandlerThread inputThread;
    private final Handler inputHandler;
    private final PassiveInputLease inputLease;
    private BroadcastReceiver receiver;
    private DisplayManager.DisplayListener displayListener;
    private boolean receiverRegistered;
    private boolean displayRegistered;

    private DashUdfpsTouchBridge(Context supplied) throws Exception {
        context = supplied;
        Class<?> provider = Class.forName("com.android.server.biometrics.BiometricHandlerProvider");
        Object handlerProvider = provider.getMethod("getInstance").invoke(null);
        handler = (Handler) provider.getMethod("getFingerprintHandler").invoke(handlerProvider);
        diagnostic("constructor handler ready");
        displays = context.getSystemService(DisplayManager.class);
        power = context.getSystemService(PowerManager.class);
        Method getService = Class.forName("android.os.ServiceManager")
                .getMethod("getService", String.class);
        if (displays == null || power == null) throw new IllegalStateException("unavailable");
        diagnostic("constructor display services ready");
        Object fpBinder = getService.invoke(null, "fingerprint");
        Class<?> stub = Class.forName("android.hardware.fingerprint.IFingerprintService$Stub");
        fingerprintService = stub.getMethod("asInterface", IBinder.class).invoke(null, fpBinder);
        if (fingerprintService == null) throw new IllegalStateException("unavailable");
        Class<?> fp = Class.forName("android.hardware.fingerprint.IFingerprintService");
        pointerContextType = Class.forName("android.hardware.biometrics.fingerprint.PointerContext");
        clientType = Class.forName("com.android.server.biometrics.sensors.BaseClientMonitor");
        udfpsType = Class.forName("com.android.server.biometrics.sensors.fingerprint.Udfps");
        down = fp.getMethod("onPointerDown", long.class, int.class, pointerContextType);
        up = fp.getMethod("onPointerUp", long.class, int.class, pointerContextType);
        properties = fp.getMethod("getSensorPropertiesInternal", String.class);
        getDisplayId = Class.forName("android.view.InputEvent").getMethod("getDisplayId");
        diagnostic("constructor fingerprint interface ready");
        core = new UdfpsTouchBridgeCore(this);
        // One cheap process-lifetime callback; inactive bridge never registers an input listener.
        Class.forName("android.os.SystemProperties").getMethod("addChangeCallback", Runnable.class)
                .invoke(null, (Runnable) () -> {
                    if (!enabledForDash()) invalidateAsync();
                });
        inputThread = new HandlerThread("DashUdfpsInput");
        inputThread.start();
        inputHandler = new Handler(inputThread.getLooper());
        inputLease = new PassiveInputLease(task -> {
            if (!inputHandler.post(task)) throw new IllegalStateException("input looper stopped");
        }, new PassiveInputLease.Factory() {
            @Override public Object createMonitor(long generation) {
                return InputManagerGlobal.getInstance().monitorGestureInput("DashUdfpsBridge", 0);
            }
            @Override public Object createReceiver(Object monitor, long generation) {
                return new BridgeInputReceiver(DashUdfpsTouchBridge.this,
                        ((InputMonitor) monitor).getInputChannel(), inputThread.getLooper(), generation);
            }
            @Override public void disposeReceiver(Object receiver) { ((InputEventReceiver) receiver).dispose(); }
            @Override public void disposeMonitor(Object monitor) { ((InputMonitor) monitor).dispose(); }
        }, new PassiveInputLease.Observer() {
            @Override public void ready(long generation) { diagnostic("input monitor receiver ready"); }
            @Override public void failed(long generation, Throwable failure) {
                diagnosticFailure("input monitor", failure);
                invalidateRegistration(generation, "input_monitor_failure");
            }
        });
    }

    private static final class BridgeInputReceiver extends InputEventReceiver {
        private final DashUdfpsTouchBridge bridge;
        private final long generation;
        private final java.util.concurrent.atomic.AtomicInteger observations = new java.util.concurrent.atomic.AtomicInteger();
        private boolean reported;
        BridgeInputReceiver(DashUdfpsTouchBridge bridge, InputChannel channel, Looper looper, long generation) {
            super(channel, looper);
            this.bridge = bridge; this.generation = generation;
        }
        @Override public void onInputEvent(InputEvent event) {
            try {
                if (!bridge.inputLease.canForward(generation)) return;
                if (event instanceof MotionEvent) {
                    if (!reported) { reported = true; diagnostic("passive input callback observed"); }
                    bridge.snapshot(generation, (MotionEvent) event, observations);
                }
            } catch (Throwable failure) {
                diagnosticFailure("input receiver", failure);
                bridge.invalidateRegistration(generation, "input_receiver_failure");
            } finally { finishInputEvent(event, false); }
        }
    }

    /** Hook only after SensorOverlays' real remote show succeeds. */
    public static void onShow(Object overlayOwner, int sensorId, int reason, Object client) {
        try {
            if (ENTRY_LOGGED.compareAndSet(false, true)) diagnostic("show hook entered");
            if (!gate()) { diagnostic("show suppressed: opt-in or SKU gate"); return; }
            DashUdfpsTouchBridge bridge = instance;
            if (bridge == null) {
                synchronized (DashUdfpsTouchBridge.class) {
                    bridge = instance;
                    if (bridge == null) {
                        Context context = (Context) Class.forName(
                                "com.android.server.biometrics.sensors.BaseClientMonitor")
                                .getMethod("getContext").invoke(client);
                        bridge = new DashUdfpsTouchBridge(context);
                        instance = bridge;
                        diagnostic("bridge initialized");
                    }
                }
            }
            DashUdfpsTouchBridge selected = bridge;
            selected.run(() -> selected.arm(overlayOwner, sensorId, reason, client));
        } catch (Throwable failure) { diagnosticFailure("onShow", failure); failClosed(); }
    }

    /** Hook at hide entry, outside the property check and outside the optional-controller branch. */
    public static void onHide(Object owner, int sensorId) {
        DashUdfpsTouchBridge bridge = instance;
        if (bridge != null) bridge.run(() -> {
            diagnostic("session hide armedBefore=" + bridge.core.armed());
            bridge.core.hide(owner, sensorId);
            diagnostic("session hide armedAfter=" + bridge.core.armed());
        });
    }

    private void arm(Object owner, int sensorId, int reason, Object client) {
        try {
            if (!udfpsType.isInstance(client)) {
                diagnostic("arm suppressed: client type"); core.invalidate(); return;
            }
            if (!isDisplayReady(0)) {
                Display d = displays.getDisplay(0);
                diagnostic("arm suppressed: screen available=" + (d != null)
                        + " on=" + (d != null && d.getState() == Display.STATE_ON)
                        + " portrait=" + (d != null && d.getRotation() == 0)
                        + " interactive=" + power.isInteractive());
                core.invalidate(); return;
            }
            long request = ((Number) clientType.getMethod("getRequestId").invoke(client)).longValue();
            int actualSensor = ((Number) clientType.getMethod("getSensorId").invoke(client)).intValue();
            int user = ((Number) clientType.getMethod("getTargetUserId").invoke(client)).intValue();
            if (sensorId != actualSensor) {
                diagnostic("arm suppressed: sensor mismatch"); core.invalidate(); return;
            }
            Object selected = null;
            for (Object item : (List<?>) properties.invoke(fingerprintService, "android")) {
                if (item.getClass().getField("sensorId").getInt(item) == sensorId) selected = item;
            }
            if (selected == null) {
                diagnostic("arm suppressed: metadata absent"); core.invalidate(); return;
            }
            int type = selected.getClass().getField("sensorType").getInt(selected);
            if (type != 2) {
                diagnostic("arm suppressed: unsupported sensor type"); core.invalidate(); return;
            } // This verified Xiaomi ultrasonic sensor only.
            Object location = selected.getClass().getMethod("getLocation").invoke(selected);
            float x = location.getClass().getField("sensorLocationX").getInt(location);
            float y = location.getClass().getField("sensorLocationY").getInt(location);
            float radius = location.getClass().getField("sensorRadius").getInt(location);
            Display.Mode mode = displays.getDisplay(0).getMode();
            UdfpsTouchBridgeCore.Target target = new UdfpsTouchBridgeCore.Target(owner, client,
                    request, sensorId, user, reason, 0, x, y, radius,
                    mode.getPhysicalWidth(), mode.getPhysicalHeight());
            diagnostic("arm preflight targetValid=" + target.valid()
                    + " clientLive=" + clientStillLive(target)
                    + " screenReady=" + displayReady(target));
            core.show(target);
            diagnostic("arm result registered=" + core.armed());
        } catch (Throwable failure) { diagnosticFailure("arm", failure); failClosed(); }
    }

    private static boolean gate() {
        try {
            Class<?> props = Class.forName("android.os.SystemProperties");
            String sku = (String) props.getMethod("get", String.class, String.class)
                    .invoke(null, "ro.boot.product.hardware.sku", "");
            return "dash".equals(sku) && (Boolean) props.getMethod("getBoolean", String.class, boolean.class)
                    .invoke(null, FLAG, false);
        } catch (Throwable failure) { return false; }
    }

    private void run(Runnable task) {
        try {
            if (Looper.myLooper() == handler.getLooper()) task.run();
            else handler.post(() -> { try { task.run(); } catch (Throwable failure) { failClosed(); } });
        } catch (Throwable failure) { failClosed(); }
    }

    private void invalidateAsync() { run(() -> {
        diagnostic("session invalidate gate armedBefore=" + core.armed());
        core.invalidate();
        diagnostic("session invalidate gate armedAfter=" + core.armed());
    }); }
    private static void diagnostic(String message) {
        if (DIAGNOSTIC_COUNT.getAndIncrement() < 64) Log.i(TAG, message);
    }
    private static void forwardDiagnostic(String message) {
        if (FORWARD_DIAGNOSTIC_COUNT.getAndIncrement() < 8) Log.i(TAG, message);
    }
    private static void diagnosticFailure(String phase, Throwable failure) {
        Throwable cause = failure.getCause();
        diagnostic(phase + " failed: class=" + failure.getClass().getSimpleName()
                + " cause=" + (cause == null ? "none" : cause.getClass().getSimpleName()));
    }
    private static void failClosed() {
        DashUdfpsTouchBridge bridge = instance;
        if (bridge != null) {
            try { bridge.handler.post(bridge.core::invalidate); } catch (Throwable ignored) { }
        }
        Log.w(TAG, "Bridge unavailable; normal biometric lifecycle retained");
    }
    private int rotation() {
        Display display = displays.getDisplay(0);
        return display == null ? -1 : display.getRotation();
    }
    @Override public boolean enabledForDash() { return gate(); }
    private boolean isDisplayReady(int displayId) {
        try {
            Display display = displays.getDisplay(displayId);
            return display != null && display.getState() == Display.STATE_ON
                    && display.getRotation() == 0 && power.isInteractive();
        } catch (Throwable failure) { return false; }
    }
    @Override public boolean displayReady(UdfpsTouchBridgeCore.Target target) {
        return isDisplayReady(target.displayId);
    }
    @Override public long uptimeMillis() { return SystemClock.uptimeMillis(); }
    @Override public boolean clientStillLive(UdfpsTouchBridgeCore.Target target) {
        try {
            return !((Boolean) clientType.getMethod("isAlreadyDone").invoke(target.client()))
                    && ((Number) clientType.getMethod("getRequestId").invoke(target.client())).longValue()
                        == target.requestId()
                    && ((Number) clientType.getMethod("getSensorId").invoke(target.client())).intValue()
                        == target.sensorId();
        } catch (Throwable failure) { return false; }
    }

    @Override public void register(long generation) throws Exception {
        diagnostic("listener registration entered");
        try { registerListeners(generation); }
        catch (Exception | LinkageError failure) {
            diagnosticFailure("listener registration", failure);
            throw failure;
        }
    }
    private void registerListeners(long generation) throws Exception {
        inputLease.open(generation);
        diagnostic("input monitor creation scheduled");
        displayListener = new DisplayManager.DisplayListener() {
            @Override public void onDisplayAdded(int id) { }
            @Override public void onDisplayRemoved(int id) {
                if (id == 0) invalidateRegistration(generation, "display_removed");
            }
            @Override public void onDisplayChanged(int id) {
                if (id == 0 && !isDisplayReady(id)) invalidateRegistration(generation, "display_not_ready");
            }
        };
        displays.registerDisplayListener(displayListener, handler);
        displayRegistered = true;
        diagnostic("display listener registered");
        receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context ignored, Intent intent) {
                String action = intent.getAction();
                String reason = Intent.ACTION_SCREEN_OFF.equals(action) ? "screen_off"
                        : Intent.ACTION_USER_SWITCHED.equals(action) ? "user_switch" : "shutdown";
                invalidateRegistration(generation, reason);
            }
        };
        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_OFF);
        filter.addAction(Intent.ACTION_USER_SWITCHED);
        filter.addAction(Intent.ACTION_SHUTDOWN);
        context.registerReceiver(receiver, filter, null, handler, Context.RECEIVER_NOT_EXPORTED);
        receiverRegistered = true;
        diagnostic("lifecycle receiver registered");
    }

    private void snapshot(long generation, MotionEvent event,
                          java.util.concurrent.atomic.AtomicInteger observations) {
        try {
            UdfpsTouchBridgeCore.Action action = switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN -> UdfpsTouchBridgeCore.Action.DOWN;
                case MotionEvent.ACTION_UP -> UdfpsTouchBridgeCore.Action.UP;
                case MotionEvent.ACTION_MOVE -> UdfpsTouchBridgeCore.Action.MOVE;
                case MotionEvent.ACTION_CANCEL -> UdfpsTouchBridgeCore.Action.CANCEL;
                case MotionEvent.ACTION_POINTER_DOWN -> UdfpsTouchBridgeCore.Action.POINTER_DOWN;
                case MotionEvent.ACTION_POINTER_UP -> UdfpsTouchBridgeCore.Action.POINTER_UP;
                default -> null;
            };
            if (action == null) return;
            if (action == UdfpsTouchBridgeCore.Action.CANCEL) { cancelSnapshot(generation, "motion_cancel"); return; }
            int count = event.getPointerCount();
            if (count <= 0) { cancelSnapshot(generation, "no_pointers"); return; }
            // Public normalized display pixels; never raw kernel 100x coordinates.
            boolean sourceTouch = event.isFromSource(InputDevice.SOURCE_TOUCHSCREEN);
            boolean deviceValid = event.getDeviceId() >= 0;
            boolean toolFinger = event.getToolType(0) == MotionEvent.TOOL_TYPE_FINGER;
            boolean finger = sourceTouch && deviceValid && toolFinger;
            UdfpsTouchBridgeCore.Motion copy = new UdfpsTouchBridgeCore.Motion(action,
                    ((Number) getDisplayId.invoke(event)).intValue(), rotation(), finger,
                    event.getPointerId(0), count, event.getRawX(0), event.getRawY(0),
                    event.getTouchMinor(0), event.getTouchMajor(0), event.getOrientation(0),
                    event.getEventTime(), event.getDownTime());
            boolean sampled = action != UdfpsTouchBridgeCore.Action.MOVE && observations.getAndIncrement() < 8;
            run(() -> {
                boolean beforeArmed = core.armed(), beforeHeld = core.pointerHeld();
                if (sampled) diagnostic("snapshot sourceTouch=" + sourceTouch + " deviceValid=" + deviceValid
                        + " toolFinger=" + toolFinger + " onePointer=" + (count == 1)
                        + " down=" + (action == UdfpsTouchBridgeCore.Action.DOWN)
                        + " up=" + (action == UdfpsTouchBridgeCore.Action.UP)
                        + " " + core.diagnosticState(generation, copy));
                core.motion(generation, copy);
                if (sampled || beforeArmed != core.armed() || beforeHeld != core.pointerHeld())
                    diagnostic("snapshot result armed=" + core.armed() + " held=" + core.pointerHeld());
            });
        } catch (Throwable failure) {
            diagnosticFailure("snapshot", failure);
            cancelSnapshot(generation, "snapshot_exception");
        }
    }

    private void cancelSnapshot(long generation, String reason) {
        UdfpsTouchBridgeCore.Motion canceled = new UdfpsTouchBridgeCore.Motion(
                UdfpsTouchBridgeCore.Action.CANCEL, -1, -1, false, -1, 0,
                Float.NaN, Float.NaN, 0, 0, 0, SystemClock.uptimeMillis(), 0);
        run(() -> {
            diagnostic("gesture cancel " + reason + " current=" + (generation == core.generation())
                    + " armedBefore=" + core.armed());
            core.motion(generation, canceled);
            diagnostic("gesture cancel armedAfter=" + core.armed() + " held=" + core.pointerHeld());
        });
    }
    private void invalidateRegistration(long generation, String reason) {
        run(() -> {
            diagnostic("session invalidate " + reason + " current=" + (generation == core.generation())
                    + " armedBefore=" + core.armed());
            core.invalidate(generation);
            diagnostic("session invalidate armedAfter=" + core.armed());
        });
    }

    @Override public void unregister() {
        inputLease.close();
        diagnostic("input monitor release scheduled");
        if (displayRegistered) {
            displayRegistered = false;
            DisplayManager.DisplayListener listenerToRemove = displayListener;
            displayListener = null;
            try { displays.unregisterDisplayListener(listenerToRemove); } catch (Throwable ignored) { }
        }
        if (receiverRegistered) {
            receiverRegistered = false;
            BroadcastReceiver receiverToRemove = receiver;
            receiver = null;
            try { context.unregisterReceiver(receiverToRemove); } catch (Throwable ignored) { }
        }
    }

    private Object pointerContext(UdfpsTouchBridgeCore.Motion motion) throws Exception {
        Object pc = pointerContextType.getConstructor().newInstance();
        set(pc, "pointerId", motion.pointerId()); set(pc, "x", motion.x()); set(pc, "y", motion.y());
        set(pc, "minor", motion.minor()); set(pc, "major", motion.major());
        set(pc, "orientation", motion.orientation()); set(pc, "isAod", false);
        set(pc, "time", motion.eventTime()); set(pc, "gestureStart", motion.downTime());
        return pc;
    }
    private static void set(Object object, String name, Object value) throws Exception {
        Field field = object.getClass().getField(name); field.set(object, value);
    }
    @Override public void pointerDown(UdfpsTouchBridgeCore.Target target,
                                      UdfpsTouchBridgeCore.Motion motion) throws Exception {
        forwardDiagnostic("pointer DOWN attempt fromMove=" + (motion.action == UdfpsTouchBridgeCore.Action.MOVE));
        down.invoke(fingerprintService, target.requestId(), target.sensorId(), pointerContext(motion));
        forwardDiagnostic("pointer DOWN API returned");
    }
    @Override public void pointerUp(UdfpsTouchBridgeCore.Target target,
                                    UdfpsTouchBridgeCore.Motion motion) throws Exception {
        forwardDiagnostic("pointer UP attempt");
        up.invoke(fingerprintService, target.requestId(), target.sensorId(), pointerContext(motion));
        forwardDiagnostic("pointer UP API returned");
    }
}
