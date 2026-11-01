package com.android.server.biometrics.sensors.dash;

/** Owns only an active generation's input resources; normal create/dispose run on input looper. */
public final class PassiveInputLease {
    public interface Scheduler { void execute(Runnable task); }
    public interface Factory {
        Object createMonitor(long generation) throws Exception;
        Object createReceiver(Object monitor, long generation) throws Exception;
        void disposeReceiver(Object receiver) throws Exception;
        void disposeMonitor(Object monitor) throws Exception;
    }
    public interface Observer {
        void ready(long generation);
        void failed(long generation, Throwable failure);
    }
    private static final class Resources {
        final long generation;
        final Object monitor, receiver;
        Resources(long generation, Object monitor, Object receiver) {
            this.generation = generation; this.monitor = monitor; this.receiver = receiver;
        }
    }
    private final Scheduler scheduler;
    private final Factory factory;
    private final Observer observer;
    private long active = -1;
    private Resources owned;

    public PassiveInputLease(Scheduler scheduler, Factory factory, Observer observer) {
        this.scheduler = scheduler; this.factory = factory; this.observer = observer;
    }
    public void open(long generation) {
        if (generation < 0) throw new IllegalArgumentException("negative generation");
        synchronized (this) {
            if (active == generation) return;
            active = generation;
        }
        try { scheduler.execute(() -> create(generation)); }
        catch (RuntimeException failure) {
            boolean report;
            Resources abandoned;
            synchronized (this) {
                report = active == generation;
                abandoned = report ? owned : null;
                if (report) { active = -1; owned = null; }
            }
            dispose(abandoned);
            if (report) failed(generation, failure);
        }
    }
    public void close() {
        long generation;
        Resources retired;
        synchronized (this) {
            generation = active;
            active = -1;
            retired = owned;
            owned = null;
        }
        if (generation < 0 && retired == null) return;
        try { scheduler.execute(() -> dispose(retired)); }
        catch (RuntimeException failure) {
            // If the input looper has terminated, best-effort native cleanup still releases channel.
            dispose(retired);
            failed(retired == null ? generation : retired.generation, failure);
        }
    }
    public synchronized boolean canForward(long generation) {
        return active == generation && owned != null && owned.generation == generation;
    }
    private synchronized boolean active(long generation) { return active == generation; }
    private void create(long generation) {
        if (!active(generation)) return;
        Resources previous;
        synchronized (this) { previous = owned; owned = null; }
        dispose(previous);
        Object monitor = null, receiver = null;
        try {
            monitor = factory.createMonitor(generation);
            if (!active(generation)) { dispose(new Resources(generation, monitor, null)); return; }
            receiver = factory.createReceiver(monitor, generation);
            boolean adopted;
            synchronized (this) {
                adopted = active == generation;
                if (adopted) {
                    owned = new Resources(generation, monitor, receiver);
                }
            }
            if (!adopted) {
                dispose(new Resources(generation, monitor, receiver)); return;
            }
            if (canForward(generation)) {
                try { observer.ready(generation); } catch (RuntimeException ignored) { }
            }
        } catch (Exception | LinkageError failure) {
            dispose(new Resources(generation, monitor, receiver));
            boolean report;
            synchronized (this) { report = active == generation; if (report) active = -1; }
            if (report) failed(generation, failure);
        }
    }
    private void dispose(Resources resources) {
        if (resources == null) return;
        Throwable error = null;
        if (resources.receiver != null) {
            try { factory.disposeReceiver(resources.receiver); }
            catch (Exception | LinkageError failure) { error = failure; }
        }
        if (resources.monitor != null) {
            try { factory.disposeMonitor(resources.monitor); }
            catch (Exception | LinkageError failure) { if (error == null) error = failure; }
        }
        if (error != null) failed(resources.generation, error);
    }
    private void failed(long generation, Throwable failure) {
        try { observer.failed(generation, failure); } catch (RuntimeException ignored) { }
    }
}
