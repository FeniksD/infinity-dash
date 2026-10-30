package org.lineageos.minrefreshrate;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Settings;
import android.util.Log;

public class BootReceiver extends BroadcastReceiver {
    private static final String TAG = "MinRefreshRateCtrl";
    static final float MIN_REFRESH_RATE_HZ = 60.0f;

    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            return;
        }
        applyFloor(context);
    }

    static void applyFloor(Context context) {
        try {
            boolean applied = Settings.System.putFloat(
                    context.getContentResolver(),
                    "min_refresh_rate",
                    MIN_REFRESH_RATE_HZ);
            Log.i(TAG, applied
                    ? "min_refresh_rate enforced at " + MIN_REFRESH_RATE_HZ + "Hz"
                    : "min_refresh_rate write returned false");
        } catch (Exception e) {
            Log.e(TAG, "Failed to set min_refresh_rate", e);
        }
    }
}
