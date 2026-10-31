# Public release and maintainership status — 2026-11-01

## Existing deliverable

An owner-signed, boot-tested UNOFFICIAL GApps OTA exists. It was installed successfully through recovery on one `dash` phone. Its immutable ZIP hash and exact partition scope are recorded in `signing/release-20261031-validation.json`. The public installation preview is `docs/install-release-v2.md`.

This is a testing release candidate, not a claim of complete hardware qualification. Root is a separate opt-in installation. The working Integrity settings are described independently in `docs/integrity.md`; they are not silently included in the existing OTA.

## Before a wider UNOFFICIAL release

- Publish the exact GApps/release-signing branch and its dependencies, changes and original author credits. The public GitHub repository exists, but the latest local branch must be published deliberately; the remote main branch is older.
- Resolve kernel-source provenance. `BoardConfig.mk` currently consumes `device/xiaomi/dash-kernel/Image.lz4` and prebuilt modules. The pinned kernel repository contains binaries, DTBs, headers and extraction scripts, not a complete buildable kernel source tree. Xiaomi's `dash-w-oss` sources exist, but correspondence to the exact distributed binary/modules and any modifications has not been established. A link to a similarly named branch is not proof of correspondence.
- Complete basic hardware and recovery tests and gather independent tester reports. Calls/IMS, NFC, biometrics, camera modes, suspend/standby, sustained charging, USB, encryption/recovery decryption and eSIM behavior are not all qualified. Confirm the reported charging estimate fix on-device over actual charge cycles.
- Test installation from each supported starting firmware, a clean recovery sideload and an update from the previous release. Document recovery replacement/retention and rollback. Do not label a generic OrangeFox one-ZIP installation as tested.
- Publish known limitations, download hashes, a bug-report route and a realistic update policy. Do not promise permanent Google certification or conceal the post-install Integrity setup requirement.
- Review source history and every public attachment for signing private keys, attestation XML, personal backups and identifying phone logs. Keep public certificates and original contributor credits.

These are release-readiness recommendations; they are not all stated requirements from the Infinity team.

## Official Infinity X maintainership

The [current official requirements](https://projectinfinity-x.com/apply-for-maintainership/) call for public device sources, fully published kernel source, proper authorship, one's own build infrastructure, at least one functional UNOFFICIAL release, a GitHub account at least three years old, maintaining no more than two ROMs before applying, and ongoing collaboration/updates/support. FeniksD's account was created on 2020-07-31, so the age requirement is satisfied.

The [application form](https://github.com/ProjectInfinity-X/official_devices/issues/new?template=maintainers-application.yml) asks for the device, source URLs, maintained ROMs, a link to an existing public UNOFFICIAL release announcement, exceptions and contact information. Having a private/local ZIP alone does not complete that public-release requirement. The team decides acceptance; no application has been submitted by this task.

The main unresolved technical item for an application is the complete corresponding kernel source. The practical next step is a clearly labelled UNOFFICIAL testing release with accurate source and testing information, followed by resolving that source question with the upstream device maintainers.

## Download hosting

The OTA is 4,286,098,883 bytes. [GitHub Releases currently requires each asset to be under 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), so this single ZIP cannot be uploaded there intact. Host the intact OTA on a suitable large-file service and link it from the GitHub release, or use explicitly documented split files with reconstruction/hash verification. The intact ZIP is the simpler installation experience. A small companion installation kit and checksums can live in GitHub Releases.

No public upload or message to another maintainer is performed merely by preparing these files.
