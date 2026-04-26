"""
ls_octane.py
------------
Octane render-engine integration helpers.

Octane for Cinema 4D ships its own camera tag whose plugin ID changes between
Octane versions. We deliberately do NOT hardcode an unverified ID here --
distributing the plugin with a wrong ID would either silently no-op or, worse,
attach the wrong tag type. Instead, this module exposes a single placeholder
function that:

  * detects whether Octane is installed,
  * attaches the Octane camera tag if (and only if) the correct ID has been
    confirmed by the integrator,
  * fails gracefully (logs and returns False) in every other case.

How to finish wiring this up
----------------------------
1. Install Octane for Cinema 4D and open a scene.
2. In the C4D Console run:

       import c4d
       sel = doc.GetActiveTag()      # select an existing Octane Camera Tag
       print(sel.GetType())          # prints the integer plugin ID

3. Paste that integer into ``OCTANE_CAMERA_TAG_ID`` below and remove the
   ``None`` guard.
"""

import c4d


# TODO: Replace ``None`` with the verified Octane Camera Tag plugin ID.
# Inspect an installed Octane build with the snippet shown in the module
# docstring before committing a real value here.
OCTANE_CAMERA_TAG_ID = None


def is_octane_available():
    """
    Best-effort check that Octane for C4D is installed.

    We look for a plausible Octane plugin in the registered plugin list. This
    is intentionally permissive -- the real gating is the verified tag ID.
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


def add_octane_camera_tag(camera):
    """
    Attach an Octane Camera Tag to *camera* if possible.

    Returns
    -------
    bool
        True  -- tag attached successfully.
        False -- Octane not installed, tag ID not yet verified, or the
                 allocation failed. The caller should treat this as a
                 non-fatal condition.
    """
    if camera is None:
        return False

    if OCTANE_CAMERA_TAG_ID is None:
        # ID has not been verified yet -- intentionally a no-op.
        # See the module docstring for the verification procedure.
        print(
            "[C4D_ls-cam] Octane camera tag skipped: "
            "OCTANE_CAMERA_TAG_ID is not set in ls_octane.py."
        )
        return False

    if not is_octane_available():
        print("[C4D_ls-cam] Octane not detected; skipping Octane camera tag.")
        return False

    try:
        tag = c4d.BaseTag(OCTANE_CAMERA_TAG_ID)
    except Exception as exc:
        print("[C4D_ls-cam] Failed to allocate Octane camera tag: {0}".format(exc))
        return False

    if tag is None:
        print("[C4D_ls-cam] BaseTag(OCTANE_CAMERA_TAG_ID) returned None.")
        return False

    camera.InsertTag(tag)
    return True
