# ColorOS 17 / dash work area

This branch targets **Global (India) CPH2791_17.0.0.102(EX01)**. The full original OTA and payload signatures were verified against the OPPO key already established from the manufacturer-hosted CN release. `global-candidate.json` tracks current Global readiness; older `*-image.json` files and CN evidence are historical references, not Global device-test results.

Global framework hooks are rebuilt with `runtime_rebase.py` from pinned Global inputs. Only our own hash-pinned helper DEX is reused; original CN framework DEXs are not substituted. The Global image has booted in the separate `global17` DSU slot. Full hardware acceptance remains incomplete. The native Infinity installation is retained.

## Current Global observations

[global-runtime-status.json](global-runtime-status.json) records the Global
follow-up evidence separately from the earlier CN bring-up. Boot to an unlocked
launcher is verified. PUBG 120 FPS was owner-confirmed after choosing the in-game
preset; Standoff 2 reached about 120 FPS after a saved per-app display preference.
Those results do not establish complete hardware support, Play certification,
AOD, face unlock or camera compatibility. The original build-time receipts remain
unchanged; their pending flags describe what was known when the artifact was built.

[feature-trials-20261107.json](feature-trials-20261107.json) records the optional
AI experiments. Neither 3D wallpapers, AI live wallpaper generation nor mind maps
has passed end-to-end validation. The two wallpaper flags were reverted; the
Mind Space trial was interrupted before completion. None is enabled by the image
construction recipe. Do not publish these as working features.

The retained CN slot rejected its existing screen credential after switching
between DSU installations. It was not formatted, but its data is not confirmed
recoverable. Both systems use the same GSI Gatekeeper user-ID namespace; internal
TEE replacement was not observed. The owner chose Global and ended CN recovery.
Do not promise independent credential isolation or resume CN boot tests.

The owner currently prohibits phone interaction. Host-side work must not trigger
ADB probes, package changes, DSU switching, reboots or cleanup. The separate ACME
client update incident was reviewed with a one-file baseline change; see
[the host review](../../security/acme-update-20261107.json). No build was resumed
and no new image build is implied by these source updates.

The AOD source follow-up is in [aod-global-analysis.json](aod-global-analysis.json).
Seven selected Global/CN classes were compared: 148 method bodies match after
normalization, and two differ in brightness conversion. The kernel reference also
shows that cached doze-brightness values can update after a failed panel command.
A matching getter is therefore insufficient proof of visible AOD or successful
restoration. The bounded Xiaomi layer/power protocol test remains unperformed;
no AOD patch is enabled in the candidate.

The optional MIUI Camera bundle remains unverified on Global. The retained CN
launch trace opens the Xiaomi camera HAL, but disconnects without a usable
preview, and app log flow control dropped part of the failure trace. The camera
also reads the OPPO `Build.DEVICE` for its feature-profile lookup. The `Qcom` MIVI
implementation name is not by itself proof of wrong CPU detection.
[camera-diagnostics.json](camera-diagnostics.json) records the traced methods and
the next isolated checks. The audited canonical Global tree does not include this
optional APK; that inventory does not describe later data-app installs. No
framework/property or camera-permission workaround is enabled by this review.

## Standoff 2 refresh-rate default

The Global profile requires the `game_refresh_required` compatibility patch.
The existing `patch` stage adds one hash-pinned entry for
`com.axlebolt.standoff2` to `/my_product/etc/refresh_rate_config.xml`:
`rateId="3-1-2-3" disableViewOverride="true"`. Automatic and 120 Hz modes
allow 120 Hz; explicit 60/90 Hz choices remain 60/90 Hz. Other packages and
the thermal policy are unchanged. A build is rejected until the required
profile has been applied. Existing published images are not retroactively
changed.

On the owner's running Global, Standoff 2 1.1.0 selected a window override of
60 Hz despite its in-game 120 FPS setting. A native per-app preference for
120 Hz restored approximately 120 FPS in training, including after an app
restart, with the system-wide mode returned to Automatic. The validated live
workaround was:

```sh
adb shell dumpsys oplusscreenmode simulate_setUserrefreshrate com.axlebolt.standoff2 0 3
adb shell dumpsys oplusscreenmode simulate_setUserrefreshrate com.axlebolt.standoff2 3 3
```

These integers are ColorOS mode IDs, not arbitrary FPS values. To remove only
this user preference:

```sh
adb shell dumpsys oplusscreenmode simulate_removeUserrefreshrate com.axlebolt.standoff2
```

The image XML profile still needs a fresh-data boot/game test before release;
the live per-app test does not substitute for that validation. No general
claim is made about unlocking an engine's own FPS cap in other games.


## Historical CN bring-up

The following records describe the earlier **CN** build and its experiments. They
are retained as provenance and must not be read as Global validation. The current
Global artifact is identified in [global-image.json](global-image.json).

The final CN artifact was `ColorOS17-dash-FeniksD-20261104-sensor1.img`.
[sensor-product-image.json](sensor-product-image.json) records its checked
product identity update and permanent DSU delta.
[radio-image.json](radio-image.json) records the verified radio fix and its
permanent DSU installation. The earlier branding-only artifact is recorded below.
[branding-image.json](branding-image.json) records its complete filesystem
verification and the separately verified delta installed into the owner's
inactive DSU image. The page was checked live with the port entry directly after
the device-name/storage card and the original PLG110 hardware card retained.
The same layout was checked after a cold boot of the permanently updated DSU;
the APK checksum matches and no temporary APK bind mount remains.
The earlier `runtime-image.json` remains the historical pre-branding record.

Port and device adaptation: **FeniksD**. Updates and releases:
[FeniksD Lab | dash](https://t.me/feniksd_dash). Contact:
[@FeniksD2](https://t.me/FeniksD2). The bilingual attribution text is kept in
[PORT_INFO.txt](PORT_INFO.txt). ColorOS is developed by OPPO; original Xiaomi,
xiaomi-mt6991 and Project Infinity X contributions retain their authorship.

`branding_overlay/` contains the source resources and the signed, code-free RRO
for the "About device" port-information entry. It opens
`https://t.me/feniksd_dash` and includes Russian and English labels. The donor
Settings APK stays unchanged. `branding.py` reconstructs its existing preference
XML from the pinned donor's AAPT2 resource dump and inserts the entry at order
176, between the storage card (175) and hardware card (350); the build
was checked to preserve every original preference node and attribute.
`branding-bundle.json` pins the exact Settings APK and overlay hashes.
Apply this stage before building an image with the current profile:

```sh
python3 -B -m ports.coloros17.candidate --base /srv/infinity/coloros17 --stage branding
```

This adds only `/system/etc/feniksd-port-info.txt` and
`/system/system_ext/overlay/FeniksDAboutOverlay.apk`. Signing keys are held outside
the repository. This description of the build inputs is not a device-test result.

The included 21 KiB APK is a pinned prebuilt with no DEX code or launcher icon.
To rebuild the resource overlay against the exact donor APK:

```sh
python3 -B -m ports.coloros17.branding \
  --settings-apk /path/to/donor/Settings.apk \
  --framework-apk /path/to/donor/framework-res.apk \
  --aapt2 /path/to/aapt2 \
  --output /path/to/new/FeniksDAboutOverlay-unsigned.apk
```

Sign that output with the maintainer's separate overlay certificate before
staging it. A different signing key or changed resources require a new reviewed
APK hash in `branding-bundle.json`. The builder refuses a different Settings
APK and checks that recompilation preserves all original preference nodes and
attributes. The original Settings APK is neither modified nor re-signed.

The overlay is linked with `--shared-lib` so its local resource IDs do not alias
the target Settings package (0x7f). The first version shared that package ID and
caused a blank About page: Android relocated donor integer/string references
into the overlay namespace. A device-side resource probe reproduced the bad
integer lookup; the corrected overlay resolves the original donor resources
and the complete About page renders again. The Russian and default English
labels are both retained. DPI is not changed by this overlay.

The owner-reported remaining issues and next checks are recorded in
[bugs-20261104.json](bugs-20261104.json). The native OPPO camera app also currently
throws a missing `CameraAdapterUtils` class error; restoring the original About
layout does not fix that separate app failure.

Status: ColorOS 17 boots through DSU on dash. Fingerprint enrollment, animation, repeated authentication and wake-to-unlock are owner-tested. Restoring the retained hardware product name enables LTE; the owner confirmed mobile data and outgoing calls. The permanent runtime delta has passed a cold boot; the owner confirmed fingerprint enrollment and repeated unlock after a clean userdata reset. DSU userdata is now 32 GiB, with about 25.6 GiB available and no low/full-storage flag. Incoming calls and SMS are being retested. Face Unlock has no compatible provider yet. The Infinity MIUI Camera bundle is installed but still requires runtime testing. This remains a laboratory port.

The first raw EXT4 candidate and its gzip were built and verified; its regenerable gzip cache was later removed while preserving the raw image. [lab-image.json](lab-image.json) records their sizes, SHA-256 hashes and the limits of offline validation. The gzip is 6,866,550,221 bytes; it expands to 15,169,392,640 bytes. Construction verified 14,480 inode metadata records and all 11,219 regular-file contents. Successful construction does not establish that the image boots on `dash`.

Donor: OPPO Find X9 Pro CN, `PLG110_17.0.0.105(CN01)`, Android17/SDK37. This is the same device family named by the earlier unofficial ColorOS16 dash port. `donor.json` records public provenance; expiring URL query signatures remain in private task cache.

The manufacturer's OTA is 9,592,101,891 bytes. Its payload is marked partial, but the selected system/system_ext/product/my_* images have only replacement/zero operations and no source-image dependencies. They are suitable for image extraction without a previous OTA; the package must never be flashed directly to a POCO.

The preflight is read-only:

```sh
python3 -B ports/coloros17/preflight.py \
  --metadata ports/coloros17/donor-metadata.json \
  --payload-summary ports/coloros17/payload-summary.json
```

This validates the extraction recipe and the reviewed construction profile. It does not authorize a phone flash or establish bootability.

`candidate.py` provides the host-only `merge`, `patch` and `build` stages. Run it as an unprivileged build account, with the verified input reports and unpacked trees under the selected base directory:

```sh
python3 -B -m ports.coloros17.candidate --base /srv/infinity/coloros17 --stage merge
python3 -B -m ports.coloros17.candidate --base /srv/infinity/coloros17 --stage patch
python3 -B -m ports.coloros17.candidate --base /srv/infinity/coloros17 --stage build
```

The tested runtime bundle and optional camera payload are separate verified stages:

```sh
python3 -B -m ports.coloros17.candidate --base /srv/infinity/coloros17 --stage runtime
python3 -B -m ports.coloros17.camera_bundle --base /srv/infinity/coloros17 \
  --bundle-dir /srv/infinity/coloros17/inputs/camera
python3 -B -m ports.coloros17.candidate --base /srv/infinity/coloros17 --stage build \
  --output /srv/infinity/coloros17/output/ColorOS17-dash-runtime.img
```

`inputs/runtime` must contain the exact two JARs pinned by `runtime-bundle.json`; the camera directory must contain the unchanged `payload/` tree pinned by `camera-bundle.json`. Runtime staging includes fingerprint properties/features, narrow CIL rules with an updated policy stamp, the retained vendor product name, and the combined haptic/charging JAR. Build verification requires the runtime stage by default. The new output path preserves the baseline image. Successful source staging is not a cold-boot or camera compatibility test.

The stages retain a recovery journal and atomically publish the metadata/content pair. Files are moved on the same filesystem, preserving the original raw images without duplicating the full unpacked tree. Six compatibility fixes are included: remove two conflicting powercap genfs rules, restore the loop-control label before APEX bootstrap, add optional declarations for the retained dash HALs, install the standard monolithic-GSI `skip_mount.cfg` for `/system_ext` and `/product`, grant SurfaceFlinger the existing vendor composer-client role, and install the power-key telemetry workaround described below.

The output is an **unsigned, editable EXT4 laboratory image**, not an OPPO-signed update or a production ROM. The original `/my_reserve` directory has no label; a temporary build label is removed and verified afterward. SELinux policies compile in the mode used by the unmodified donor init and contain no permissive domains, but the stricter build-time neverallow audit still reports retained-vendor conflicts. Full APEX/kernel VINTF checks and device tests remain outstanding.

Pinned toolkit: [MysticGSI](https://github.com/MysticGSI/mysticgsi/tree/b906057b9909d9ec3272feb9c53306f7bd4912f0). There is no `37/coloros` profile at this commit. Its stock pipeline also performs broad removals, disables security properties and can install permissive-SELinux helpers, so this port will use explicit, reviewed transformations instead. Original authorship must be preserved.

The first candidate targets DSU, preserving the working Infinity base. Later iterations should modify only the inactive DSU copy and corresponding canonical host files, with rollback, verified metadata and an explicit AVB policy.

For the laboratory transfer, `serve_artifact.py` serves one hash-verified file with a bearer token and pinned TLS. The runtime systemd unit uses privileged lifecycle hooks to add and remove one source-restricted firewall rule while keeping the original guard baseline intact. Do not install this example as a permanent public download service. Its optional `--tcp-congestion bbr` selects BBR only for the transfer socket; it requires an available, allowed kernel implementation and does not change the global TCP default.

Design and current task checklist: `docs/superpowers/specs/2026-11-01-coloros17-dsu-design.md` and `docs/superpowers/plans/2026-11-01-coloros17-dsu.md`.

The existing gzip predates `skip_mount.cfg`. Its hashes identify the preserved base image, not the patched phone variant; see `post_build_dsu_patch` in `lab-image.json`. No replacement archive has been built.

Runtime findings from 2026-11-01:

- Physical power-key events were delayed by about 5.02 seconds inside the donor's `saupwkProcessKey`, waiting for absent `IOplusProject/default`. Setting `persist.sys.saupwk_test=true` bypasses this optional telemetry path; the owner confirmed the button became responsive. The recipe now installs `system_ext/etc/init/dash-power-key.rc`, which reapplies this setting after persisted properties load. The permanent init integration has been checked after a cold boot, including its effective property. The separate composer-client policy change reduced measured display-power transitions from about 2.4 seconds to 0.2–0.3 seconds.
- Both SIMs work in the retained Infinity base. Restoring `ro.product.vendor.name=dash_global` fixed the modem product-identity exchange and enabled LTE, mobile data and outgoing calls in ColorOS. The retained `ro.vendor.imeisv=05` baseline alone did not fix radio service. Incoming calls and SMS still need retesting after removing the userdata-capacity bottleneck. No modem or NV partition was changed.
- The charging warning has a traced compatibility cause: absent `vendor.oplus.hardware.charger.ICharger/default` returns `-1`, BatteryService publishes that as `notifycode`, and SystemUI treats bit 1 as overvoltage. The observed USB input was about 4.82 V. This does not establish all future charging conditions are safe. A fix must represent unavailable diagnostics separately and preserve real fault notifications and kernel protections; no charging protection has been disabled.
- `patches/0003-charger-invalid-diagnostic.patch` now retains the last valid fault mask when a diagnostic sample is negative. The actual ART harness passed 21 samples; the owner confirmed the false Voltage Error disappeared in the live test. The combined JAR retains the haptics patch. `charger-diagnostics.json` records the exact hashes and limits. The runtime bundle now installs this combined JAR; its standalone source rebuild scripts remain hash-pinned. The permanent combined JAR hash has been verified after a cold boot; runtime charging observations remain separate from that integrity check.
- The owner confirmed a direct standard-HAL pulse at full amplitude, and ordinary interface feedback after the optional source patch in `patches/0002-dash-haptic-aosp-fallback.patch`. The owner also confirmed that feedback intensity follows the volume slider. The donor's proprietary Oplus extension remains absent. `haptic-fallback.json` pins the source/result hashes and verification; `tests/device/ColorOsHapticFallbackProbe.java` checks the converter against actual Android classes. The `runtime` stage now installs the verified combined JAR; rebuilding its source remains a separate pinned step. The verified runtime delta now installs the combined JAR permanently in the DSU system image, with `persist.sys.dash.haptic_fallback=true` set by init.
- The O-Haptics video preview calls RichTap pattern playback. That path is separate from OplusPrebakedSegment and is not covered by the basic feedback patch. The preview currently logs unavailable Oplus vibrator extension errors; do not claim that proprietary texture/style playback works because ordinary button feedback works.

DSU userdata capacity

Use at least **32 GiB** for this donor during DSU testing. The previous 8 GiB userdata filled with application data, ART cache and downloaded AI assets; this caused storage errors and an SMS-storage-unavailable condition. A working fingerprint enrollment also failed to persist when storage was full.

The owner authorized resetting only ColorOS userdata. It was recreated as a 34,359,738,368-byte `userdata_gsi` through the existing ImageService API, retaining the installed system image and the native Infinity installation. Full mapped `system_gsi` hashes matched before and after; control markers and the existing metadata-key pointer stayed unchanged. This was a clean reset, not an in-place F2FS expansion. The preserve-data expansion prototype was not deployed.

The installed delta retains the old 15,169,392,640-byte system filesystem geometry and therefore has a different raw hash from the separately rebuilt full image. `runtime-image.json` records both artifacts and the cold-boot evidence.

## Optional OPPO radio service on dash

`radio_registration.py` adds a `SecurityException` handler to the existing
`RemoteException` failure path around OPPO radio service notification
registration. The Xiaomi base has no `vendor.oplus.hardware.radio.IRadioStable`
service. Before this change the exception aborted `OplusTelephonyFactoryImpl`
construction; both SIM SMS handlers stayed in `StartupState`. With the patch
both handlers receive `EVENT_START_ACCEPTING_SMS`. The owner confirmed incoming
SMS and calls during the live test. SELinux remains enforcing.

Build the pinned JAR without modifying the canonical input, then stage it:

```sh
python3 -B ports/coloros17/radio/build_registration.py \
  /path/to/original/oplus-telephony-common.jar \
  /path/to/new/oplus-telephony-common.jar \
  ports/coloros17/radio_registration.py /srv/infinity/android
# Copy the verified output to BASE/inputs/radio/oplus-telephony-common.jar.
python3 -B -m ports.coloros17.candidate --base BASE --stage radio
```

The active profile requires this stage before a future image build.
`radio-registration.json` pins both source and result; `radio/validation.json`
records the ART regression and device-test limits. The regression executes the
actual extracted method body with controlled service responses, including an
unrelated exception that must remain visible.

## Sensor product identity

The retained dash HWC checks `ro.product.product.name` against a device
allowlist containing `dash`. The shared donor product name `ossi` leaves
`mNeedRGBNotifier` disabled, so the CIT light-sensor service is never told to
request display frames for under-display light compensation.

The `sensor` stage changes only that property to `dash_global`. The global
model and the original PLG110 About-device presentation remain unchanged.
The stage hash-pins both the original product build.prop and the result,
preserves its metadata, and is required by the current build profile.
After permanent installation and a cold boot, the frame notifications and
calibrated lux resumed. The owner confirmed that automatic brightness responds
when the sensor is covered and then exposed to brighter light. AOD behavior
remains a separate, unresolved test.

```sh
python3 -B -m ports.coloros17.candidate --base BASE --stage sensor
```
