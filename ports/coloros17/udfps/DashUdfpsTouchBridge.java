package com.android.server.biometrics.sensors.dash;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.display.DisplayManager;
import android.hardware.display.DisplayManagerGlobal;
import android.graphics.Rect;
import android.hardware.input.InputManagerGlobal;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;
import android.view.Display;
import android.view.DisplayInfo;
import android.view.SurfaceControl;
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
public final class DashUdfpsTouchBridge implements UdfpsTouchBridgeCore.Port, OemFingerprintUiCompat.UiPort {
    private static final String TAG = "DashUdfpsTouchBridge";
    private static final String FLAG = "persist.sys.dash.udfps_touch_bridge";
    private static volatile DashUdfpsTouchBridge instance;
    private static final java.util.concurrent.atomic.AtomicBoolean ENTRY_LOGGED =
            new java.util.concurrent.atomic.AtomicBoolean();
    private static final java.util.concurrent.atomic.AtomicInteger DIAGNOSTIC_COUNT =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicInteger FORWARD_DIAGNOSTIC_COUNT =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicInteger UI_DIAGNOSTIC_COUNT =
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
    private final UdfpsSessionCoordinator coordinator;
    private final HandlerThread inputThread;
    private final Handler inputHandler;
    private final PassiveInputLease inputLease;
    private final OemFingerprintUiCompat.OwnedRelay uiRelay = new OemFingerprintUiCompat.OwnedRelay();
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
        coordinator = new UdfpsSessionCoordinator(core, this);
        inputThread = new HandlerThread("DashUdfpsInput");
        inputThread.start();
        inputHandler = new Handler(inputThread.getLooper());
        inputLease = new PassiveInputLease(task -> {
            if (!inputHandler.post(task)) throw new IllegalStateException("input looper stopped");
        }, new PassiveInputLease.Factory() {
            @Override public Object createMonitor(long generation) throws Exception {
                return RootedInputResources.create(new RootedInputResources.Operations() {
                    @Override public Object createRoot() {
                        return new SurfaceControl.Builder().setName("DashUdfpsInputRoot")
                                .setContainerLayer().build();
                    }
                    @Override public Object createMonitor() {
                        return InputManagerGlobal.getInstance().monitorGestureInput("DashUdfpsBridge", 0);
                    }
                    @Override public void configure(Object root, Object monitor) {
                        DisplayInfo info = DisplayManagerGlobal.getInstance().getDisplayInfo(0);
                        if (info == null || info.rotation != 0 || info.logicalWidth <= 0 || info.logicalHeight <= 0)
                            throw new IllegalStateException("portrait display unavailable");
                        SurfaceControl ownRoot = (SurfaceControl) root;
                        SurfaceControl ownMonitor = ((InputMonitor) monitor).getSurface();
                        Rect crop = new Rect(0, 0, info.logicalWidth, info.logicalHeight);
                        try (SurfaceControl.Transaction transaction = new SurfaceControl.Transaction()) {
                            transaction.setLayerStack(ownRoot, info.layerStack);
                            transaction.setLayer(ownRoot, Integer.MAX_VALUE);
                            transaction.setPosition(ownRoot, 0f, 0f);
                            transaction.setCrop(ownRoot, crop);
                            transaction.show(ownRoot);
                            transaction.reparent(ownMonitor, ownRoot);
                            transaction.setLayer(ownMonitor, 1);
                            transaction.setPosition(ownMonitor, 0f, 0f);
                            transaction.setCrop(ownMonitor, crop);
                            transaction.show(ownMonitor);
                            transaction.apply();
                        }
                    }
                    @Override public void disposeMonitor(Object monitor) { ((InputMonitor) monitor).dispose(); }
                    @Override public void removeRoot(Object root) {
                        try (SurfaceControl.Transaction transaction = new SurfaceControl.Transaction()) {
                            transaction.remove((SurfaceControl) root);
                            transaction.apply();
                        }
                    }
                    @Override public void releaseRoot(Object root) { ((SurfaceControl) root).release(); }
                });
            }
            @Override public Object createReceiver(Object monitor, long generation) {
                return new BridgeInputReceiver(DashUdfpsTouchBridge.this,
                        ((InputMonitor) ((RootedInputResources) monitor).monitor()).getInputChannel(),
                        inputThread.getLooper(), generation);
            }
            @Override public void disposeReceiver(Object receiver) { ((InputEventReceiver) receiver).dispose(); }
            @Override public void disposeMonitor(Object monitor) throws Exception { ((RootedInputResources) monitor).close(); }
        }, new PassiveInputLease.Observer() {
            @Override public void ready(long generation) { diagnostic("input monitor receiver ready"); }
            @Override public void failed(long generation, Throwable failure) {
                diagnosticFailure("input monitor", failure);
                invalidateRegistration(generation, "input_monitor_failure");
            }
        });
        // All state and lease fields exist before any process-lifetime callback can run.
        try {
            installLifecycleObservers();
            Class.forName("android.os.SystemProperties").getMethod("addChangeCallback", Runnable.class)
                    .invoke(null, (Runnable) () -> {
                        if (!enabledForDash()) invalidateAsync();
                    });
        } catch (Exception | LinkageError failure) {
            removeLifecycleObservers();
            inputThread.quitSafely();
            throw failure;
        }
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
            if (UdfpsTouchBridgeCore.isOemStatusReason(reason)) return;
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
            bridge.coordinator.hide(owner, sensorId);
            diagnostic("session hide armedAfter=" + bridge.core.armed());
        });
    }

    private void arm(Object owner, int sensorId, int reason, Object client) {
        try {
            if (!udfpsType.isInstance(client)) {
                diagnostic("arm suppressed: client type"); coordinator.clear(); return;
            }
            long request = ((Number) clientType.getMethod("getRequestId").invoke(client)).longValue();
            int actualSensor = ((Number) clientType.getMethod("getSensorId").invoke(client)).intValue();
            int user = ((Number) clientType.getMethod("getTargetUserId").invoke(client)).intValue();
            if (sensorId != actualSensor) {
                diagnostic("arm suppressed: sensor mismatch"); coordinator.clear(); return;
            }
            Object selected = null;
            for (Object item : (List<?>) properties.invoke(fingerprintService, "android")) {
                if (item.getClass().getField("sensorId").getInt(item) == sensorId) selected = item;
            }
            if (selected == null) {
                diagnostic("arm suppressed: metadata absent"); coordinator.clear(); return;
            }
            int type = selected.getClass().getField("sensorType").getInt(selected);
            if (type != 2) {
                diagnostic("arm suppressed: unsupported sensor type"); coordinator.clear(); return;
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
            coordinator.show(target);
            diagnostic("arm result pending=" + coordinator.hasPending() + " registered=" + core.armed());
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

    /** Called only by the narrowly patched OEM enrollment-total getter. */
    public static int normalizeEnrollmentTotal(int total) {
        if (total > 0) return total;
        return OemFingerprintUiCompat.normalizeEnrollmentTotal(total, gate());
    }

    private void run(Runnable task) {
        try {
            if (Looper.myLooper() == handler.getLooper()) task.run();
            else handler.post(() -> { try { task.run(); } catch (Throwable failure) { failClosed(); } });
        } catch (Throwable failure) { failClosed(); }
    }

    private void invalidateAsync() { run(() -> {
        diagnostic("session invalidate gate armedBefore=" + core.armed());
        coordinator.clear();
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
            try { bridge.handler.post(bridge.coordinator::clear); } catch (Throwable ignored) { }
        }
        Log.w(TAG, "Bridge unavailable; normal biometric lifecycle retained");
    }
    private int rotation() {
        Display display = displays.getDisplay(0);
        return display == null ? -1 : display.getRotation();
    }
    @Override public boolean enabledForDash() { return gate(); }
    @Override public boolean ownsTarget(UdfpsTouchBridgeCore.Target target) { return core.ownsTarget(target); }
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
            coordinator.registrationFailed();
            diagnosticFailure("listener registration", failure);
            throw failure;
        }
    }
    private void registerListeners(long generation) throws Exception {
        inputLease.open(generation);
        diagnostic("input monitor creation scheduled");
    }

    private void installLifecycleObservers() {
        displayListener = new DisplayManager.DisplayListener() {
            @Override public void onDisplayAdded(int id) {
                if (id == 0) coordinator.readinessChanged();
            }
            @Override public void onDisplayRemoved(int id) {
                if (id == 0) coordinator.clear();
            }
            @Override public void onDisplayChanged(int id) {
                if (id == 0) coordinator.readinessChanged();
            }
        };
        displays.registerDisplayListener(displayListener, handler);
        displayRegistered = true;
        receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context ignored, Intent intent) {
                String action = intent.getAction();
                if (Intent.ACTION_SCREEN_OFF.equals(action)) coordinator.suspend();
                else if (Intent.ACTION_SCREEN_ON.equals(action) || Intent.ACTION_USER_PRESENT.equals(action))
                    coordinator.screenOn();
                else coordinator.clear();
            }
        };
        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_OFF);
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_USER_PRESENT);
        filter.addAction(Intent.ACTION_USER_SWITCHED);
        filter.addAction(Intent.ACTION_SHUTDOWN);
        context.registerReceiver(receiver, filter, null, handler, Context.RECEIVER_NOT_EXPORTED);
        receiverRegistered = true;
        diagnostic("process-lifetime readiness observers registered");
    }

    private void removeLifecycleObservers() {
        if (displayRegistered) {
            displayRegistered = false;
            try { displays.unregisterDisplayListener(displayListener); } catch (Throwable ignored) { }
            displayListener = null;
        }
        if (receiverRegistered) {
            receiverRegistered = false;
            try { context.unregisterReceiver(receiver); } catch (Throwable ignored) { }
            receiver = null;
        }
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
                coordinator.motion(generation, copy);
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
            coordinator.motion(generation, canceled);
            diagnostic("gesture cancel armedAfter=" + core.armed() + " held=" + core.pointerHeld());
        });
    }
    private void invalidateRegistration(long generation, String reason) {
        run(() -> {
            diagnostic("session invalidate " + reason + " current=" + (generation == core.generation())
                    + " armedBefore=" + core.armed());
            coordinator.captureFailure(generation);
            diagnostic("session invalidate armedAfter=" + core.armed());
        });
    }

    @Override public void unregister() {
        coordinator.captureUnregistered();
        uiRelay.forget();
        inputLease.close();
        diagnostic("input monitor release scheduled");
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
        try {
            OemFingerprintUiCompat.Result result = uiRelay.pointerThenRelay(() -> {
                down.invoke(fingerprintService, target.requestId(), target.sensorId(), pointerContext(motion));
                forwardDiagnostic("pointer DOWN API returned");
            }, target, true, this);
            uiRelayDiagnostic(true, result);
        } catch (Exception | LinkageError primaryFailure) {
            coordinator.pointerFailed();
            throw primaryFailure;
        }
    }
    @Override public void pointerUp(UdfpsTouchBridgeCore.Target target,
                                    UdfpsTouchBridgeCore.Motion motion) throws Exception {
        forwardDiagnostic("pointer UP attempt");
        try {
            OemFingerprintUiCompat.Result result = uiRelay.pointerThenRelay(() -> {
                up.invoke(fingerprintService, target.requestId(), target.sensorId(), pointerContext(motion));
                forwardDiagnostic("pointer UP API returned");
            }, target, false, this);
            uiRelayDiagnostic(false, result);
        } catch (Exception | LinkageError primaryFailure) {
            coordinator.pointerFailed();
            throw primaryFailure;
        }
    }
    @Override public void relay(UdfpsTouchBridgeCore.Target target, int reason) throws Exception {
        // Resolve lazily: presentation API absence must not prevent native touch forwarding.
        Class<?> ownerType = Class.forName("com.android.server.biometrics.sensors.SensorOverlays");
        Class<?> acquisitionType = Class.forName("com.android.server.biometrics.sensors.AcquisitionClient");
        if (!ownerType.isInstance(target.overlayOwner) || !acquisitionType.isInstance(target.client))
            throw new IllegalArgumentException("unsupported OEM overlay owner");
        ownerType.getMethod("show", int.class, int.class, acquisitionType)
                .invoke(target.overlayOwner, target.sensorId(), reason, target.client);
    }
    private static void uiRelayDiagnostic(boolean down, OemFingerprintUiCompat.Result result) {
        try {
            if (UI_DIAGNOSTIC_COUNT.getAndIncrement() < 8)
                Log.i(TAG, "optional UI relay " + (down ? "DOWN" : "UP") + " result=" + result);
        } catch (Throwable ignored) { }
    }
}
