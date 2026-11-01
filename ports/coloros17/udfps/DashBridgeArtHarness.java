package com.android.server.biometrics.sensors.dash;

import android.content.Context;
import android.os.IBinder;
import android.os.Parcel;
import android.os.Parcelable;
import android.view.MotionEvent;
import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Enumeration;

/** Verifier-only ART harness. Never calls bridge hooks, registers listeners, or sends HAL commands. */
public final class DashBridgeArtHarness {
    private static Class<?> type(String name) throws ClassNotFoundException {
        return Class.forName(name, false, DashBridgeArtHarness.class.getClassLoader());
    }
    private static void require(boolean condition, String what) {
        if (!condition) throw new AssertionError(what);
    }
    private static Field field(Class<?> type, String name) throws Exception {
        Field result = type.getDeclaredField(name); result.setAccessible(true); return result;
    }
    private static String origin(Class<?> type) throws Exception {
        Object loader = type.getClassLoader();
        require(loader != null, "production unexpectedly loaded by bootstrap loader");
        Object pathList = field(Class.forName("dalvik.system.BaseDexClassLoader"), "pathList").get(loader);
        Object[] elements = (Object[]) field(pathList.getClass(), "dexElements").get(pathList);
        for (Object element : elements) {
            Object dex = field(element.getClass(), "dexFile").get(element);
            if (dex == null) continue;
            Method entries = dex.getClass().getMethod("entries");
            Enumeration<?> names = (Enumeration<?>) entries.invoke(dex);
            while (names.hasMoreElements()) {
                if (type.getName().equals(names.nextElement())) {
                    return (String) dex.getClass().getMethod("getName").invoke(dex);
                }
            }
        }
        throw new AssertionError("class origin not found: " + type.getName());
    }
    private static void requireOrigin(Class<?> type, String expected) throws Exception {
        require(new File(origin(type)).getCanonicalFile().equals(new File(expected).getCanonicalFile()),
                "wrong class origin: " + type.getName());
    }
    public static void main(String[] args) throws Exception {
        if ((args.length != 3 && args.length != 4) || !"--verify-only".equals(args[0]))
            throw new IllegalArgumentException("Use --verify-only CANDIDATE_JAR TEST_ONLY_DEX [OPLUS_CANDIDATE_JAR]");
        ClassLoader loader = DashBridgeArtHarness.class.getClassLoader();
        Class.forName(DashUdfpsTouchBridge.class.getName(), false, loader);
        requireOrigin(DashBridgeArtHarness.class, args[2]);
        requireOrigin(UdfpsTouchBridgeCoreTest.class, args[2]);
        requireOrigin(DashUdfpsTouchBridge.class, args[1]);
        requireOrigin(UdfpsTouchBridgeCore.class, args[1]);
        requireOrigin(UdfpsTouchBridgeCore.Target.class, args[1]);
        requireOrigin(UdfpsTouchBridgeCore.Motion.class, args[1]);
        requireOrigin(UdfpsTouchBridgeCore.Port.class, args[1]);
        requireOrigin(PassiveInputLease.class, args[1]);
        requireOrigin(PassiveInputLease.Factory.class, args[1]);
        requireOrigin(PassiveInputLease.Observer.class, args[1]);
        requireOrigin(PassiveInputLease.Scheduler.class, args[1]);
        requireOrigin(PassiveInputLeaseTest.class, args[2]);
        requireOrigin(RootedInputResources.class, args[1]);
        requireOrigin(RootedInputResources.Operations.class, args[1]);
        requireOrigin(RootedInputResourcesTest.class, args[2]);
        requireOrigin(OemFingerprintUiCompat.class, args[1]);
        requireOrigin(OemFingerprintUiCompat.Result.class, args[1]);
        requireOrigin(OemFingerprintUiCompat.PointerCall.class, args[1]);
        requireOrigin(OemFingerprintUiCompat.UiPort.class, args[1]);
        requireOrigin(OemFingerprintUiCompat.OwnedRelay.class, args[1]);
        requireOrigin(OemFingerprintUiCompatTest.class, args[2]);
        requireOrigin(UdfpsSessionCoordinator.class, args[1]);
        requireOrigin(UdfpsSessionCoordinatorTest.class, args[2]);
        UdfpsSessionCoordinator.class.getMethod("screenOn");
        UdfpsSessionCoordinator.class.getMethod("suspend");
        UdfpsSessionCoordinator.class.getMethod("registrationFailed");
        System.out.println("PASS exact class origins: production=candidate, tests=test-only DEX");
        Class<?> client = type("com.android.server.biometrics.sensors.BaseClientMonitor");
        require(client.getMethod("getContext").getReturnType() == Context.class, "client context");
        require(client.getMethod("getRequestId").getReturnType() == long.class, "request type");
        client.getMethod("getSensorId"); client.getMethod("getTargetUserId");
        client.getMethod("isAlreadyDone");
        Class<?> acquisition = type("com.android.server.biometrics.sensors.AcquisitionClient");
        require(type("com.android.server.biometrics.sensors.SensorOverlays")
                .getMethod("show", int.class, int.class, acquisition).getReturnType() == void.class,
                "exact OEM relay method signature");
        require(DashUdfpsTouchBridge.class.getMethod("normalizeEnrollmentTotal", int.class)
                .getReturnType() == int.class, "enrollment normalizer descriptor");
        Class<?> providerExt = type("com.android.server.biometrics.sensors.fingerprint.aidl.FingerprintServiceProviderExtImpl");
        require(providerExt.getMethod("getEnrollmentTotalTimes", int.class).getReturnType() == int.class,
                "OEM enrollment getter descriptor");
        if (args.length == 4) requireOrigin(providerExt, args[3]);
        Class<?> global = type("android.hardware.input.InputManagerGlobal");
        global.getMethod("getInstance");
        global.getMethod("monitorGestureInput", String.class, int.class);
        Class<?> monitor = type("android.view.InputMonitor");
        monitor.getMethod("getInputChannel"); monitor.getMethod("dispose");
        monitor.getMethod("getSurface");
        Class<?> surface = type("android.view.SurfaceControl");
        surface.getMethod("release");
        Class<?> builder = type("android.view.SurfaceControl$Builder");
        builder.getConstructor(); builder.getMethod("setName", String.class);
        builder.getMethod("setContainerLayer"); builder.getMethod("build");
        Class<?> transaction = type("android.view.SurfaceControl$Transaction");
        transaction.getMethod("reparent", surface, surface);
        transaction.getMethod("setLayerStack", surface, int.class);
        transaction.getMethod("setLayer", surface, int.class);
        transaction.getMethod("setCrop", surface, type("android.graphics.Rect"));
        transaction.getMethod("setPosition", surface, float.class, float.class);
        transaction.getMethod("show", surface); transaction.getMethod("remove", surface);
        transaction.getMethod("apply"); transaction.getMethod("close");
        Class<?> displayGlobal = type("android.hardware.display.DisplayManagerGlobal");
        displayGlobal.getMethod("getInstance"); displayGlobal.getMethod("getDisplayInfo", int.class);
        Class<?> displayInfo = type("android.view.DisplayInfo");
        for (String field : new String[] {"layerStack", "logicalWidth", "logicalHeight", "rotation"})
            displayInfo.getField(field);
        Class<?> inputEvent = type("android.view.InputEvent");
        Class<?> eventReceiver = type("android.view.InputEventReceiver");
        eventReceiver.getConstructor(type("android.view.InputChannel"), type("android.os.Looper"));
        eventReceiver.getMethod("onInputEvent", inputEvent);
        eventReceiver.getMethod("finishInputEvent", inputEvent, boolean.class);
        eventReceiver.getMethod("dispose");
        Class<?> bridgeReceiver = type("com.android.server.biometrics.sensors.dash.DashUdfpsTouchBridge$BridgeInputReceiver");
        requireOrigin(bridgeReceiver, args[1]);
        require(bridgeReceiver.getSuperclass() == eventReceiver, "candidate input receiver superclass");
        bridgeReceiver.getDeclaredMethod("onInputEvent", inputEvent);
        Class<?> props = type("android.os.SystemProperties");
        props.getMethod("get", String.class, String.class);
        props.getMethod("getBoolean", String.class, boolean.class);
        props.getMethod("addChangeCallback", Runnable.class);
        Class<?> provider = type("com.android.server.biometrics.BiometricHandlerProvider");
        provider.getMethod("getInstance"); provider.getMethod("getFingerprintHandler");
        Class<?> fp = type("android.hardware.fingerprint.IFingerprintService");
        Class<?> pc = type("android.hardware.biometrics.fingerprint.PointerContext");
        fp.getMethod("onPointerDown", long.class, int.class, pc);
        fp.getMethod("onPointerUp", long.class, int.class, pc);
        fp.getMethod("getSensorPropertiesInternal", String.class);
        type("android.hardware.fingerprint.IFingerprintService$Stub")
                .getMethod("asInterface", IBinder.class);
        Class<?> sensor = type("android.hardware.fingerprint.FingerprintSensorPropertiesInternal");
        sensor.getField("sensorId"); sensor.getField("sensorType");
        Class<?> location = sensor.getMethod("getLocation").getReturnType();
        location.getField("sensorLocationX"); location.getField("sensorLocationY");
        location.getField("sensorRadius");
        type("android.view.InputEvent").getMethod("getDisplayId");
        type("android.view.Display").getMethod("getState");
        type("android.view.Display").getField("STATE_ON");
        type("android.os.PowerManager").getMethod("isInteractive");
        Object pointer = pc.getConstructor().newInstance();
        pc.getField("pointerId").setInt(pointer, 3);
        pc.getField("x").setFloat(pointer, 638f);
        pc.getField("y").setFloat(pointer, 2060f);
        pc.getField("minor").setFloat(pointer, 12f);
        pc.getField("major").setFloat(pointer, 20f);
        pc.getField("time").setLong(pointer, 1200L);
        pc.getField("gestureStart").setLong(pointer, 1000L);
        Parcel parcel = Parcel.obtain();
        try {
            ((Parcelable) pointer).writeToParcel(parcel, 0);
            require(parcel.dataSize() == 48, "PointerContext size");
            parcel.setDataPosition(0);
            Parcelable.Creator<?> creator = (Parcelable.Creator<?>) pc.getField("CREATOR").get(null);
            Object restored = creator.createFromParcel(parcel);
            require(pc.getField("pointerId").getInt(restored) == 3, "pointer roundtrip");
            require(pc.getField("x").getFloat(restored) == 638f, "x roundtrip");
            require(pc.getField("time").getLong(restored) == 1200L, "time roundtrip");
        } finally { parcel.recycle(); }
        UdfpsTouchBridgeCoreTest.main(new String[0]);
        PassiveInputLeaseTest.main(new String[0]);
        RootedInputResourcesTest.main(new String[0]);
        OemFingerprintUiCompatTest.main(new String[0]);
        UdfpsSessionCoordinatorTest.main(new String[0]);
        System.out.println("PASS donor API reflection and PointerContext roundtrip; no HAL/input writes");
    }
}
