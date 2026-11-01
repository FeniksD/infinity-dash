# ColorOS 17 for dash: official donor and DSU laboratory

## User-approved objective

Prepare ColorOS **17**, not the previously tested ColorOS 16, for POCO X8 Pro Max / Redmi Turbo 5 Max (`dash`, owner model `2602BPC18G`). The first target is a DSU test image while Infinity remains the main installation. Use an official OPPO firmware donor and the published MysticGSI tooling as a reviewed starting point, not an uninspected third-party GSI.

The old device-specific ColorOS16 port explicitly names OPPO Find X9 Pro CN as donor: https://t.me/POCOX8ProMaxIDUpdate/101. The later hotfix is https://t.me/POCOX8ProMaxIDUpdate/125. These establish prior art only; do not copy their binaries or assume their fixes apply to ColorOS17.

## Constraints

- Keep Infinity, its user data, bootloader, LK, modem, NV and eSIM state outside the port's write scope.
- Download large inputs directly to the existing VDS, not the owner's slow PC connection. Persist public provenance and hashes locally.
- Confirm actual donor metadata reports ColorOS17 and Android SDK37. A filename or web listing is insufficient.
- Retain the target's hardware vendor/ODM for the first system-only DSU attempt. A GSI test cannot establish compatibility of a different kernel/vendor stack.
- Preserve ColorOS launcher, system UI and user-visible features where compatible. Do not inherit blanket debloat, insecure ADB, permissive SELinux or opaque binary edits by default.
- Keep the source/prepared tree separate from generated images. Record every input, tool revision and applied change.
- Reuse one installed DSU instance where possible. Later iterations should edit its inactive mapped EXT4 filesystem, with matching edits to the canonical host tree. Do not assume EXT4 alone makes an AVB-protected mapping writable.
- Validate before/after hashes, filesystem metadata and rollback for each edit. Never edit a mounted filesystem through its raw backing blocks.
- Do not flash or activate a candidate merely because extraction/build succeeded. Present its verified scope and remaining risks first.

## Engineering choices

The initial donor candidate is Find X9 Pro CN, with Find X8 Pro CN considered only if its closer platform materially helps. This is an engineering selection, not a user preference for a specific OPPO model. Prefer manufacturer-hosted bytes; an index may locate the URL but must not be the sole provenance claim.

MysticGSI is pinned at `b906057b9909d9ec3272feb9c53306f7bd4912f0`. The audit found no `patches/37/coloros` or `patches/CinnamonBun/coloros`. Generic SDK37 support does not establish ColorOS17 support. Fail before mutation when a required profile is absent. Do not blindly copy `patches/36/coloros`.

The donor OTA may mark its payload as `partial_update`; accept it as an extraction input only if every required partition is self-contained (no old-partition dependency or source extents). Never treat it as a POCO flash package.

## Deliverables and boundaries

1. An official donor archive plus provenance, metadata and partition hashes.
2. A reviewed, explicit ColorOS17 patch profile with a preservation report and reproducible preparation commands.
3. A candidate EXT4 DSU image with a documented AVB policy and offline validation.
4. After an authorized boot test, a minimal delta/rollback workflow for the installed DSU and a retained canonical tree.

Passing source or filesystem checks does not prove camera, IMS, fingerprint, encryption, standby or charging work. Passing Integrity is a separate runtime matter, not a property guaranteed by this port. No external announcements, maintainer application or public release is included in this phase.
