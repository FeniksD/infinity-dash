# DSU mapping on directly mounted userdata

The current Android 17 phone fails DSU installation while mapping the new userdata image: `/data` is mounted directly from a physical block device, and `ImageManager::MapImageDevice` requires an intermediate device-mapper layer. The existing loop mapping implementation is still present in the pinned source but no longer reached from this method.

Prepare an experimental source patch restoring the existing loop mapping route only for images under `/data/gsi/dsu/`. Do not change encryption, reformat userdata, remove kernel security checks, or install anything on the phone. Keep device-mapper-backed images and ramdisk builds on their existing paths. Preserve mapping status and cleanup after property errors.

The restored helper must reject an empty image-file list and return the combined device-mapper path for a split image instead of its last loop segment. Reuse existing direct-I/O and cleanup behavior.

The initial deliverable is a pinned, reviewable patch with executable host tests of the actual patched mapping methods. These tests simulate kernel/helper operations and do not prove Android compilation, SELinux compatibility, first-stage mapping or boot safety. Native compilation and device testing are separate gates. Never apply the patch to the currently sealed build tree while compilation is running.
