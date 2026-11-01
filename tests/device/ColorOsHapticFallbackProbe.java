import java.lang.reflect.*;
import java.util.*;
public class ColorOsHapticFallbackProbe {
  static Class<?> op, step, composed; static Constructor<?> oc, sc, cc; static Method convert, segments, repeat;
  static Object o(int wave, long duration, int strength) throws Exception { return oc.newInstance(wave < 0 ? -1 : 68,wave,duration,strength,false,18); }
  static Object s(float amp,long duration) throws Exception { return sc.newInstance(amp,(int)duration); }
  static Object c(List<Object> list,int r) throws Exception { return cc.newInstance(list,r); }
  static List<?> list(Object c) throws Exception { return (List<?>)segments.invoke(c); }
  static void check(boolean ok,String name) { if(!ok) throw new AssertionError(name); }
  static void pulse(Object value,float amp,long duration) throws Exception {
    check(step.isInstance(value),"not StepSegment");
    float a=((Number)step.getMethod("getAmplitude").invoke(value)).floatValue();
    long d=((Number)step.getMethod("getDuration").invoke(value)).longValue();
    check(Math.abs(a-amp)<0.00001f,"amplitude "+a+" expected "+amp); check(d==duration,"duration "+d+" expected "+duration);
  }
  public static void main(String[] args) throws Exception {
    op=Class.forName("android.os.vibrator.OplusPrebakedSegment"); step=Class.forName("android.os.vibrator.StepSegment"); composed=Class.forName("android.os.VibrationEffect$Composed");
    oc=op.getConstructor(int.class,int.class,long.class,int.class,boolean.class,int.class); sc=step.getConstructor(float.class,int.class); cc=composed.getConstructor(List.class,int.class);
    segments=composed.getMethod("getSegments");repeat=composed.getMethod("getRepeatIndex");
    convert=Class.forName("com.android.server.vibrator.VibrationStepConductorExtImpl").getDeclaredMethod("convertDashHapticSegments",composed);convert.setAccessible(true);
    Object a=o(7,35,1200),gap=o(-1,80,-1),plain=s(.25f,20),z=o(6,45,2400);
    Object input=c(Arrays.asList(a,gap,plain,z),1);Object output=convert.invoke(null,input);List<?> out=list(output);
    check(out.size()==4,"segment count");pulse(out.get(0),.5f,35);pulse(out.get(1),0f,80);check(out.get(2)==plain,"plain segment identity");pulse(out.get(3),1f,45);
    check(((Number)repeat.invoke(output)).intValue()==1,"repeat index");check(list(input).get(0)==a && list(input).get(1)==gap,"original mutated");
    Object again=convert.invoke(null,output);check(list(again).equals(out),"not idempotent");
    Object defaults=convert.invoke(null,c(Arrays.asList(o(1,30,-1),o(1,30,0),o(1,30,4000),o(-1,25,2400)), -1));
    List<?> d=list(defaults);pulse(d.get(0),1f,30);pulse(d.get(1),0f,30);pulse(d.get(2),1f,30);pulse(d.get(3),0f,25);
    Object edge=convert.invoke(null,c(Arrays.asList(o(1,-5,1200),o(1,Long.MAX_VALUE,1200)), -1)); pulse(list(edge).get(0),.5f,0); pulse(list(edge).get(1),.5f,Integer.MAX_VALUE);
    System.out.println("PASS: actual ART converter preserves pauses, repeats, original list, standard segments, durations and amplitude bounds.");
    System.out.println("MOTOR_COMMANDS_ISSUED=0");
  }
}
