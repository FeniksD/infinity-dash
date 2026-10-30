# SPDX-FileCopyrightText: 2017-2024 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

# build-manifest.xml
# The sealed build exports its manifest without writing Git metadata.
BUILD_BROKEN_SRC_DIR_RW_ALLOWLIST :=

# Recovery
BOARD_USES_FULL_RECOVERY_IMAGE ?= true

include vendor/infinity/config/BoardConfigKernel.mk

ifeq ($(BOARD_USES_QCOM_HARDWARE),true)
    include hardware/qcom-caf/common/BoardConfigQcom.mk
endif

include vendor/infinity/config/BoardConfigSoong.mk
