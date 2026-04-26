"""
ls_rig.py
---------
Builds the LS Relativistic Camera Rig in the active Cinema 4D document.

Public entry point:
    build_rig(doc) -> dict
        Creates and inserts the rig hierarchy. Returns a dict containing the
        created camera, rig null, and controller tag. All scene mutations are
        wrapped in a single undo step so the user can Ctrl+Z the whole rig.

This module is responsible for the scene graph only. The actual
relativistic evaluation lives in :mod:`ls_evaluator`; the controller tag
created here is a thin shim that calls into it on every scene update.
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


def _add_vector_ud(host, name, default_xyz):
    """Add a VECTOR user-data field to *host* and return its DescID."""
    bc = c4d.GetCustomDataTypeDefault(c4d.DTYPE_VECTOR)
    bc[c4d.DESC_NAME] = name
    bc[c4d.DESC_SHORT_NAME] = name
    default = c4d.Vector(*default_xyz)
    bc[c4d.DESC_DEFAULT] = default
    desc_id = host.AddUserData(bc)
    host[desc_id] = default
    return desc_id


def _add_enum_ud(host, name, items, default_index):
    """
    Add a CYCLE (dropdown) user-data field to *host* and return its DescID.

    *items* is the ordered tuple of label strings. The integer stored in
    the field is the selected index into that tuple.
    """
    bc = c4d.GetCustomDataTypeDefault(c4d.DTYPE_LONG)
    bc[c4d.DESC_NAME] = name
    bc[c4d.DESC_SHORT_NAME] = name
    bc[c4d.DESC_DEFAULT] = int(default_index)
    bc[c4d.DESC_CUSTOMGUI] = c4d.CUSTOMGUI_CYCLE

    cycle = c4d.BaseContainer()
    for i, label in enumerate(items):
        cycle.SetString(i, label)
    bc[c4d.DESC_CYCLE] = cycle

    desc_id = host.AddUserData(bc)
    host[desc_id] = int(default_index)
    return desc_id


def _build_user_data(tag):
    """
    Attach all user-data parameters defined in ls_constants to *tag*.

    Returns a dict mapping the user-data key (string) to its DescID, so the
    caller (or downstream math code) can read/write the parameters reliably
    even if the user reorders fields later.

    Computed-output fields (``UD_OUTPUT_KEYS`` plus the internal rest-FOV
    cache) are added with the same DTYPE_REAL widget but their labels are
    suffixed with "(computed)" / "(internal)" to signal that they are
    written by the evaluator and should be treated as read-only -- C4D
    has no native read-only flag for user data, so we rely on convention
    plus the evaluator overwriting these on every tick.
    """
    ud_ids = {}

    for key in K.UD_ORDER:
        label = K.UD_LABELS[key]

        if key in K.UD_ENUMS:
            spec = K.UD_ENUMS[key]
            ud_ids[key] = _add_enum_ud(tag, label, spec["items"], spec["default"])
        elif key in K.UD_VECTORS:
            (default_xyz,) = K.UD_VECTORS[key]
            ud_ids[key] = _add_vector_ud(tag, label, default_xyz)
        elif key in K.UD_RANGES:
            vmin, vmax, default = K.UD_RANGES[key]
            ud_ids[key] = _add_real_ud(tag, label, default, vmin, vmax)
        elif key in K.UD_OUTPUT_RANGES:
            vmin, vmax, default = K.UD_OUTPUT_RANGES[key]
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


def _capture_rest_camera_state(tag, camera):
    """
    Snapshot the camera's current FOV / focus distance / aperture onto
    the controller tag.

    Every camera-side effect derives its live value from these baselines,
    so toggling an effect off (or calling ``reset_ls_camera_rig``)
    restores the camera to exactly its initial state. Capturing once at
    rig creation -- rather than reading the camera every tick -- means
    the baseline never drifts even if the evaluator is wedged into a
    feedback loop.

    Defensive against missing fields and against parameters the camera
    type may not expose (some properties are gated on the active
    renderer). Each field is captured independently so a single missing
    parameter never blocks the others.
    """
    # Build a label -> DescID lookup for the controller's user data.
    lookup = {}
    for desc_id, bc in tag.GetUserDataContainer():
        lookup[bc[c4d.DESC_NAME]] = desc_id

    def _store(label, value):
        desc_id = lookup.get(label)
        if desc_id is None:
            return
        try:
            tag[desc_id] = float(value)
        except Exception:
            pass

    # FOV is always present on a standard camera.
    try:
        _store(K.UD_LABELS[K.UD_REST_FOV_RAD], camera[c4d.CAMERAOBJECT_FOV])
    except Exception:
        pass

    # Focus distance: TARGETDISTANCE on the standard camera. May be 0
    # if the user hasn't set it -- still safe to record.
    try:
        _store(K.UD_LABELS[K.UD_REST_FOCUS_DIST],
               camera[c4d.CAMERAOBJECT_TARGETDISTANCE])
    except Exception:
        pass

    # Aperture: APERTURE on the standard camera. Some camera variants
    # (and some renderer presets) hide this; tolerate absence.
    try:
        _store(K.UD_LABELS[K.UD_REST_APERTURE],
               camera[c4d.CAMERAOBJECT_APERTURE])
    except Exception:
        pass


# Backwards-compatible alias -- earlier passes called this helper.
_capture_rest_fov = _capture_rest_camera_state


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


# Tag script body. Kept as a triple-quoted string so the rig builder can
# inject it verbatim. Logic is deliberately kept in the importable
# ``ls_evaluator`` module -- the tag is just a thin shim that finds the
# camera under its host null and delegates.
_CONTROLLER_TAG_SOURCE = '''\
# LS_Relativity_Controller -- evaluation shim.
# All real work lives in ls_evaluator.update_ls_camera_rig(); this script
# only locates the camera under the rig null and forwards the call.
import c4d


def _find_ls_camera(host):
    if host is None:
        return None
    child = host.GetDown()
    while child is not None:
        if child.GetType() == c4d.Ocamera:
            return child
        child = child.GetNext()
    return None


def main():
    tag = op  # noqa: F821 -- 'op' is injected by C4D's Python tag runtime
    host = tag.GetObject()
    cam = _find_ls_camera(host)
    if cam is None:
        return

    try:
        import ls_evaluator
    except ImportError:
        # Plugin folder isn't on sys.path (e.g. tag was copied to a scene
        # without the plugin installed). Fail quietly.
        return

    ls_evaluator.update_ls_camera_rig(tag.GetDocument(), tag, cam)
'''


def _make_controller_tag(host):
    """
    Create the relativity controller tag and attach it to *host*.

    A Python Tag (Tpython) is used so the relativistic evaluation runs
    automatically each time the scene is evaluated. The tag's body is a
    thin shim that delegates to ``ls_evaluator.update_ls_camera_rig``.
    """
    tag = c4d.BaseTag(c4d.Tpython)
    if tag is None:
        raise RuntimeError("Failed to allocate Python tag (Tpython).")
    tag.SetName(K.CONTROLLER_TAG_NAME)
    tag[c4d.TPYTHON_CODE] = _CONTROLLER_TAG_SOURCE
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

        # 5. Capture the camera's rest state (FOV, focus distance,
        # aperture) onto the controller. The evaluator derives every
        # live value from these baselines so changes remain
        # non-destructive and reset_ls_camera_rig() can restore them.
        _capture_rest_camera_state(controller_tag, camera)

        # 6. Best-effort Octane integration. Discovery + attachment is
        # silent here: the Attribute Manager dialog only appears when the
        # user later flips enable_octane_camera_tag and calls into
        # ls_octane.add_octane_camera_tag(camera, show_dialog_on_failure=True)
        # from an interactive command. If Octane isn't installed at all,
        # this just returns None.
        ls_octane.add_octane_camera_tag(camera, show_dialog_on_failure=False)

        # 7. Make the new camera the active selection so the user sees it.
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
