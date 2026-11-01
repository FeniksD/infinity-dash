package com.android.server.biometrics.sensors.dash;

/** Owns the probe-proven root container and its passive monitor, independently of Android APIs. */
public final class RootedInputResources {
    public interface Operations {
        Object createRoot() throws Exception;
        Object createMonitor() throws Exception;
        void configure(Object root, Object monitor) throws Exception;
        void disposeMonitor(Object monitor) throws Exception;
        void removeRoot(Object root) throws Exception;
        void releaseRoot(Object root) throws Exception;
    }
    private final Operations operations;
    private final Object root, monitor;
    private boolean closed;
    private RootedInputResources(Operations operations, Object root, Object monitor) {
        this.operations = operations; this.root = root; this.monitor = monitor;
    }
    public static RootedInputResources create(Operations operations) throws Exception {
        Object root = null, monitor = null;
        try {
            root = java.util.Objects.requireNonNull(operations.createRoot());
            monitor = java.util.Objects.requireNonNull(operations.createMonitor());
            operations.configure(root, monitor);
            return new RootedInputResources(operations, root, monitor);
        } catch (Throwable failure) {
            try { cleanup(operations, root, monitor); }
            catch (Throwable closeFailure) {
                if (closeFailure != failure) failure.addSuppressed(closeFailure);
            }
            rethrow(failure);
            throw new AssertionError("unreachable");
        }
    }
    public Object monitor() { return monitor; }
    public void close() throws Exception {
        synchronized (this) { if (closed) return; closed = true; }
        cleanup(operations, root, monitor);
    }
    private static void cleanup(Operations operations, Object root, Object monitor) throws Exception {
        Throwable first = null;
        if (monitor != null) {
            try { operations.disposeMonitor(monitor); }
            catch (Throwable failure) { first = failure; }
        }
        if (root != null) {
            try { operations.removeRoot(root); }
            catch (Throwable failure) { first = combine(first, failure); }
            try { operations.releaseRoot(root); }
            catch (Throwable failure) { first = combine(first, failure); }
        }
        if (first != null) rethrow(first);
    }
    private static Throwable combine(Throwable first, Throwable next) {
        if (first == null) return next;
        if (first != next) first.addSuppressed(next);
        return first;
    }
    private static void rethrow(Throwable failure) throws Exception {
        if (failure instanceof Exception) throw (Exception) failure;
        if (failure instanceof Error) throw (Error) failure;
        throw new AssertionError(failure);
    }
}
