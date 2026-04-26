"""
ls_diagnostics.py
=================
Viewport / render diagnostic helpers.

Two independent features live here:

1. **HUD-style overlay.** A null parented under the LS camera
   (``LS_Diagnostic_Overlay``) holding one ``Osplinetext`` child per
   live readout (beta / gamma / contraction / Doppler forward /
   searchlight). Created and destroyed by the **Toggle Diagnostic
   Overlay** menu command; updated every tick by the evaluator via
   :func:`update_overlay`. Per-text caching skips spline regeneration
   when the value didn't change between ticks, which keeps the
   per-frame cost bounded in medium scenes.

2. **Debug material preview.** A bool user-data flag
   (``debug_material_preview``) that, when on, overrides every
   ``LS_Doppler_<x>`` clone's ``MATERIAL_COLOR_COLOR`` with a
   ``cos(theta)`` heatmap (red = receding, green = perpendicular,
   blue = approaching). Intended for diagnosing which surfaces the
   rig considers in front of vs behind the motion vector. Off by
   default, so the production render path is untouched until the
   user opts in.

Both features are non-destructive:

* The overlay is a single null + a handful of text-spline children
  parented under the camera. Toggling it off deletes only those
  objects and is undoable in one step.
* The debug material preview only writes to ``LS_Doppler_<x>``
  duplicates -- never the originals -- and it doesn't store any
  baselines because the next tick of the evaluator will overwrite
  the colour anyway (the Doppler shift, the searchlight luminance,
  or the heatmap, depending on which flags are on). When
  ``debug_material_preview`` is turned off, the next tick lets the
  Doppler shift win again, so the duplicates revert automatically.
"""

import c4d

import ls_constants as K
import ls_doppler_materials
import ls_geometry
import ls_ui


# ---------------------------------------------------------------------------
# Layout / formatting constants
# ---------------------------------------------------------------------------

# Order matters: defines top-to-bottom row order in the viewport HUD.
# Each entry is (label_key, format_template, computed_dict_key).
_HUD_ROWS = (
    ("beta",        "beta = {0:.4f}",        "beta"),
    ("gamma",       "gamma = {0:.4f}",       "gamma"),
    ("contraction", "contraction = {0:.4f}", "contraction_factor"),
    ("doppler",     "doppler_fwd = {0:.4f}", "doppler_forward_factor"),
    ("searchlight", "searchlight = {0:.4g}", "searchlight_multiplier"),
)

# Stacked vertical offset between rows (C4D scene units).
_HUD_ROW_SPACING = 18.0

# Text-spline height. Small enough to fit five rows in a typical
# viewport, big enough to stay legible.
_HUD_TEXT_HEIGHT = 12.0

# Where to anchor the overlay relative to the camera. Negative Z places
# it in front of the camera (C4D cameras look along local -Z); the X/Y
# offsets push the stack to the bottom-left of the viewport so it
# doesn't obscure the centre framing.
_HUD_ANCHOR_OFFSET = c4d.Vector(-80.0, -45.0, -200.0)

# Private BC slot used to remember the last text written to a row, so
# we can skip the relatively expensive PRIM_TEXT_TEXT write (which
# triggers a spline rebuild) when the value didn't change.
_BC_KEY_LAST_TEXT = 1400


# ---------------------------------------------------------------------------
# Overlay discovery / creation / removal
# ---------------------------------------------------------------------------

def _row_object_name(row_key):
    return "ls_diag_" + row_key


def find_overlay(camera):
    """Return the ``LS_Diagnostic_Overlay`` null on *camera*, or None."""
    if camera is None:
        return None
    child = camera.GetDown()
    while child is not None:
        if (child.GetType() == c4d.Onull
                and child.GetName() == K.DIAGNOSTIC_OVERLAY_NAME):
            return child
        child = child.GetNext()
    return None


def create_overlay(doc, camera):
    """
    Build the overlay null + one text spline per row under *camera*.

    Returns the overlay null on success, ``None`` if it already
    existed or the camera is missing. Wrapped in a single undo step.
    """
    if doc is None or camera is None:
        return None
    if find_overlay(camera) is not None:
        return None

    doc.StartUndo()
    try:
        overlay = c4d.BaseObject(c4d.Onull)
        if overlay is None:
            doc.EndUndo()
            return None
        overlay.SetName(K.DIAGNOSTIC_OVERLAY_NAME)
        # Hide the null icon -- the visible thing is the text below it.
        overlay[c4d.NULLOBJECT_DISPLAY] = c4d.NULLOBJECT_DISPLAY_NONE
        overlay.InsertUnder(camera)
        overlay.SetMl(c4d.utils.MatrixMove(_HUD_ANCHOR_OFFSET))
        doc.AddUndo(c4d.UNDOTYPE_NEW, overlay)

        for i, (row_key, _fmt, _src) in enumerate(_HUD_ROWS):
            text = c4d.BaseObject(c4d.Osplinetext)
            if text is None:
                continue
            text.SetName(_row_object_name(row_key))
            try:
                text[c4d.PRIM_TEXT_TEXT] = "{0}: ...".format(row_key)
                text[c4d.PRIM_TEXT_HEIGHT] = _HUD_TEXT_HEIGHT
            except Exception:
                # Older builds may lack one of these IDs; the spline
                # still inserts and shows the default text.
                pass
            text.InsertUnder(overlay)
            text.SetMl(c4d.utils.MatrixMove(c4d.Vector(0.0,
                                                       -i * _HUD_ROW_SPACING,
                                                       0.0)))
            doc.AddUndo(c4d.UNDOTYPE_NEW, text)
    except Exception:
        doc.EndUndo()
        c4d.EventAdd()
        raise

    doc.EndUndo()
    c4d.EventAdd()
    return overlay


def remove_overlay(doc, camera):
    """Delete the overlay (and all rows) from *camera*. Returns True if removed."""
    if doc is None or camera is None:
        return False
    overlay = find_overlay(camera)
    if overlay is None:
        return False
    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_DELETE, overlay)
        overlay.Remove()
    except Exception:
        doc.EndUndo()
        c4d.EventAdd()
        raise
    doc.EndUndo()
    c4d.EventAdd()
    return True


def toggle_overlay(doc, camera):
    """Convenience: remove if present, create if absent. Returns True on add."""
    if find_overlay(camera) is not None:
        remove_overlay(doc, camera)
        return False
    create_overlay(doc, camera)
    return True


# ---------------------------------------------------------------------------
# Per-tick overlay update
# ---------------------------------------------------------------------------

def _format_row(fmt, value):
    try:
        return fmt.format(value)
    except (TypeError, ValueError):
        return fmt.format(0.0)


def update_overlay(camera, computed):
    """
    Refresh the HUD text from a *computed* dict (the evaluator's return
    value). Cheap when the overlay doesn't exist (single null walk).

    Per-row text is cached in a private BaseContainer slot on the text
    spline; we only call ``[c4d.PRIM_TEXT_TEXT] = ...`` (which forces a
    spline rebuild) when the formatted string actually changed.
    """
    overlay = find_overlay(camera)
    if overlay is None:
        return

    # Build a row_key -> formatted_text map once.
    text_for = {}
    for row_key, fmt, src_key in _HUD_ROWS:
        value = computed.get(src_key, 0.0) if computed else 0.0
        text_for[row_key] = _format_row(fmt, value)

    child = overlay.GetDown()
    while child is not None:
        name = child.GetName() or ""
        # Map name back to row_key.
        row_key = None
        for key, _fmt, _src in _HUD_ROWS:
            if name == _row_object_name(key):
                row_key = key
                break
        if row_key is None:
            child = child.GetNext()
            continue

        new_text = text_for.get(row_key, "")
        bc = child.GetDataInstance()
        last = ""
        if bc is not None:
            try:
                last = bc.GetString(_BC_KEY_LAST_TEXT) or ""
            except Exception:
                last = ""

        if new_text and new_text != last:
            try:
                child[c4d.PRIM_TEXT_TEXT] = new_text
            except Exception:
                pass
            if bc is not None:
                try:
                    bc.SetString(_BC_KEY_LAST_TEXT, new_text)
                except Exception:
                    pass

        child = child.GetNext()


# ---------------------------------------------------------------------------
# Debug material preview (cos-theta heatmap)
# ---------------------------------------------------------------------------

def _iter_doppler_duplicates(doc):
    if doc is None:
        return
    m = doc.GetFirstMaterial()
    while m is not None:
        if ls_doppler_materials.is_doppler_duplicate(m):
            yield m
        m = m.GetNext()


def _objects_using_material(doc, mat):
    """Mirror of the helper in ls_doppler_materials, kept local for isolation."""
    out = []
    if doc is None:
        return out
    stack = []
    obj = doc.GetFirstObject()
    while obj is not None:
        stack.append(obj)
        obj = obj.GetNext()
    while stack:
        cur = stack.pop()
        tag = cur.GetFirstTag()
        while tag is not None:
            if tag.GetType() == c4d.Ttexture:
                try:
                    ref = tag[c4d.TEXTURETAG_MATERIAL]
                except Exception:
                    ref = None
                if ref is mat:
                    out.append(cur)
                    break
            tag = tag.GetNext()
        c = cur.GetDown()
        while c is not None:
            stack.append(c)
            c = c.GetNext()
    return out


def _heatmap_color(cos_theta):
    """
    Map ``cos_theta`` in ``[-1, 1]`` to a debug-friendly RGB triple.

      cos_theta = +1 (approaching)  -> blue   (0, 0, 1)
      cos_theta =  0 (perpendicular) -> green (0, 1, 0)
      cos_theta = -1 (receding)     -> red    (1, 0, 0)

    We pick a piecewise-linear blend between adjacent stops so the
    middle band has predictable green that's easy to spot.
    """
    if cos_theta > 1.0:
        cos_theta = 1.0
    elif cos_theta < -1.0:
        cos_theta = -1.0

    if cos_theta >= 0.0:
        # green -> blue
        return c4d.Vector(0.0, 1.0 - cos_theta, cos_theta)
    # red -> green
    return c4d.Vector(-cos_theta, 1.0 + cos_theta, 0.0)


def apply_debug_material_preview(doc, controller, camera):
    """
    Override every classic ``LS_Doppler_<x>`` clone's colour with a
    cos-theta heatmap. Idempotent and bounded in cost (one walk per
    duplicate).

    The doppler / searchlight passes earlier in the evaluator have
    already touched these materials this tick, but the override here
    runs *after* them, so the heatmap wins. Toggling the flag off
    simply lets next tick's Doppler shift overwrite the heatmap.
    """
    if doc is None:
        return 0
    if camera is None:
        return 0

    forward = ls_geometry.camera_forward_vector(camera)
    cam_pos = camera.GetMg().off

    # The debug heatmap uses the camera-forward axis directly even if
    # the controller has a custom velocity vector. The whole point of
    # the preview is to show the rig's view from the camera, so going
    # through resolve_velocity_axis here would only obscure the
    # diagnostic.

    n = 0
    for mat in _iter_doppler_duplicates(doc):
        if mat.GetType() != c4d.Mmaterial:
            # Node-graph engines: skip silently. The Doppler pass logs
            # a one-shot warning in this case already.
            continue
        users = _objects_using_material(doc, mat)
        if not users:
            continue
        centroid = c4d.Vector(0.0, 0.0, 0.0)
        for u in users:
            centroid += u.GetMg().off
        centroid /= float(len(users))

        look = centroid - cam_pos
        if look.GetLength() < 1.0e-9:
            cos_theta = 0.0
        else:
            cos_theta = forward * look.GetNormalized()
            if cos_theta > 1.0:
                cos_theta = 1.0
            elif cos_theta < -1.0:
                cos_theta = -1.0

        try:
            mat[c4d.MATERIAL_COLOR_COLOR] = _heatmap_color(cos_theta)
        except Exception:
            continue
        n += 1
    return n
