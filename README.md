# Infinity X 4.1 for POCO X8 Pro Max (`dash`)

Unofficial Android 17 bring-up and reproducible build infrastructure for POCO X8 Pro Max (`2602BPC18G` / `mt6991`). The first full build and final source integrity verification completed on October 31, 2026.

## What Is Included

- Pinned device tree snapshot from `xiaomi-mt6991/device_xiaomi_dash` (`cnb`, commit `574a0737bdc440ba90aa7b28681506ed28a44d9e`).
- Target product `infinity_dash`, model `2602BPC18G`, `UNOFFICIAL`, `userdebug`, vanilla build (no GApps).
- 13 upstream dependencies pinned by exact commit SHA in `sources/dependencies.json` and `local_manifests/dash.xml`.
- Verifiable patch `patches/0001-infinity-dash.patch` applied cleanly on top of the synced upstream tree after `repo sync`.
- Automated checks for pinned commits, idempotent patch application, and protection against overwriting upstream changes.
- Preparation and build automation scripts with no automatic device-flashing commands.
- Build server access and integrity controls with independent verification from a local workstation.
- SHA-256 verification of all input files and read-only source-tree builds with isolated output artifacts and logs.

## Local Verification

```sh
python3 -m unittest discover -s tests -v
python3 tools/preflight.py
bash scripts/prepare-server.sh /srv/infinity-dash
```

By default, `prepare-server.sh` runs in dry-run mode and only prints the execution plan without creating the source directory. Server setup details are documented in [build/README.md](build/README.md).

## Verification Status

The full `m bacon -j8` build exited with status 0. Full source snapshots were verified both before and after compilation. SELinux/Treble, bootclasspath, VINTF, OTA/payload signatures, AVB, and SHA-256 checksums across all 36 payload images passed validation. The local test suite passes all 96 unit tests. See [validation/2026-10-31-build.json](validation/2026-10-31-build.json) for SHA-256 hashes and verification scope.

- Artifact: `Project_Infinity-X-4.1-dash-31.10.2026-VANILLA-UNOFFICIAL.zip` (3,291,568,750 bytes, signed with public test keys).
- Low-level firmware images (`lk`, `preloader_raw`) are included in the OTA package; always keep a verified recovery/flashing plan before installing.
- GitHub Actions triggers are disabled by default; builds run over SSH. Components of the restricted CI request protocol are documented in [ci/README.md](ci/README.md).
- Live build console on the VM: `bash scripts/watch-builds.sh` (read-only tmux attach showing Infinity X build output, experimental `gsid` build, and host health status; detach with `Ctrl+b` then `d`).

Additional source notes: [sources/NOTES.md](sources/NOTES.md). Bring-up plan: [docs/superpowers/plans/2026-10-30-infinity-dash.md](docs/superpowers/plans/2026-10-30-infinity-dash.md).

Exact revisions of all 1,245 synced repositories are pinned in [build/source-manifest.xml](build/source-manifest.xml). Device-specific changes for `dash` are layered via the standalone patch file.

## Credits

Port bring-up and reproducible build infrastructure by [FeniksD](https://github.com/FeniksD). Device tree based on [xiaomi-mt6991/device_xiaomi_dash](https://github.com/xiaomi-mt6991/device_xiaomi_dash) and system base on [Project Infinity X](https://github.com/ProjectInfinity-X). Original authorship and license headers are preserved.
