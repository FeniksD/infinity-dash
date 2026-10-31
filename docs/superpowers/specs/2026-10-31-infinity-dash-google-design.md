# Infinity X dash: Google services and application replacements

## Requested result

Provide Google Play services and Play Store on the working Infinity X 4.1 / Android 17 build for POCO X8 Pro Max (`dash`). Gboard is required. Replace the corresponding bundled user applications with Google alternatives, while retaining the working MIUI Camera, Infinity launcher, hardware integration, encryption and recovery path.

The user requested implementation and then said to continue. A concise application-set confirmation and a request for a working ADB connection are pending in chat. Preparation and validation can proceed; phone installation requires a connection and an explicit decision if another data wipe becomes necessary.

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

## Scope and safeguards

- Preserve Android/device/kernel/vendor revisions, current hardware tuning, kernel/DTB/module cohort, SELinux enforcement, encryption and device identity.
- Do not add root, change bootloader state, flash LK/preloader/radio/NV, change charging controls or import private attestation keys/keyboxes.
- Play Store certification and Play Integrity are separate runtime checks, not promises. Report observed Basic/Device/Strong verdicts and app compatibility after installation; GApps inclusion alone does not establish certification.
- Existing Dolby, charge-time-estimate and XiaomiParts permission findings remain tracked separately. Do not silently bundle unrelated fixes into this application migration.
- Keep the verified Vanilla package, raw images, original rollback backup and source baselines available.

## Preparation and build

Work on an isolated feature branch. Update the tracked device configuration and reproducible upstream patch together. The effective GApps configuration selects EROFS for the read-only Android partitions through the existing device rule; userdata remains F2FS.

Validate the old test baseline, selected package dependencies, permission/library declarations and patch reproduction. Promote source changes through the existing root/local integrity workflow, preserving the previous baselines and build artifacts. Reuse the current output/cache, run the guarded native build, and verify actual output package selection and the existing ZIP/payload/AVB/VINTF/image checks. Check super capacity from produced image sizes, not source-directory size.

## Installation and acceptance

Do not assume that a Vanilla-to-GApps transition after first boot is a supported data-preserving update. Determine the migration procedure before phone writes. Back up new user data if present; obtain specific approval before any new wipe. Never sideload the complete OTA containing low-level firmware. Continue the reviewed selective installation procedure with a coherent final image set and verified rollback.

Acceptance checks: Android boots; Google account sign-in (performed by the user), Play Store installs/updates an application, Play services remain running, Gboard is available/default, intended Google applications open and receive the appropriate roles, duplicate user apps are absent, contacts/SMS/providers still work, and camera/telephony/eSIM/lighting are not regressed. Record actual Play certification/Integrity separately. Do not claim unperformed checks passed.
