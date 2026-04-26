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
import ls_doppler_materials  # noqa: E402
import ls_evaluator       # noqa: E402
import ls_presets         # noqa: E402


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


def _doc_has_doppler_duplicates(doc):
    """True if *doc* contains at least one LS_Doppler_* duplicate material."""
    if doc is None:
        return False
    m = doc.GetFirstMaterial()
    while m is not None:
        if ls_doppler_materials.is_doppler_duplicate(m):
            return True
        m = m.GetNext()
    return False


class AddDopplerMaterialController(c4d.plugins.CommandData):
    """Menu command: duplicate selected materials as LS_Doppler_<name>."""

    def Execute(self, doc):
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if doc is None:
            ls_ui.error("No active document.")
            return False
        try:
            ls_doppler_materials.add_doppler_controller(doc)
        except Exception as exc:
            traceback.print_exc()
            ls_ui.error("Add Doppler Material Controller failed:\n\n{0}".format(exc))
            return False
        return True

    def GetState(self, doc):
        if doc is None:
            return 0
        return c4d.CMD_ENABLED


class RestoreOriginalMaterials(c4d.plugins.CommandData):
    """Menu command: re-point texture tags to originals + delete duplicates."""

    def Execute(self, doc):
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if doc is None:
            ls_ui.error("No active document.")
            return False
        try:
            ls_doppler_materials.restore_original_materials(doc)
        except Exception as exc:
            traceback.print_exc()
            ls_ui.error("Restore Original Materials failed:\n\n{0}".format(exc))
            return False
        return True

    def GetState(self, doc):
        if doc is None:
            return 0
        # Grey the menu out when there are no Doppler duplicates.
        return c4d.CMD_ENABLED if _doc_has_doppler_duplicates(doc) else 0


# ---------------------------------------------------------------------------
# Preset dialog + command
# ---------------------------------------------------------------------------

class _PresetDialog(c4d.gui.GeDialog):
    """
    Modeless dialog with a preset dropdown plus Apply / Reset buttons.

    The dialog itself is owned by :class:`ApplyRelativityPreset` so it
    can be re-shown without rebuilding the layout each time the user
    picks the menu item.
    """

    GADGET_COMBO = 1000
    GADGET_APPLY = 1001
    GADGET_RESET = 1002

    def CreateLayout(self):
        self.SetTitle("LS Cam: Apply Relativity Preset")
        if self.GroupBegin(id=2000, flags=c4d.BFH_SCALEFIT, cols=1, rows=3):
            self.GroupBorderSpace(8, 8, 8, 8)

            self.AddStaticText(0, c4d.BFH_LEFT, name="Preset:")

            self.AddComboBox(self.GADGET_COMBO,
                             c4d.BFH_SCALEFIT | c4d.BFV_TOP,
                             initw=260)
            for i, name in enumerate(ls_presets.list_preset_names()):
                self.AddChild(self.GADGET_COMBO, i, name)

            if self.GroupBegin(id=2001,
                               flags=c4d.BFH_SCALEFIT | c4d.BFV_TOP,
                               cols=2, rows=1):
                self.AddButton(self.GADGET_APPLY, c4d.BFH_SCALEFIT,
                               name="Apply")
                self.AddButton(self.GADGET_RESET, c4d.BFH_SCALEFIT,
                               name="Reset")
                self.GroupEnd()
        self.GroupEnd()
        return True

    def InitValues(self):
        # Reset selection to the first preset every time the dialog is
        # opened so the user always sees a clean starting state.
        self.SetInt32(self.GADGET_COMBO, 0)
        return True

    def Command(self, id, msg):
        if id == self.GADGET_APPLY:
            self._handle_apply()
        elif id == self.GADGET_RESET:
            self._handle_reset()
        return True

    # -- handlers -------------------------------------------------------

    def _handle_apply(self):
        doc = c4d.documents.GetActiveDocument()
        if doc is None:
            ls_ui.error("No active document.")
            return

        rig, camera, controller = ls_rig.find_rig_in_document(doc)
        if controller is None:
            ls_ui.error(
                "No LS_Camera_Rig found. Run 'Create LS Relativistic "
                "Camera Rig' first."
            )
            return

        names = ls_presets.list_preset_names()
        sel = self.GetInt32(self.GADGET_COMBO)
        if sel < 0 or sel >= len(names):
            ls_ui.error("No preset selected.")
            return
        preset_name = names[sel]

        try:
            written = ls_presets.apply_preset(controller, preset_name)
        except Exception as exc:
            traceback.print_exc()
            ls_ui.error("Apply preset failed:\n\n{0}".format(exc))
            return

        ls_ui.status("Applied preset '{0}' ({1} field(s) written).".format(
            preset_name, written))

    def _handle_reset(self):
        doc = c4d.documents.GetActiveDocument()
        if doc is None:
            ls_ui.error("No active document.")
            return

        rig, camera, controller = ls_rig.find_rig_in_document(doc)
        if controller is None or camera is None:
            ls_ui.error(
                "No LS_Camera_Rig found. Run 'Create LS Relativistic "
                "Camera Rig' first."
            )
            return

        try:
            ls_evaluator.reset_ls_camera_rig(doc, controller, camera)
        except Exception as exc:
            traceback.print_exc()
            ls_ui.error("Reset failed:\n\n{0}".format(exc))
            return

        ls_ui.status("Reset relativistic camera rig to baseline.")


class ApplyRelativityPreset(c4d.plugins.CommandData):
    """Menu command: open the preset dialog (modeless / async)."""

    # CommandData instances are created once at registration time and
    # reused for every menu click, so caching the dialog here gives us
    # singleton-by-construction without any module-level globals.
    def __init__(self):
        self._dialog = None

    def Execute(self, doc):
        try:
            if self._dialog is None:
                self._dialog = _PresetDialog()
            self._dialog.Open(c4d.DLG_TYPE_ASYNC,
                              pluginid=K.PLUGIN_ID_PRESETS,
                              defaultw=320, defaulth=140)
        except Exception as exc:
            traceback.print_exc()
            ls_ui.error("Open preset dialog failed:\n\n{0}".format(exc))
            return False
        return True

    def GetState(self, doc):
        if doc is None:
            return 0
        return c4d.CMD_ENABLED

    def RestoreLayout(self, sec_ref):
        # Required for async dialogs to survive layout changes /
        # reload Python plugins.
        if self._dialog is None:
            self._dialog = _PresetDialog()
        return self._dialog.Restore(pluginid=K.PLUGIN_ID_PRESETS,
                                    secret=sec_ref)


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
    _register_one(K.PLUGIN_ID_DOPPLER_MAT_ADD, K.DOPPLER_MAT_ADD_NAME,
                  K.DOPPLER_MAT_ADD_HELP, AddDopplerMaterialController())
    _register_one(K.PLUGIN_ID_DOPPLER_MAT_RESTORE, K.DOPPLER_MAT_RESTORE_NAME,
                  K.DOPPLER_MAT_RESTORE_HELP, RestoreOriginalMaterials())
    _register_one(K.PLUGIN_ID_PRESETS, K.PRESETS_NAME,
                  K.PRESETS_HELP, ApplyRelativityPreset())


if __name__ == "__main__":
    _register()
