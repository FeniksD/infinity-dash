# ColorOS 17 / dash work area

Status: the official donor is booting to the ColorOS 17 desktop through DSU on dash. The owner reports working applications, Wi-Fi, 120 Hz animations, screen recording and USB file transfer. An experimental runtime patch restores ordinary interface vibration with variable strength and duration. Cellular service, fingerprint enrollment and face unlock remain broken; the synchronized O-Haptics demonstration is not supported yet. This is a laboratory port, not a release. Do not invoke the unmodified Mystic pipeline as a substitute.

The first raw EXT4 candidate and its gzip are built and verified. [lab-image.json](lab-image.json) records their sizes, SHA-256 hashes and the limits of offline validation. The gzip is 6,866,550,221 bytes; it expands to 15,169,392,640 bytes. Construction verified 14,480 inode metadata records and all 11,219 regular-file contents. Successful construction does not establish that the image boots on `dash`.

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

The stages retain a recovery journal and atomically publish the metadata/content pair. Files are moved on the same filesystem, preserving the original raw images without duplicating the full unpacked tree. Six compatibility fixes are included: remove two conflicting powercap genfs rules, restore the loop-control label before APEX bootstrap, add optional declarations for the retained dash HALs, install the standard monolithic-GSI `skip_mount.cfg` for `/system_ext` and `/product`, grant SurfaceFlinger the existing vendor composer-client role, and install the power-key telemetry workaround described below.

The output is an **unsigned, editable EXT4 laboratory image**, not an OPPO-signed update or a production ROM. The original `/my_reserve` directory has no label; a temporary build label is removed and verified afterward. SELinux policies compile in the mode used by the unmodified donor init and contain no permissive domains, but the stricter build-time neverallow audit still reports retained-vendor conflicts. Full APEX/kernel VINTF checks and device tests remain outstanding.

Pinned toolkit: [MysticGSI](https://github.com/MysticGSI/mysticgsi/tree/b906057b9909d9ec3272feb9c53306f7bd4912f0). There is no `37/coloros` profile at this commit. Its stock pipeline also performs broad removals, disables security properties and can install permissive-SELinux helpers, so this port will use explicit, reviewed transformations instead. Original authorship must be preserved.

The first candidate targets DSU, preserving the working Infinity base. Later iterations should modify only the inactive DSU copy and corresponding canonical host files, with rollback, verified metadata and an explicit AVB policy.

For the laboratory transfer, `serve_artifact.py` serves one hash-verified file with a bearer token and pinned TLS. The runtime systemd unit uses privileged lifecycle hooks to add and remove one source-restricted firewall rule while keeping the original guard baseline intact. Do not install this example as a permanent public download service. Its optional `--tcp-congestion bbr` selects BBR only for the transfer socket; it requires an available, allowed kernel implementation and does not change the global TCP default.

Design and current task checklist: `docs/superpowers/specs/2026-11-01-coloros17-dsu-design.md` and `docs/superpowers/plans/2026-11-01-coloros17-dsu.md`.

The existing gzip predates `skip_mount.cfg`. Its hashes identify the preserved base image, not the patched phone variant; see `post_build_dsu_patch` in `lab-image.json`. No replacement archive has been built.

Runtime findings from 2026-11-01:

- Physical power-key events were delayed by about 5.02 seconds inside the donor's `saupwkProcessKey`, waiting for absent `IOplusProject/default`. Setting `persist.sys.saupwk_test=true` bypasses this optional telemetry path; the owner confirmed the button became responsive. The recipe now installs `system_ext/etc/init/dash-power-key.rc`, which reapplies this setting after persisted properties load. The init integration is source-tested; the new RC has not yet been boot-tested in a rebuilt image. The separate composer-client policy change reduced measured display-power transitions from about 2.4 seconds to 0.2–0.3 seconds.
- Both SIMs work in the retained Infinity base, but ColorOS still reports radio power off. Restoring the base's `ro.vendor.imeisv=05` in the installed DSU did not restore service and is not promoted as a recipe fix. No modem or NV partition was changed.
- The charging warning has a traced compatibility cause: absent `vendor.oplus.hardware.charger.ICharger/default` returns `-1`, BatteryService publishes that as `notifycode`, and SystemUI treats bit 1 as overvoltage. The observed USB input was about 4.82 V. This does not establish all future charging conditions are safe. A fix must represent unavailable diagnostics separately and preserve real fault notifications and kernel protections; no charging protection has been disabled.
- The owner confirmed a direct standard-HAL pulse at full amplitude, and ordinary interface feedback after the optional source patch in `patches/0002-dash-haptic-aosp-fallback.patch`. The owner also confirmed that feedback intensity follows the volume slider. The donor's proprietary Oplus extension remains absent. `haptic-fallback.json` pins the source/result hashes and verification; `tests/device/ColorOsHapticFallbackProbe.java` checks the converter against actual Android classes. This optional JAR-rebuild step is not integrated into `candidate.py` yet. The current phone trial uses a temporary bind mount and `persist.sys.dash.haptic_fallback=true`; the bind disappears on reboot.
- The O-Haptics video preview calls RichTap pattern playback. That path is separate from OplusPrebakedSegment and is not covered by the basic feedback patch. The preview currently logs unavailable Oplus vibrator extension errors; do not claim that proprietary texture/style playback works because ordinary button feedback works.
