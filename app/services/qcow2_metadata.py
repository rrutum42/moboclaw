"""Snapshot branch metadata (``SnapshotRecord.metadata`` keys).

Branches are stored as full **directory copies** of the session ``ANDROID_AVD_HOME`` tree (see
``snapshot_capture``). Legacy qcow2 keys are kept as string constants for tests and old records.
"""

# --- Clone-based branch snapshots (current) ---

# Absolute path to the stored branch directory (…/branches/<snapshot_id>/).
AVD_CLONE_PATH = "avd_clone_path"

# AVD name at capture time (e.g. ``moboclaw_emu-…``); used when renaming on restore.
SESSION_AVD_NAME = "session_avd_name"

# Absolute path to the session ``ANDROID_AVD_HOME`` directory at capture time; used to rewrite paths.
SESSION_ANDROID_AVD_HOME = "session_android_avd_home"

# Parent snapshot id at capture time (string).
AVD_PARENT_SNAPSHOT_ID = "avd_parent_snapshot_id"

# Optional: BASE seed marker (not a filesystem path).
AVD_BRANCH_KIND = "avd_branch_kind"
AVD_BRANCH_KIND_GOLDEN = "golden"

# --- Legacy qcow2 v1 (deprecated; not written by new captures) ---

QCOW2_USERDATA_PATH = "qcow2_userdata_path"
QCOW2_PARENT_SNAPSHOT_ID = "qcow2_parent_snapshot_id"
QCOW2_FORMAT = "qcow2_format"
QCOW2_FORMAT_FLAT = "flat_qcow2"
QCOW2_BRANCH_KIND = "qcow2_branch_kind"
QCOW2_BRANCH_KIND_GOLDEN = "golden"
