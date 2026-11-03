package test;
public final class FakeServiceManager {
 public static int mode, calls;
 public static void registerForNotifications(String name, Object callback) throws android.os.RemoteException {
  calls++;
  if (!name.equals("vendor.oplus.hardware.radio.IRadioStable/OplusRadio0")) throw new AssertionError(name);
  if (mode==1) throw new SecurityException("Optional OPPO interface is absent");
  if (mode==2) throw new android.os.RemoteException("Remote unavailable");
  if (mode==3) throw new IllegalStateException("Unrelated programming error");
 }
}
