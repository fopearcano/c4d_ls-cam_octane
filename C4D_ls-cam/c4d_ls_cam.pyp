"""
c4d_ls_cam.pyp
==============
Cinema 4D 2025+ Python plugin entry point for **C4D_ls-cam**.

Drop this folder into one of:

    <user>/maxon/<C4D version>/python/libs/         (per-user)
    <C4D install dir>/plugins/                      (system-wide)

Cinema 4D auto-loads any .pyp file inside ``plugins/`` on startup. This file
registers a single ``CommandData`` plugin titled "Create LS Relativistic
Camera Rig" under the **Extensions** menu. The actual rig construction lives
in ``ls_rig.py`` so the entry point stays small and easy to audit.

Module layout
-------------
    c4d_ls_cam.pyp     -- this file; CommandData registration
    ls_constants.py    -- IDs, names, user-data definitions
    ls_rig.py          -- rig builder (camera, null, controller tag, UD)
    ls_octane.py       -- Octane integration placeholder
    ls_ui.py           -- console / dialog helpers
"""

import os
import sys
import traceback

import c4d


# ---------------------------------------------------------------------------
# Make sibling modules importable.
# ---------------------------------------------------------------------------
# C4D loads .pyp files as standalone scripts (not as a package), so we
# prepend our own directory to sys.path before importing siblings.
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

import ls_constants as K  # noqa: E402  -- must follow sys.path tweak
import ls_rig             # noqa: E402
import ls_ui              # noqa: E402
import ls_geometry        # noqa: E402


# ---------------------------------------------------------------------------
# Command plugin
# ---------------------------------------------------------------------------

class CreateLSRelativisticCameraRig(c4d.plugins.CommandData):
    """
    Menu command that builds the LS Relativistic Camera Rig.

    Execute() is called by Cinema 4D when the user clicks the menu item or
    triggers the assigned shortcut. We delegate the heavy lifting to
    ls_rig.build_rig() and translate any exception into a user-visible
    error dialog so the plugin never crashes the host application.
    """

    def Execute(self, doc):
        if doc is None:
            doc = c4d.documents.GetActiveDocument()

        if doc is None:
            ls_ui.error("No active document. Open or create a scene first.")
            return False

        try:
            result = ls_rig.build_rig(doc)
        except Exception as exc:
            # Print full traceback to the Python console for debugging,
            # then surface a friendly message to the user.
            traceback.print_exc()
            ls_ui.error(
                "Failed to create the relativistic camera rig:\n\n{0}".format(exc)
            )
            return False

        ls_ui.status(
            "Created '{0}' under '{1}'.".format(
                result["camera"].GetName(),
                result["rig_null"].GetName(),
            )
        )
        return True

    def GetState(self, doc):
        # Enable the menu item whenever a document is open.
        if doc is None:
            return 0
        return c4d.CMD_ENABLED


class AddRelativisticGeometryProxy(c4d.plugins.CommandData):
    """Menu command: wrap selected (or all) objects in LS_Geometry_Proxy."""

    def Execute(self, doc):
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if doc is None:
            ls_ui.error("No active document.")
            return False
        try:
            ls_geometry.add_geometry_proxy(doc)
        except Exception as exc:
            traceback.print_exc()
            ls_ui.error("Add Geometry Proxy failed:\n\n{0}".format(exc))
            return False
        return True

    def GetState(self, doc):
        if doc is None:
            return 0
        return c4d.CMD_ENABLED


class RemoveRelativisticGeometryProxy(c4d.plugins.CommandData):
    """Menu command: unwrap LS_Geometry_Proxy and restore world transforms."""

    def Execute(self, doc):
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if doc is None:
            ls_ui.error("No active document.")
            return False
        try:
            ls_geometry.remove_geometry_proxy(doc)
        except Exception as exc:
            traceback.print_exc()
            ls_ui.error("Remove Geometry Proxy failed:\n\n{0}".format(exc))
            return False
        return True

    def GetState(self, doc):
        if doc is None:
            return 0
        # Grey the menu out when there's no proxy to remove.
        return (c4d.CMD_ENABLED if ls_geometry.find_existing_proxy(doc) is not None
                else 0)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def _register_one(plugin_id, name, help_text, dat):
    """Register a single CommandData plugin and log the result."""
    ok = c4d.plugins.RegisterCommandPlugin(
        id=plugin_id,
        str=name,
        info=0,
        icon=None,            # TODO: ship a 32x32 icon in res/ and load it here.
        help=help_text,
        dat=dat,
    )
    if ok:
        print("[C4D_ls-cam] Registered command id={0} ({1}).".format(plugin_id, name))
    else:
        print(
            "[C4D_ls-cam] FAILED to register command id={0} ({1}). "
            "Is the ID already in use?".format(plugin_id, name)
        )
    return ok


def _register():
    """Register every CommandData plugin shipped by C4D_ls-cam."""
    _register_one(K.PLUGIN_ID, K.COMMAND_NAME, K.COMMAND_HELP,
                  CreateLSRelativisticCameraRig())
    _register_one(K.PLUGIN_ID_GEOM_PROXY_ADD, K.GEOM_PROXY_ADD_NAME,
                  K.GEOM_PROXY_ADD_HELP, AddRelativisticGeometryProxy())
    _register_one(K.PLUGIN_ID_GEOM_PROXY_REMOVE, K.GEOM_PROXY_REMOVE_NAME,
                  K.GEOM_PROXY_REMOVE_HELP, RemoveRelativisticGeometryProxy())


if __name__ == "__main__":
    _register()
