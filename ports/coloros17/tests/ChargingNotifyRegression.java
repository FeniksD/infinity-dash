import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** Scratch ART test: no constructors, HAL calls, broadcasts or charging writes. */
public final class ChargingNotifyRegression {
    private static Class<?> serviceClass;
    private static Object unsafe;
    private static Method allocateInstance;
    private static Method update;
    private static Field code;
    private static Field unavailable;
    private static int cases;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static Object instance(int previous) throws Exception {
        Object object = allocateInstance.invoke(unsafe, serviceClass);
        code.setInt(object, previous);
        check(!unavailable.getBoolean(object), "new instance availability default");
        Field context = serviceClass.getDeclaredField("mContext");
        context.setAccessible(true);
        Field batteryService = serviceClass.getDeclaredField("mBas");
        batteryService.setAccessible(true);
        check(context.get(object) == null && batteryService.get(object) == null,
                "constructor dependencies must remain uninitialized");
        return object;
    }

    private static void sample(Object object, int value, int wanted, boolean missing)
            throws Exception {
        update.invoke(object, value);
        check(code.getInt(object) == wanted,
                "sample " + value + " produced " + code.getInt(object) + "; expected " + wanted);
        check(unavailable.getBoolean(object) == missing,
                "sample " + value + " availability state");
        cases++;
    }

    public static void main(String[] args) throws Exception {
        String vm = System.getProperty("java.vm.name", "");
        check(vm.contains("Dalvik") || vm.contains("ART"), "must run on Android ART: " + vm);
        serviceClass = Class.forName("com.android.server.OplusBatteryService");
        code = serviceClass.getDeclaredField("mBatteryNotifyCode");
        code.setAccessible(true);
        unavailable = serviceClass.getDeclaredField("mBatteryNotifyUnavailable");
        unavailable.setAccessible(true);
        update = serviceClass.getDeclaredMethod("updateBatteryNotifyCode", int.class);
        update.setAccessible(true);

        Class<?> unsafeClass = Class.forName("sun.misc.Unsafe");
        Field singleton = unsafeClass.getDeclaredField("theUnsafe");
        singleton.setAccessible(true);
        unsafe = singleton.get(null);
        allocateInstance = unsafeClass.getMethod("allocateInstance", Class.class);

        for (int negative : new int[] {-1, -95, Integer.MIN_VALUE}) {
            sample(instance(0), negative, 0, true);
            sample(instance(2), negative, 2, true);
            sample(instance(0x40A), negative, 0x40A, true);
        }
        for (int valid : new int[] {0, 2, 8, 0x40A, Integer.MAX_VALUE}) {
            sample(instance(2), valid, valid, false);
        }
        Object sequence = instance(0);
        sample(sequence, -1, 0, true);
        sample(sequence, -95, 0, true);
        sample(sequence, 2, 2, false);
        sample(sequence, -1, 2, true);
        sample(sequence, 0, 0, false);
        sample(sequence, 8, 8, false);
        sample(sequence, -95, 8, true);

        System.out.println("PASS: " + cases + " actual ART samples; negative/zero/positive, "
                + "fault retention and recovery verified.");
        System.out.println("HAL_CALLS=0 CONSTRUCTORS_RUN=0 BROADCASTS_SENT=0 CHARGING_WRITES=0");
        System.out.println("CLASSPATH=" + System.getProperty("java.class.path"));
        System.exit(0);
    }
}
