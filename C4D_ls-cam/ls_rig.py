"""
ls_rig.py
---------
Builds the LS Relativistic Camera Rig in the active Cinema 4D document.

Public entry point:
    build_rig(doc) -> dict
        Creates and inserts the rig hierarchy. Returns a dict containing the
        created camera, rig null, and controller tag. All scene mutations are
        wrapped in a single undo step so the user can Ctrl+Z the whole rig.

This module deliberately does NOT implement any relativistic math. It only
sets up the scene graph and exposes parameters via user data. The math is
expected to live in a separate Python tag script (or a future
ls_relativity.py) that reads the user data on every frame.
"""

import c4d

# These siblings are importable because c4d_ls_cam.pyp prepends this
# directory to sys.path during plugin load.
import ls_constants as K
import ls_octane


# ---------------------------------------------------------------------------
# User-data construction helpers
# ---------------------------------------------------------------------------

def _add_real_ud(host, name, default, vmin, vmax, step=0.001):
    """Add a REAL (float) user-data field to *host* and return its DescID."""
    bc = c4d.GetCustomDataTypeDefault(c4d.DTYPE_REAL)
    bc[c4d.DESC_NAME] = name
    bc[c4d.DESC_SHORT_NAME] = name
    bc[c4d.DESC_DEFAULT] = float(default)
    bc[c4d.DESC_MIN] = float(vmin)
    bc[c4d.DESC_MAX] = float(vmax)
    bc[c4d.DESC_MINSLIDER] = float(vmin)
    bc[c4d.DESC_MAXSLIDER] = float(vmax)
    bc[c4d.DESC_STEP] = float(step)
    bc[c4d.DESC_CUSTOMGUI] = c4d.CUSTOMGUI_REALSLIDER
    desc_id = host.AddUserData(bc)
    host[desc_id] = float(default)
    return desc_id


def _add_bool_ud(host, name, default):
    """Add a BOOL user-data field to *host* and return its DescID."""
    bc = c4d.GetCustomDataTypeDefault(c4d.DTYPE_BOOL)
    bc[c4d.DESC_NAME] = name
    bc[c4d.DESC_SHORT_NAME] = name
    bc[c4d.DESC_DEFAULT] = bool(default)
    bc[c4d.DESC_CUSTOMGUI] = c4d.CUSTOMGUI_BOOL
    desc_id = host.AddUserData(bc)
    host[desc_id] = bool(default)
    return desc_id


def _build_user_data(tag):
    """
    Attach all user-data parameters defined in ls_constants to *tag*.

    Returns a dict mapping the user-data key (string) to its DescID, so the
    caller (or downstream math code) can read/write the parameters reliably
    even if the user reorders fields later.
    """
    ud_ids = {}

    for key in K.UD_ORDER:
        label = K.UD_LABELS[key]

        if key in K.UD_RANGES:
            vmin, vmax, default = K.UD_RANGES[key]
            ud_ids[key] = _add_real_ud(tag, label, default, vmin, vmax)
        elif key in K.UD_BOOL_DEFAULTS:
            default = K.UD_BOOL_DEFAULTS[key]
            ud_ids[key] = _add_bool_ud(tag, label, default)
        else:
            # Should never happen unless ls_constants gets out of sync.
            raise RuntimeError(
                "Unknown user-data key in UD_ORDER: {0}".format(key)
            )

    return ud_ids


# ---------------------------------------------------------------------------
# Object creation helpers
# ---------------------------------------------------------------------------

def _make_camera():
    """Create a standard Cinema 4D camera object."""
    cam = c4d.BaseObject(c4d.Ocamera)
    if cam is None:
        raise RuntimeError("Failed to allocate Ocamera object.")
    cam.SetName(K.CAMERA_NAME)
    return cam


def _make_rig_null():
    """Create the controller null parented above the camera."""
    null = c4d.BaseObject(c4d.Onull)
    if null is None:
        raise RuntimeError("Failed to allocate Onull object.")
    null.SetName(K.RIG_NULL_NAME)
    # Use a recognizable display so the rig is easy to spot in the viewport.
    null[c4d.NULLOBJECT_DISPLAY] = c4d.NULLOBJECT_DISPLAY_CIRCLE
    null[c4d.NULLOBJECT_ORIENTATION] = c4d.NULLOBJECT_ORIENTATION_CAMERA
    return null


def _make_controller_tag(host):
    """
    Create the relativity controller tag and attach it to *host*.

    A Python Tag (Tpython) is used so we can later embed the relativistic
    math directly in the tag's main() callback. The tag is created in a
    'no-op' state -- its script is left empty until the math module lands.
    """
    tag = c4d.BaseTag(c4d.Tpython)
    if tag is None:
        raise RuntimeError("Failed to allocate Python tag (Tpython).")
    tag.SetName(K.CONTROLLER_TAG_NAME)

    # Empty placeholder script. Real implementation will read user data
    # from op (the host) and drive camera / shader parameters.
    tag[c4d.TPYTHON_CODE] = (
        "# LS_Relativity_Controller -- placeholder.\n"
        "# Relativistic math will be implemented here in a later commit.\n"
        "import c4d\n"
        "\n"
        "def main():\n"
        "    pass\n"
    )

    host.InsertTag(tag)
    return tag


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_rig(doc):
    """
    Create the full LS Relativistic Camera Rig in *doc*.

    The whole operation is wrapped in StartUndo()/EndUndo() so a single
    Ctrl+Z removes every object inserted by this call. If any step fails the
    partial state is rolled back via the undo stack.

    Returns
    -------
    dict
        {
            "camera":     c4d.BaseObject,
            "rig_null":   c4d.BaseObject,
            "controller": c4d.BaseTag,
            "ud_ids":     dict[str, c4d.DescID],
        }
    """
    if doc is None:
        raise ValueError("build_rig() requires an active BaseDocument.")

    doc.StartUndo()
    try:
        # 1. Create objects (not yet in the scene graph).
        rig_null = _make_rig_null()
        camera = _make_camera()

        # 2. Parent camera under rig null.
        camera.InsertUnder(rig_null)

        # 3. Insert the rig null at the document root.
        doc.InsertObject(rig_null)
        doc.AddUndo(c4d.UNDOTYPE_NEW, rig_null)
        # Children of an inserted object are tracked by C4D's undo system,
        # but we still record the camera explicitly to be safe across versions.
        doc.AddUndo(c4d.UNDOTYPE_NEW, camera)

        # 4. Attach the controller tag to the rig null and add user data.
        controller_tag = _make_controller_tag(rig_null)
        doc.AddUndo(c4d.UNDOTYPE_NEW, controller_tag)
        ud_ids = _build_user_data(controller_tag)

        # 5. Optional Octane camera tag -- safe no-op if Octane isn't present.
        ls_octane.add_octane_camera_tag(camera)

        # 6. Make the new camera the active selection so the user sees it.
        doc.SetActiveObject(camera, c4d.SELECTION_NEW)

    except Exception:
        # Allow C4D to roll back any partially-applied changes.
        doc.EndUndo()
        c4d.EventAdd()
        raise

    doc.EndUndo()
    c4d.EventAdd()

    return {
        "camera": camera,
        "rig_null": rig_null,
        "controller": controller_tag,
        "ud_ids": ud_ids,
    }
