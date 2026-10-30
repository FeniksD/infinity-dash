package org.lineageos.minrefreshrate;

import android.app.Application;
import android.database.ContentObserver;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;

public class MinRefreshRateApplication extends Application {
    private static final String TAG = "MinRefreshRateCtrl";

    @Override
    public void onCreate() {
        super.onCreate();

        getContentResolver().registerContentObserver(
                Settings.System.getUriFor("min_refresh_rate"),
                false,
                new ContentObserver(new Handler(Looper.getMainLooper())) {
                    @Override
                    public void onChange(boolean selfChange) {
                        float current = Settings.System.getFloat(
                                getContentResolver(), "min_refresh_rate", 0f);
                        if (current < BootReceiver.MIN_REFRESH_RATE_HZ) {
                            Log.i(TAG, "min_refresh_rate overridden to " + current
                                    + "Hz externally, re-enforcing floor");
                            BootReceiver.applyFloor(MinRefreshRateApplication.this);
                        }
                    }
                });
    }
}
