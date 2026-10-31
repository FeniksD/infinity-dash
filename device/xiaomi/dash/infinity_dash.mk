# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
# Adaptation for Project Infinity X. Hardware configuration comes from dash/cnb.

WITH_GAPPS := true
TARGET_KEEP_STOCK_SOUNDS := true
INFINITY_BUILD_TYPE := UNOFFICIAL
INFINITY_MAINTAINER := feniksd

TARGET_HAS_UDFPS := true
TARGET_DISABLE_LINEAGE_SDK := false
TARGET_DISABLE_FASTBOOTD := false
TARGET_EXCLUDES_AUDIOFX := true
TARGET_SUPPORTS_64_BIT_APPS := true
TARGET_ENABLE_BLUR := true
TARGET_SCREEN_WIDTH := 1280
TARGET_SCREEN_HEIGHT := 2772

# Preserve the upstream Fenrir userspace lock-state workaround.
$(call soong_config_set_bool,fastbootd,bypass_lock_state,true)

$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit_only.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base_telephony.mk)
$(call inherit-product, device/xiaomi/dash/device.mk)
$(call inherit-product, vendor/infinity/config/common_full_phone.mk)

# Match the centered camera cutout in portrait on this device.
PRODUCT_PACKAGES += DashStatusBarHeightOverlay

ifeq ($(WITH_GAPPS),true)
# Google replacements; keep the device camera, launcher and system providers.
PRODUCT_PACKAGES += \
    CalendarGooglePrebuilt \
    Photos \
    GoogleDialer \
    PrebuiltBugle \
    com.google.android.dialer.support

# Google Dialer declares this shared library as required in its manifest.
PRODUCT_COPY_FILES += \
    vendor/pixel/gms/common/proprietary/product/etc/permissions/com.google.android.dialer.support.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/permissions/com.google.android.dialer.support.xml
endif

PRODUCT_DEVICE := dash
PRODUCT_NAME := infinity_dash
PRODUCT_BRAND := POCO
PRODUCT_MODEL := 2602BPC18G
PRODUCT_MANUFACTURER := Xiaomi

PRODUCT_BRAND_FOR_ATTESTATION := $(PRODUCT_BRAND)
PRODUCT_DEVICE_FOR_ATTESTATION := $(PRODUCT_DEVICE)
PRODUCT_MODEL_FOR_ATTESTATION := $(PRODUCT_MODEL)
PRODUCT_NAME_FOR_ATTESTATION := dash_global
PRODUCT_MANUFACTURER_FOR_ATTESTATION := $(PRODUCT_MANUFACTURER)
PRODUCT_GMS_CLIENTID_BASE := android-xiaomi

# Preserve the vendor baseline identity. The framework is Android 17.
PRODUCT_BUILD_PROP_OVERRIDES += \
    BuildDesc="missi-user 16 BP2A.250605.031.A3 16OS3.1.260728.145010743.MTPEGL.S release-keys" \
    BuildFingerprint=POCO/dash_global/dash:16/BP2A.250605.031.A3/OS3.0.303.0.WPLMIXM:user/release-keys \
    DeviceName=dash \
    DeviceProduct=dash_global \
    SystemDevice=dash \
    SystemName=dash_global
