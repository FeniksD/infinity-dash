package test;
public final class RadioBoundaryHarness {
 public static void main(String[] args) {
  try { test(); } catch(Throwable e) {e.printStackTrace(System.out);System.exit(1);}
 }
 public static void test() throws Exception {
  Class<?> target=Class.forName("test.RadioBoundaryUnderTest");
  for (int mode=0;mode<4;mode++) {
   Object object=target.getConstructor().newInstance();
   FakeServiceManager.mode=mode; FakeServiceManager.calls=0;
   Throwable failure=null;
   try {target.getMethod("run").invoke(object);}
   catch(java.lang.reflect.InvocationTargetException e) {failure=e.getCause();}
   if(mode==3) {if(!(failure instanceof IllegalStateException)) throw new AssertionError("unrelated error swallowed",failure);}
   else if(failure!=null)throw new AssertionError("registration mode "+mode+" escaped constructor boundary",failure);
   if(FakeServiceManager.calls!=1) throw new AssertionError("registration was duplicated or skipped");
   System.out.println("PASS registration mode "+mode);
  }
  System.out.println("PASS exact method body: normal, SELinux denial, dead binder, unrelated failure");
  System.exit(0);
 }
}
