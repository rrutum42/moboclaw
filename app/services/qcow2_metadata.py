"""v1 qcow2 snapshot branching metadata (``SnapshotRecord.metadata`` keys).

Branches are stored as flattened qcow2 images produced offline via ``qemu-img convert``
(see ``snapshot_capture``). ADB/emulator ``avd snapshot`` save/load is not used in v1.
"""

# Flat qcow2 path on disk (absolute path string) for provisioning non-BASE snapshots.
QCOW2_USERDATA_PATH = "qcow2_userdata_path"

# Parent snapshot id at capture time (string, mirrors ``SnapshotRecord.parent_snapshot_id``).
QCOW2_PARENT_SNAPSHOT_ID = "qcow2_parent_snapshot_id"

# Format discriminator; v1 uses a single flattened image.
QCOW2_FORMAT = "qcow2_format"
QCOW2_FORMAT_FLAT = "flat_qcow2"

# Optional: BASE snapshot seed marker (not a filesystem path).
QCOW2_BRANCH_KIND = "qcow2_branch_kind"
QCOW2_BRANCH_KIND_GOLDEN = "golden"
