package com.android.server.biometrics.sensors.dash;

import java.util.ArrayList;
import java.util.List;

/** Pure resource-state tests. No Android, input events, or biometric operations. */
public final class PassiveInputLeaseTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    private static final class Queue implements PassiveInputLease.Scheduler {
        final List<Runnable> tasks = new ArrayList<>();
        boolean reject;
        public void execute(Runnable task) {
            if (reject) throw new IllegalStateException("executor stopped");
            tasks.add(task);
        }
        void all() { while (!tasks.isEmpty()) tasks.remove(0).run(); }
        void last() { tasks.remove(tasks.size() - 1).run(); }
    }
    private static final class Factory implements PassiveInputLease.Factory {
        final List<String> calls = new ArrayList<>();
        PassiveInputLease lease;
        boolean failMonitor, failReceiver, failDisposeReceiver, closeDuringMonitor, closeDuringReceiver;
        boolean replaceAndFail;
        public Object createMonitor(long g) throws Exception {
            calls.add("create-m" + g);
            if (closeDuringMonitor) lease.close();
            if (replaceAndFail) { replaceAndFail = false; lease.open(2); throw new Exception("stale"); }
            if (failMonitor) throw new Exception("monitor failed");
            return "m" + g;
        }
        public Object createReceiver(Object monitor, long g) throws Exception {
            calls.add("create-r" + g);
            if (closeDuringReceiver) lease.close();
            if (failReceiver) throw new Exception("receiver failed");
            return "r" + g;
        }
        public void disposeReceiver(Object receiver) throws Exception {
            calls.add("close-" + receiver);
            if (failDisposeReceiver) throw new Exception("receiver close failed");
        }
        public void disposeMonitor(Object monitor) { calls.add("close-" + monitor); }
    }
    private static final class Observer implements PassiveInputLease.Observer {
        final List<Long> ready = new ArrayList<>(), failed = new ArrayList<>();
        public void ready(long g) { ready.add(g); }
        public void failed(long g, Throwable failure) { failed.add(g); }
    }
    private static final class Fixture {
        final Queue queue = new Queue();
        final Factory factory = new Factory();
        final Observer observer = new Observer();
        final PassiveInputLease lease = new PassiveInputLease(queue, factory, observer);
        Fixture() { factory.lease = lease; }
    }
    private static void normalAndEarlyClose() {
        Fixture f = new Fixture(); f.lease.open(1); f.queue.all();
        check(f.lease.canForward(1) && f.observer.ready.equals(List.of(1L)), "created generation ready");
        f.lease.close();
        check(!f.lease.canForward(1), "hide disables forwarding before async resource disposal");
        f.queue.all();
        check(f.factory.calls.equals(List.of("create-m1", "create-r1", "close-r1", "close-m1")),
                "receiver disposed before monitor exactly once");
        f.lease.close(); f.queue.all();
        check(f.factory.calls.size() == 4, "repeated close is idempotent");
        Fixture early = new Fixture(); early.lease.open(1); early.lease.close(); early.queue.all();
        check(early.factory.calls.isEmpty(), "cancel before creation leaves no input resources");
        Fixture pending = new Fixture(); pending.lease.open(1); pending.queue.all();
        pending.lease.open(2); pending.lease.close(); pending.queue.all();
        check(pending.factory.calls.equals(List.of("create-m1", "create-r1", "close-r1", "close-m1")),
                "cancelling pending replacement retires previously owned resources");
    }
    private static void staleGenerationsCannotCloseReplacement() {
        Fixture f = new Fixture(); f.lease.open(1); f.queue.all();
        f.lease.close(); f.lease.open(2);
        f.queue.last(); // Intentionally make the new create run before the old queued close.
        f.queue.all();
        check(f.lease.canForward(2) && !f.lease.canForward(1), "only replacement generation forwards");
        check(!f.factory.calls.contains("close-r2"), "old close cannot dispose new receiver");
        f.lease.close(); f.queue.all();
        check(f.factory.calls.subList(f.factory.calls.size()-2, f.factory.calls.size())
                .equals(List.of("close-r2", "close-m2")), "replacement still disposes normally");
    }
    private static void partialCreationsAreCleaned() {
        Fixture f = new Fixture(); f.factory.closeDuringMonitor = true;
        f.lease.open(1); f.queue.all();
        check(f.factory.calls.equals(List.of("create-m1", "close-m1")), "cancellation after monitor closes partial resource");
        Fixture r = new Fixture(); r.factory.closeDuringReceiver = true;
        r.lease.open(1); r.queue.all();
        check(r.factory.calls.equals(List.of("create-m1", "create-r1", "close-r1", "close-m1")),
                "cancellation after receiver closes both partial resources");
    }
    private static void failuresRemainClosed() {
        Fixture m = new Fixture(); m.factory.failMonitor = true; m.lease.open(1); m.queue.all();
        check(!m.lease.canForward(1) && m.observer.failed.equals(List.of(1L)), "monitor failure disables generation");
        Fixture r = new Fixture(); r.factory.failReceiver = true; r.lease.open(1); r.queue.all();
        check(r.factory.calls.equals(List.of("create-m1", "create-r1", "close-m1")), "receiver failure closes monitor");
        check(!r.lease.canForward(1), "receiver failure never forwards");
        Fixture c = new Fixture(); c.factory.failDisposeReceiver = true; c.lease.open(1); c.queue.all();
        c.lease.close(); c.queue.all();
        check(c.factory.calls.contains("close-m1"), "monitor still closes if receiver dispose throws");
        Fixture stale = new Fixture(); stale.factory.replaceAndFail = true;
        stale.lease.open(1); stale.queue.all();
        check(stale.lease.canForward(2) && stale.observer.failed.isEmpty(), "stale creation failure cannot invalidate replacement");
        Fixture q = new Fixture(); q.queue.reject = true; q.lease.open(1);
        check(!q.lease.canForward(1) && q.observer.failed.equals(List.of(1L)), "rejected setup is fail closed");
        Fixture close = new Fixture(); close.lease.open(1); close.queue.all(); close.queue.reject = true; close.lease.close();
        check(!close.lease.canForward(1) && close.factory.calls.contains("close-m1"),
                "rejected cleanup still attempts to release owned monitor");
        Fixture replacement = new Fixture(); replacement.lease.open(1); replacement.queue.all();
        replacement.queue.reject = true; replacement.lease.open(2);
        check(!replacement.lease.canForward(2) && replacement.factory.calls.contains("close-m1"),
                "rejected replacement releases previous disabled monitor");
    }
    public static void main(String[] args) {
        normalAndEarlyClose(); staleGenerationsCannotCloseReplacement(); partialCreationsAreCleaned(); failuresRemainClosed();
        System.out.println("PASS " + checks + " input resource ownership checks; no device access");
    }
}
