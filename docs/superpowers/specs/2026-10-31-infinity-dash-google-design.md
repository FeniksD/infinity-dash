# Infinity X dash: Google services and application replacements

## Requested result

Provide Google Play services and Play Store on the working Infinity X 4.1 / Android 17 build for POCO X8 Pro Max (`dash`). Gboard is required. Replace the corresponding bundled user applications with Google alternatives, while retaining the working MIUI Camera, Infinity launcher, hardware integration, encryption and recovery path.

The user requested implementation, said to continue, and explicitly confirmed this application set. Phone installation requires a stable connection and an explicit decision if another data wipe becomes necessary.

## Application selection

Use Infinity's existing `WITH_GAPPS` integration and its already pinned `vendor/pixel/gms` tree at `4d2eb0026075de0f6f4a95bc5818dacdd1c0e852`. Do not download a different GApps distribution or update unrelated repositories.

The default Google integration supplies Play Store, Play services, Google Services Framework, setup/synchronization support, Gboard, Google Contacts, Google Clock, Google Calculator, Chrome and Google WebView.

Additionally select these existing modules:

- `CalendarGooglePrebuilt`: Google Calendar.
- `Photos`: Google Photos.
- `GoogleDialer`: Google Phone.
- `PrebuiltBugle`: Google Messages.
- `com.google.android.dialer.support`: required shared library for the pinned Google Phone APK.

Install the existing `com.google.android.dialer.support.xml` into the product permissions directory so PackageManager registers that library and the supported-dialer feature. Existing Google privileged-permission allowlists must cover the selected applications. If native build validation requires a matching Soong `uses_libs` declaration, add a narrowly scoped pinned GMS patch; never relax global library or permission checks.

Use the Google modules' declared overrides to remove LatinIME, Contacts, DeskClock, ExactCalculator, Jelly, Glimpse and AOSP Dialer/Messaging from the resulting package set. Do not remove ContactsProvider, CalendarProvider, DocumentsUI, Telecom, IMS, eSIM components, permission controllers, XiaomiParts, MIUI Camera or Launcher3QuickStep. Google Calendar is an addition where no standalone calendar was bundled. Do not add unrelated optional Google applications.

## Later user requirements: sound and status-bar preservation

The user explicitly asked not to change notification/ringtone/alarm sounds in the build. GApps currently causes `vendor/extras/prebuilts.mk` to install and select different defaults. Add a device opt-out, `TARGET_KEEP_STOCK_SOUNDS := true`, around only that extras sound block; preserve upstream behavior when the flag is absent. Leave the usual Infinity/AOSP audio content and fallback defaults intact. The currently selected notification is OnTheHunt; changing Google applications must not silently choose a replacement tone.

The user also requested camera-aligned status-bar content and Dynamic Island, reporting different vertical placement on the lock screen and unlocked screen. Runtime measurements show 504 dpi, a cutout center at y=85 px, a 132 px/42 dp regular status bar, and a separately overridden 48 dp portrait resource from `SBHeightOverlay`. Provide a product-partition device RRO replacing `SBHeightOverlay`, retaining its package identity and priority while making portrait height and portrait default height 54 dp (170 px at default density). Keep the existing 28 dp landscape resource and leave the default resource outside portrait to the existing device overlay. Do not alter cutout geometry, DPI, fonts, icons or hardware settings.

Runtime acceptance must confirm both lock-screen and unlocked alignment; the numeric fit alone is not proof of visual correctness. A temporary APK update was rejected because the installed overlay is static, so no successful trial overlay was installed. The earlier temporary padding setting was verified restored to its original null value.

## Scope and safeguards

- Preserve Android/device/kernel/vendor revisions, current hardware tuning, kernel/DTB/module cohort, SELinux enforcement, encryption and device identity.
- Do not add root, change bootloader state, flash LK/preloader/radio/NV, change charging controls or import private attestation keys/keyboxes.
- Play Store certification and Play Integrity are separate runtime checks, not promises. Report observed Basic/Device/Strong verdicts and app compatibility after installation; GApps inclusion alone does not establish certification.
- Existing Dolby and XiaomiParts permission findings remain tracked separately. Do not silently bundle unrelated fixes into this application migration.
- Keep the verified Vanilla package, raw images, original rollback backup and source baselines available.

## Preparation and build

Work on an isolated feature branch. Update the tracked device configuration and reproducible upstream patch together. The effective GApps configuration selects EROFS for the read-only Android partitions through the existing device rule; userdata remains F2FS.

Validate the old test baseline, selected package dependencies, permission/library declarations and patch reproduction. Promote source changes through the existing root/local integrity workflow, preserving the previous baselines and build artifacts. Reuse the current output/cache, run the guarded native build, and verify actual output package selection and the existing ZIP/payload/AVB/VINTF/image checks. Check super capacity from produced image sizes, not source-directory size.

## Installation and acceptance

Do not assume that a Vanilla-to-GApps transition after first boot is a supported data-preserving update. Determine the migration procedure before phone writes. Back up new user data if present; obtain specific approval before any new wipe. Never sideload the complete OTA containing low-level firmware. Continue the reviewed selective installation procedure with a coherent final image set and verified rollback.

Acceptance checks: Android boots; Google account sign-in (performed by the user), Play Store installs/updates an application, Play services remain running, Gboard is available/default, intended Google applications open and receive the appropriate roles, duplicate user apps are absent, contacts/SMS/providers still work, and camera/telephony/eSIM/lighting are not regressed. Record actual Play certification/Integrity separately. Do not claim unperformed checks passed.

## Later requested correction: charge-time estimate

The user explicitly requested that the known incorrect charging-time estimate be corrected before the new installation. Recorded dash measurements reproduce the driver's multi-day estimates exactly: its time-to-full calculation uses the stale MTK gauge average current, while instantaneous current and charge counter come from the external BMS. Do not change the kernel, charging current, thermal protection or capacity calibration to address this presentation bug.

Use the existing AIDL Health `UpdateHealthInfo` extension point to mark hardware time-to-full as unsupported (-1), enabled only for dash by the `mediatek_health.ignore_time_to_full` Soong setting. With the setting absent, all hardware estimates must pass through unchanged. Other HealthInfo fields remain untouched. BatteryStats then uses its existing charge-level history estimator. This does not promise an immediate or perfectly accurate estimate; a fresh session needs charge-level observations and tapering can change the prediction. Runtime acceptance must confirm both the HAL value and framework/UI estimate after charging progresses.
