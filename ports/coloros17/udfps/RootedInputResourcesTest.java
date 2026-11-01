package com.android.server.biometrics.sensors.dash;

import java.util.ArrayList;
import java.util.List;

/** Pure resource ownership tests; no SurfaceControl/InputMonitor or phone access. */
public final class RootedInputResourcesTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++; if (!value) throw new AssertionError(message);
    }
    private static final class Ops implements RootedInputResources.Operations {
        final List<String> calls = new ArrayList<>();
        String fail;
        Runnable afterConfigure;
        public Object createRoot() throws Exception { calls.add("root"); fail("root"); return "root"; }
        public Object createMonitor() throws Exception { calls.add("monitor"); fail("monitor"); return "monitor"; }
        public void configure(Object root, Object monitor) throws Exception {
            calls.add("configure"); if (afterConfigure != null) afterConfigure.run(); fail("configure");
        }
        public void disposeMonitor(Object monitor) throws Exception { calls.add("dispose-monitor"); fail("dispose-monitor"); }
        public void removeRoot(Object root) throws Exception { calls.add("remove-root"); fail("remove-root"); }
        public void releaseRoot(Object root) throws Exception { calls.add("release-root"); fail("release-root"); }
        private void fail(String name) throws Exception { if (name.equals(fail)) throw new Exception(name); }
    }
    private static void normal() throws Exception {
        Ops ops = new Ops(); RootedInputResources resources = RootedInputResources.create(ops);
        check(resources != null && "monitor".equals(resources.monitor()), "returns the owned monitor");
        resources.close(); resources.close();
        check(ops.calls.equals(List.of("root", "monitor", "configure", "dispose-monitor", "remove-root", "release-root")),
                "normal close releases monitor then root once");
    }
    private static void partialFailures() {
        for (String phase : List.of("root", "monitor", "configure")) {
            Ops ops = new Ops(); ops.fail = phase;
            boolean threw = false;
            try { RootedInputResources.create(ops); } catch (Exception expected) { threw = true; }
            check(threw, "construction failure is propagated");
            List<String> wanted = switch (phase) {
                case "root" -> List.of("root");
                case "monitor" -> List.of("root", "monitor", "remove-root", "release-root");
                default -> List.of("root", "monitor", "configure", "dispose-monitor", "remove-root", "release-root");
            };
            check(ops.calls.equals(wanted), "partial root/monitor/configure failure releases every owned resource");
        }
    }
    private static void closeFailures() throws Exception {
        for (String phase : List.of("dispose-monitor", "remove-root", "release-root")) {
            Ops ops = new Ops(); RootedInputResources resources = RootedInputResources.create(ops); ops.fail = phase;
            boolean threw = false;
            try { resources.close(); } catch (Exception expected) { threw = true; }
            check(threw, "close failure propagated");
            check(ops.calls.subList(3, 6).equals(List.of("dispose-monitor", "remove-root", "release-root")),
                    "one cleanup failure cannot skip remaining cleanup");
            resources.close();
            check(ops.calls.size() == 6, "failed close remains idempotent");
        }
    }
    private static void integrationWithPendingLease() {
        List<Runnable> queue = new ArrayList<>(); List<Ops> created = new ArrayList<>();
        PassiveInputLease lease = new PassiveInputLease(queue::add, new PassiveInputLease.Factory() {
            public Object createMonitor(long generation) throws Exception {
                Ops ops = new Ops(); created.add(ops); return RootedInputResources.create(ops);
            }
            public Object createReceiver(Object monitor, long generation) { return "receiver"; }
            public void disposeReceiver(Object receiver) { }
            public void disposeMonitor(Object monitor) throws Exception { ((RootedInputResources) monitor).close(); }
        }, new PassiveInputLease.Observer() {
            public void ready(long generation) { }
            public void failed(long generation, Throwable failure) { throw new AssertionError(failure); }
        });
        lease.open(1); while (!queue.isEmpty()) queue.remove(0).run();
        lease.open(2); lease.close(); while (!queue.isEmpty()) queue.remove(0).run();
        check(created.size() == 1, "cancelled pending replacement creates no second root");
        check(created.get(0).calls.equals(List.of("root", "monitor", "configure", "dispose-monitor", "remove-root", "release-root")),
                "lease retires both resources from previous generation");
    }
    private static void cancellationDuringSetup() {
        List<Runnable> queue = new ArrayList<>(); Ops ops = new Ops();
        PassiveInputLease[] holder = new PassiveInputLease[1];
        boolean[] receiverCreated = {false};
        holder[0] = new PassiveInputLease(queue::add, new PassiveInputLease.Factory() {
            public Object createMonitor(long generation) throws Exception {
                ops.afterConfigure = () -> holder[0].close();
                return RootedInputResources.create(ops);
            }
            public Object createReceiver(Object monitor, long generation) { receiverCreated[0] = true; return "receiver"; }
            public void disposeReceiver(Object receiver) { }
            public void disposeMonitor(Object monitor) throws Exception { ((RootedInputResources) monitor).close(); }
        }, new PassiveInputLease.Observer() {
            public void ready(long generation) { throw new AssertionError("cancelled setup became ready"); }
            public void failed(long generation, Throwable failure) { throw new AssertionError(failure); }
        });
        holder[0].open(1); while (!queue.isEmpty()) queue.remove(0).run();
        check(!receiverCreated[0] && !holder[0].canForward(1), "cancelled root setup never creates receiver or forwards");
        check(ops.calls.equals(List.of("root", "monitor", "configure", "dispose-monitor", "remove-root", "release-root")),
                "cancelled root setup releases completed root and monitor");
    }
    public static void main(String[] args) throws Exception {
        normal(); partialFailures(); closeFailures(); integrationWithPendingLease(); cancellationDuringSetup();
        System.out.println("PASS " + checks + " rooted input resource checks; no device access");
    }
}
