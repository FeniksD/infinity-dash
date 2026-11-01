# ColorOS 17 / dash work area

Status: official donor and signatures checked; the reviewed host construction adapter is implemented. The port is **not yet boot-tested**. Do not invoke the unmodified Mystic pipeline as a substitute.

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

The stages retain a recovery journal and atomically publish the metadata/content pair. Files are moved on the same filesystem, preserving the original raw images without duplicating the full unpacked tree. Only three compatibility changes are included: remove two conflicting powercap genfs rules, restore the loop-control label before APEX bootstrap, and add optional declarations for the retained dash HALs.

The output is an **unsigned, editable EXT4 laboratory image**, not an OPPO-signed update or a production ROM. The original `/my_reserve` directory has no label; a temporary build label is removed and verified afterward. SELinux policies compile in the mode used by the unmodified donor init and contain no permissive domains, but the stricter build-time neverallow audit still reports retained-vendor conflicts. Full APEX/kernel VINTF checks and device tests remain outstanding.

Pinned toolkit: [MysticGSI](https://github.com/MysticGSI/mysticgsi/tree/b906057b9909d9ec3272feb9c53306f7bd4912f0). There is no `37/coloros` profile at this commit. Its stock pipeline also performs broad removals, disables security properties and can install permissive-SELinux helpers, so this port will use explicit, reviewed transformations instead. Original authorship must be preserved.

The first candidate targets DSU, preserving the working Infinity base. Later iterations should modify only the inactive DSU copy and corresponding canonical host files, with rollback, verified metadata and an explicit AVB policy.

Design and current task checklist: `docs/superpowers/specs/2026-11-01-coloros17-dsu-design.md` and `docs/superpowers/plans/2026-11-01-coloros17-dsu.md`.
