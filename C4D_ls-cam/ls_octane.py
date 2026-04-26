"""
ls_octane.py
============
Octane render-engine integration helpers.

Octane for Cinema 4D ships its own camera tag whose plugin ID changes
between Octane versions. We never hardcode an unverified ID -- that would
silently misroute parameters on machines we never tested against. Instead,
this module:

    * tries to **discover** the Octane Camera Tag plugin by scanning the
      registered tag plugins for one whose name contains both "octane"
      and "camera",
    * lets the integrator **override** the discovered ID by setting
      :data:`OCTANE_CAMERA_TAG_ID` explicitly,
    * **attaches** the tag (or detects an existing one on the camera) via
      :func:`add_octane_camera_tag`,
    * **dumps** the tag's full parameter description via
      :func:`dump_octane_tag_parameters`, so the integrator can map Octane
      parameter IDs into :mod:`ls_octane_params` without guessing.

If discovery fails and the explicit ID is unset, every entry point either
no-ops (silent contexts like the per-frame evaluator) or surfaces a single
clear dialog explaining how to recover.
"""

import c4d

import ls_ui
import ls_octane_params as P


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Set this to a verified integer if you want to bypass the runtime name
# search. Leave it ``None`` to fall back to :func:`find_octane_camera_tag_id`.
OCTANE_CAMERA_TAG_ID = None

# Substrings (lowercased) we expect to find in the Octane Camera Tag's
# registered plugin name. Both must be present for a hit. Kept here so the
# heuristic is easy to tune if a future Octane release renames the plugin.
_OCTANE_NAME_TOKENS = ("octane", "camera")

# Module-level cache for the discovered tag ID so repeated calls don't
# re-walk the plugin list every frame.
_DISCOVERED_TAG_ID = None

# Message shown when we cannot attach the tag automatically. The wording
# is fixed by the project brief.
_DIALOG_MESSAGE = (
    "Octane Camera Tag not found. "
    "Add it manually, then rerun Update LS Camera Rig."
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def is_octane_available():
    """
    Best-effort check that Octane for C4D is installed.

    We just look for any registered plugin whose name contains "octane".
    The real gating happens in :func:`find_octane_camera_tag_id`, which
    must succeed before we ever try to allocate a tag.
    """
    try:
        plugins = c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_ANY, True)
    except Exception:
        return False

    for p in plugins or []:
        name = (p.GetName() or "").lower()
        if "octane" in name:
            return True
    return False


def find_octane_camera_tag_id(force_refresh=False):
    """
    Search the registered tag plugins for the Octane Camera Tag.

    Returns the integer plugin ID, or ``None`` if no matching plugin is
    found. The result is cached at module level; pass ``force_refresh=True``
    to re-scan (useful after the user installs Octane mid-session).

    Detection rule
    --------------
    A tag plugin is considered a match if its name (lowercased) contains
    every token in :data:`_OCTANE_NAME_TOKENS` -- by default both
    ``"octane"`` and ``"camera"``. This covers the common spellings
    ("Octane Camera Tag", "OctaneCameraTag", etc.) without false-matching
    the unrelated Octane object plugins.
    """
    global _DISCOVERED_TAG_ID
    if _DISCOVERED_TAG_ID is not None and not force_refresh:
        return _DISCOVERED_TAG_ID

    try:
        plugins = c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_TAG, True)
    except Exception:
        plugins = None

    for p in plugins or []:
        name = (p.GetName() or "").lower()
        if all(tok in name for tok in _OCTANE_NAME_TOKENS):
            _DISCOVERED_TAG_ID = p.GetID()
            return _DISCOVERED_TAG_ID

    return None


def _resolve_tag_id():
    """
    Pick the Octane Camera Tag ID we should use right now.

    Order of precedence:
      1. The integrator-supplied :data:`OCTANE_CAMERA_TAG_ID` constant.
      2. The cached / freshly-discovered ID from
         :func:`find_octane_camera_tag_id`.
    Returns ``None`` if neither is available.
    """
    if OCTANE_CAMERA_TAG_ID is not None:
        return OCTANE_CAMERA_TAG_ID
    return find_octane_camera_tag_id()


def find_existing_octane_tag(camera):
    """Return an Octane Camera Tag already on *camera*, or ``None``."""
    if camera is None:
        return None
    tag_id = _resolve_tag_id()
    if tag_id is None:
        return None
    tag = camera.GetFirstTag()
    while tag is not None:
        if tag.GetType() == tag_id:
            return tag
        tag = tag.GetNext()
    return None


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------

def add_octane_camera_tag(camera, show_dialog_on_failure=False):
    """
    Attach an Octane Camera Tag to *camera*, or detect an existing one.

    Parameters
    ----------
    camera : c4d.BaseObject or None
        The target camera.
    show_dialog_on_failure : bool, optional
        If True, show the user-facing "Octane Camera Tag not found ..."
        dialog when attachment fails. Off by default so this function is
        safe to call from per-frame evaluation paths -- pass True only
        from interactive entry points (menu commands, etc.).

    Returns
    -------
    c4d.BaseTag or None
        The attached or pre-existing tag on success, ``None`` on failure.
    """
    if camera is None:
        if show_dialog_on_failure:
            ls_ui.error(_DIALOG_MESSAGE)
        return None

    # If the camera already has an Octane Camera Tag, reuse it -- never
    # stack duplicates.
    existing = find_existing_octane_tag(camera)
    if existing is not None:
        return existing

    tag_id = _resolve_tag_id()
    if tag_id is None:
        # No verified or discovered ID. This is the most common "Octane
        # missing" path and the place where we surface the dialog.
        ls_ui.log(
            "Octane Camera Tag plugin not found "
            "(no name match for {0}).".format(_OCTANE_NAME_TOKENS)
        )
        if show_dialog_on_failure:
            ls_ui.error(_DIALOG_MESSAGE)
        return None

    try:
        tag = c4d.BaseTag(tag_id)
    except Exception as exc:
        ls_ui.log("Failed to allocate Octane camera tag: {0}".format(exc))
        if show_dialog_on_failure:
            ls_ui.error(_DIALOG_MESSAGE)
        return None

    if tag is None:
        ls_ui.log("BaseTag({0}) returned None.".format(tag_id))
        if show_dialog_on_failure:
            ls_ui.error(_DIALOG_MESSAGE)
        return None

    camera.InsertTag(tag)
    return tag


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

def _format_desc_id(desc_id):
    """Render a c4d.DescID as a readable ``[(id,dtype,creator), ...]``."""
    try:
        levels = []
        for i in range(desc_id.GetDepth()):
            lv = desc_id[i]
            levels.append("({0},{1},{2})".format(lv.id, lv.dtype, lv.creator))
        return "DescID[" + ", ".join(levels) + "]"
    except Exception:
        return repr(desc_id)


def dump_octane_tag_parameters(tag):
    """
    Print every parameter on *tag* as ``DescID : name = value``.

    Use this from the C4D Python console to discover the parameter IDs
    that should be filled into :mod:`ls_octane_params`. Example::

        import c4d
        from C4D_ls_cam import ls_octane
        ls_octane.dump_octane_tag_parameters(doc.GetActiveTag())

    The function never raises -- a malformed parameter is reported as
    ``<unreadable: ...>`` so a single bad entry doesn't abort the dump.

    Returns the number of parameters printed (0 on any failure / empty
    description).
    """
    if tag is None:
        ls_ui.log("dump_octane_tag_parameters: tag is None.")
        return 0

    try:
        description = tag.GetDescription(c4d.DESCFLAGS_DESC_0)
    except Exception as exc:
        ls_ui.log("dump_octane_tag_parameters: GetDescription failed: {0}".format(exc))
        return 0

    if description is None:
        ls_ui.log("dump_octane_tag_parameters: no description on tag.")
        return 0

    print("[C4D_ls-cam] === Octane tag parameter dump ===")
    print("[C4D_ls-cam] tag name : {0}".format(tag.GetName()))
    print("[C4D_ls-cam] tag type : {0}".format(tag.GetType()))

    count = 0
    for bc, desc_id, _group_id in description:
        if bc is None:
            continue
        name = bc[c4d.DESC_NAME] or "<unnamed>"
        try:
            value = tag[desc_id]
        except Exception as exc:
            value = "<unreadable: {0}>".format(exc)
        print("[C4D_ls-cam]   {0} : {1} = {2}".format(
            _format_desc_id(desc_id), name, value
        ))
        count += 1

    print("[C4D_ls-cam] === end dump ({0} params) ===".format(count))

    # Also report which symbolic slots in ls_octane_params are still
    # unmapped, so the user knows what to look for in the dump above.
    missing = P.unmapped_keys()
    if missing:
        print(
            "[C4D_ls-cam] Slots awaiting param_id mapping in "
            "ls_octane_params.OCTANE_CAMERA_PARAMS: {0}".format(missing)
        )

    return count


def dump_octane_tag_on_camera(camera):
    """Convenience wrapper: dump the Octane Camera Tag found on *camera*."""
    tag = find_existing_octane_tag(camera)
    if tag is None:
        ls_ui.log(
            "dump_octane_tag_on_camera: no Octane Camera Tag found on '{0}'.".format(
                camera.GetName() if camera is not None else "<None>"
            )
        )
        return 0
    return dump_octane_tag_parameters(tag)
