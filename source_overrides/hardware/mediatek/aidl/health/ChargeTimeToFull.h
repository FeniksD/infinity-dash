/*
 * Copyright (C) 2026 FeniksD
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <cstdint>

namespace mediatek::health {

inline constexpr int64_t ChargeTimeToFullSeconds(int64_t reported_seconds) {
#if defined(MEDIATEK_HEALTH_IGNORE_TIME_TO_FULL) && MEDIATEK_HEALTH_IGNORE_TIME_TO_FULL
    // dash's MTK gauge estimates time from a stale current_avg while current_now
    // comes from the external BMS. Let BatteryStats use charge-level history.
    (void)reported_seconds;
    return -1;  // HealthInfo::BATTERY_CHARGE_TIME_TO_FULL_NOW_SECONDS_UNSUPPORTED
#else
    return reported_seconds;
#endif
}

}  // namespace mediatek::health
