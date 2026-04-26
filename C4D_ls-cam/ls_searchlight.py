"""
ls_searchlight.py
=================
Relativistic-beaming ("searchlight" / "headlight") visual approximation.

For each *controlled* object the evaluator calls
:func:`apply_searchlight`, which estimates the angle between the camera
forward axis and the line of sight to the object, computes
``RM.searchlight_intensity_factor(beta, cos_theta, strength)``, clamps
it to the user-supplied ``max_intensity_multiplier`` ceiling, and writes
the result into one of three places depending on the active mode:

  * **Viewport Only** -- per-object ``ID_BASEOBJECT_USECOLOR`` /
    ``ID_BASEOBJECT_COLOR``. Cheap, always available, viewport-only.
  * **Material Luminance** -- enables the luminance channel on every
    ``LS_Doppler_<x>`` material clone and writes
    ``MATERIAL_LUMINANCE_COLOR``. Renders in production, but only
    affects materials that have already been wrapped via the Doppler
    pass.
  * **Octane Material Placeholder** -- one-shot logged no-op. Hooking
    Octane node-material emission is left as a TODO until the Octane
    material params are mapped (the camera-tag mapping is the only
    Octane mapping currently surfaced).

Reversibility
-------------
Every modified target is stamped with its original value (object
USECOLOR + COLOR, or material luminance flag + colour) in private
BaseContainer slots **before** the first write. Switching modes,
disabling the effect, or calling :func:`restore_searchlight` walks
every stamped target and writes the baseline back. Markers are then
cleared so a subsequent re-enable re-captures from the now-restored
state -- the user can edit baselines while the effect is off and the
plugin will respect the new baselines.

Controlled-object set
---------------------
"Controlled object" is intentionally restricted -- we never paint the
whole scene. The set is the union of:

    * the children of ``LS_Geometry_Proxy`` (if it exists), and
    * any object whose texture tags reference an ``LS_Doppler_<x>``
      material clone.

If neither system has been used the searchlight effect is a no-op.
This matches the brief's notion of "controlled objects" -- objects
that have already been opted into the rig system.
"""

import c4d

import ls_constants as K
import ls_doppler_materials
import ls_geometry
import ls_relativity_math as RM
import ls_ui


# ---------------------------------------------------------------------------
# Private BaseContainer slots used to stash baselines.
# ---------------------------------------------------------------------------
# Distinct from the doppler-materials slots so the two systems can co-
# exist on the same material without clobbering each other.
_BC_KEY_OBJ_USECOLOR_BASELINE = 1300   # int  -- saved ID_BASEOBJECT_USECOLOR
_BC_KEY_OBJ_COLOR_BASELINE = 1301      # vec  -- saved ID_BASEOBJECT_COLOR
_BC_KEY_OBJ_HAS_BASELINE = 1302        # int  -- 1 once viewport baseline stored

_BC_KEY_MAT_USE_LUMI_BASELINE = 1310   # int  -- saved MATERIAL_USE_LUMINANCE
_BC_KEY_MAT_LUMI_COLOR_BASELINE = 1311 # vec  -- saved MATERIAL_LUMINANCE_COLOR
_BC_KEY_MAT_HAS_LUMI_BASELINE = 1312   # int  -- 1 once luminance baseline stored


# ---------------------------------------------------------------------------
# C4D version compatibility for the USECOLOR enum.
# ---------------------------------------------------------------------------
# Older builds expose the explicit constant; very old builds didn't. The
# integer values are stable: 0 = off, 1 = automatic, 2 = always.
_USECOLOR_OFF = getattr(c4d, "ID_BASEOBJECT_USECOLOR_OFF", 0)
_USECOLOR_ALWAYS = getattr(c4d, "ID_BASEOBJECT_USECOLOR_ALWAYS", 2)


# ---------------------------------------------------------------------------
# Once-per-session log gate for the Octane placeholder.
# ---------------------------------------------------------------------------
_OCTANE_PLACEHOLDER_LOGGED = False


# ---------------------------------------------------------------------------
# Iterators (mirror ls_doppler_materials but local to this module so the
# searchlight pass doesn't pull in private helpers).
# ---------------------------------------------------------------------------

def _iter_objects(doc):
    if doc is None:
        return
    stack = []
    obj = doc.GetFirstObject()
    while obj is not None:
        stack.append(obj)
        obj = obj.GetNext()
    while stack:
        cur = stack.pop()
        yield cur
        c = cur.GetDown()
        while c is not None:
            stack.append(c)
            c = c.GetNext()


def _iter_materials(doc):
    if doc is None:
        return
    m = doc.GetFirstMaterial()
    while m is not None:
        yield m
        m = m.GetNext()


def _iter_doppler_duplicates(doc):
    for m in _iter_materials(doc):
        if ls_doppler_materials.is_doppler_duplicate(m):
            yield m


def _objects_using_material(doc, mat):
    out = []
    for obj in _iter_objects(doc):
        tag = obj.GetFirstTag()
        while tag is not None:
            if tag.GetType() == c4d.Ttexture:
                try:
                    ref = tag[c4d.TEXTURETAG_MATERIAL]
                except Exception:
                    ref = None
                if ref is mat:
                    out.append(obj)
                    break
            tag = tag.GetNext()
    return out


# ---------------------------------------------------------------------------
# Controlled-object set
# ---------------------------------------------------------------------------

def _gather_controlled_objects(doc):
    """
    Return the deduplicated set of objects we are allowed to recolour.

    Sources combined: geometry-proxy children + objects whose texture
    tags reference an LS_Doppler_<x> material. Returned as a list with
    stable iteration order; we use ``id()`` for dedup since BaseObject
    is hashable but we want to be explicit.
    """
    seen = set()
    out = []

    proxy = ls_geometry.find_existing_proxy(doc)
    if proxy is not None:
        c = proxy.GetDown()
        while c is not None:
            key = id(c)
            if key not in seen:
                seen.add(key)
                out.append(c)
            c = c.GetNext()

    # Collect duplicate -> users mapping once to avoid O(N*M) re-walks.
    duplicates = list(_iter_doppler_duplicates(doc))
    if duplicates:
        for obj in _iter_objects(doc):
            tag = obj.GetFirstTag()
            hit = False
            while tag is not None:
                if tag.GetType() == c4d.Ttexture:
                    try:
                        ref = tag[c4d.TEXTURETAG_MATERIAL]
                    except Exception:
                        ref = None
                    if ref is not None and ref in duplicates:
                        hit = True
                        break
                tag = tag.GetNext()
            if hit:
                key = id(obj)
                if key not in seen:
                    seen.add(key)
                    out.append(obj)

    return out


# ---------------------------------------------------------------------------
# Velocity-axis resolution (mirrors ls_doppler_materials)
# ---------------------------------------------------------------------------

def _resolve_forward_and_pos(controller, camera):
    """Return (forward_unit_vector, camera_world_pos)."""
    axis_source = K.AXIS_SOURCE_CAMERA_FORWARD
    custom_vec = c4d.Vector(0.0, 0.0, 1.0)
    if controller is not None:
        try:
            for desc_id, bc in controller.GetUserDataContainer():
                name = bc[c4d.DESC_NAME]
                if name == K.UD_LABELS[K.UD_VELOCITY_AXIS_SOURCE]:
                    try:
                        axis_source = int(controller[desc_id])
                    except Exception:
                        pass
                elif name == K.UD_LABELS[K.UD_VELOCITY_CUSTOM_VECTOR]:
                    try:
                        custom_vec = controller[desc_id] or custom_vec
                    except Exception:
                        pass
        except Exception:
            pass
    forward = ls_geometry.resolve_velocity_axis(camera, axis_source, custom_vec)
    cam_pos = camera.GetMg().off if camera is not None else c4d.Vector(0.0, 0.0, 0.0)
    return forward, cam_pos


def _cos_theta_for_position(forward, cam_pos, target_pos):
    """Compute clamped dot(forward, normalised(target - camera))."""
    look = target_pos - cam_pos
    if look.GetLength() < 1.0e-9:
        return 0.0
    cos_theta = forward * look.GetNormalized()
    if cos_theta > 1.0:
        return 1.0
    if cos_theta < -1.0:
        return -1.0
    return cos_theta


# ---------------------------------------------------------------------------
# Baseline capture / restore -- viewport mode
# ---------------------------------------------------------------------------

def _ensure_object_baseline(obj):
    """Stamp baseline USECOLOR + COLOR onto *obj* (once)."""
    bc = obj.GetDataInstance()
    if bc is None:
        return
    try:
        if bc.GetInt32(_BC_KEY_OBJ_HAS_BASELINE):
            return
    except Exception:
        pass
    try:
        use = obj[c4d.ID_BASEOBJECT_USECOLOR]
    except Exception:
        use = _USECOLOR_OFF
    try:
        col = obj[c4d.ID_BASEOBJECT_COLOR]
    except Exception:
        col = c4d.Vector(1.0, 1.0, 1.0)
    if not isinstance(col, c4d.Vector):
        col = c4d.Vector(1.0, 1.0, 1.0)
    try:
        bc.SetInt32(_BC_KEY_OBJ_USECOLOR_BASELINE, int(use))
        bc.SetVector(_BC_KEY_OBJ_COLOR_BASELINE, col)
        bc.SetInt32(_BC_KEY_OBJ_HAS_BASELINE, 1)
    except Exception:
        pass


def _restore_one_object(obj):
    """Write baseline values back to *obj* and clear the marker."""
    bc = obj.GetDataInstance()
    if bc is None:
        return False
    try:
        if not bc.GetInt32(_BC_KEY_OBJ_HAS_BASELINE):
            return False
    except Exception:
        return False
    try:
        use = bc.GetInt32(_BC_KEY_OBJ_USECOLOR_BASELINE)
        col = bc.GetVector(_BC_KEY_OBJ_COLOR_BASELINE)
        try:
            obj[c4d.ID_BASEOBJECT_USECOLOR] = int(use)
        except Exception:
            pass
        try:
            obj[c4d.ID_BASEOBJECT_COLOR] = col
        except Exception:
            pass
    except Exception:
        pass
    try:
        bc.SetInt32(_BC_KEY_OBJ_HAS_BASELINE, 0)
    except Exception:
        pass
    return True


def _restore_object_colors(doc):
    """Restore every stamped object in *doc*. Returns count restored."""
    if doc is None:
        return 0
    n = 0
    for obj in _iter_objects(doc):
        if _restore_one_object(obj):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Baseline capture / restore -- material luminance mode
# ---------------------------------------------------------------------------

def _ensure_material_lumi_baseline(mat):
    bc = mat.GetDataInstance()
    if bc is None:
        return
    try:
        if bc.GetInt32(_BC_KEY_MAT_HAS_LUMI_BASELINE):
            return
    except Exception:
        pass
    try:
        use = mat[c4d.MATERIAL_USE_LUMINANCE]
    except Exception:
        use = False
    try:
        col = mat[c4d.MATERIAL_LUMINANCE_COLOR]
    except Exception:
        col = c4d.Vector(0.0, 0.0, 0.0)
    if not isinstance(col, c4d.Vector):
        col = c4d.Vector(0.0, 0.0, 0.0)
    try:
        bc.SetInt32(_BC_KEY_MAT_USE_LUMI_BASELINE, 1 if use else 0)
        bc.SetVector(_BC_KEY_MAT_LUMI_COLOR_BASELINE, col)
        bc.SetInt32(_BC_KEY_MAT_HAS_LUMI_BASELINE, 1)
    except Exception:
        pass


def _restore_one_material(mat):
    bc = mat.GetDataInstance()
    if bc is None:
        return False
    try:
        if not bc.GetInt32(_BC_KEY_MAT_HAS_LUMI_BASELINE):
            return False
    except Exception:
        return False
    try:
        use = bool(bc.GetInt32(_BC_KEY_MAT_USE_LUMI_BASELINE))
        col = bc.GetVector(_BC_KEY_MAT_LUMI_COLOR_BASELINE)
        try:
            mat[c4d.MATERIAL_USE_LUMINANCE] = use
        except Exception:
            pass
        try:
            mat[c4d.MATERIAL_LUMINANCE_COLOR] = col
        except Exception:
            pass
    except Exception:
        pass
    try:
        bc.SetInt32(_BC_KEY_MAT_HAS_LUMI_BASELINE, 0)
    except Exception:
        pass
    return True


def _restore_material_luminance(doc):
    if doc is None:
        return 0
    n = 0
    for mat in _iter_materials(doc):
        if _restore_one_material(mat):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Public restore -- both modes
# ---------------------------------------------------------------------------

def restore_searchlight(doc):
    """
    Restore every stamped baseline (objects + materials) in *doc*.

    Returns ``(objects_restored, materials_restored)``. Cheap if there
    are no markers (the iterators just walk the scene/material list).
    """
    return _restore_object_colors(doc), _restore_material_luminance(doc)


# ---------------------------------------------------------------------------
# Mode dispatchers
# ---------------------------------------------------------------------------

def _clamp_factor(factor, max_intensity):
    """Clamp the searchlight factor to [0, max_intensity]."""
    if factor < 0.0:
        return 0.0
    if factor > max_intensity:
        return max_intensity
    return factor


def _apply_viewport_mode(doc, controller, camera, beta, strength,
                         max_intensity, debug):
    """Drive ID_BASEOBJECT_USECOLOR / COLOR on each controlled object."""
    # Make sure no luminance baselines are still active from a previous
    # mode -- restore is a no-op if there are none.
    _restore_material_luminance(doc)

    forward, cam_pos = _resolve_forward_and_pos(controller, camera)
    targets = _gather_controlled_objects(doc)
    if not targets:
        if debug:
            print("[searchlight][debug] viewport: no controlled objects "
                  "(no proxy and no Doppler material users).")
        return 0

    n = 0
    for obj in targets:
        cos_theta = _cos_theta_for_position(forward, cam_pos, obj.GetMg().off)
        factor = RM.searchlight_intensity_factor(beta, cos_theta, strength=strength)
        factor = _clamp_factor(factor, max_intensity)

        _ensure_object_baseline(obj)
        bc = obj.GetDataInstance()
        try:
            base = bc.GetVector(_BC_KEY_OBJ_COLOR_BASELINE)
        except Exception:
            base = c4d.Vector(1.0, 1.0, 1.0)
        if not isinstance(base, c4d.Vector):
            base = c4d.Vector(1.0, 1.0, 1.0)

        # Tint baseline by factor; always clamp per channel to [0, 1] so
        # the viewport never receives out-of-gamut colours that some
        # hosts handle inconsistently.
        new_color = c4d.Vector(
            min(1.0, max(0.0, base.x * factor)),
            min(1.0, max(0.0, base.y * factor)),
            min(1.0, max(0.0, base.z * factor)),
        )
        try:
            obj[c4d.ID_BASEOBJECT_USECOLOR] = _USECOLOR_ALWAYS
            obj[c4d.ID_BASEOBJECT_COLOR] = new_color
        except Exception:
            continue

        n += 1
        if debug:
            print("[searchlight][debug] viewport {0}: cos_theta={1:+.4f} "
                  "factor={2:.4g} color={3}".format(
                      obj.GetName(), cos_theta, factor, new_color))
    return n


def _apply_luminance_mode(doc, controller, camera, beta, strength,
                          max_intensity, debug):
    """
    Enable + drive the luminance channel on each LS_Doppler_<x> clone.

    cos_theta is computed from the centroid of the objects that use the
    clone (same convention the Doppler colour shift uses). This is a
    deliberate simplification -- per-object luminance overrides would
    require per-tag overrides which are out of scope for the skeleton.
    """
    # Restore the other mode's baselines first.
    _restore_object_colors(doc)

    forward, cam_pos = _resolve_forward_and_pos(controller, camera)
    duplicates = list(_iter_doppler_duplicates(doc))
    if not duplicates:
        if debug:
            print("[searchlight][debug] luminance: no LS_Doppler_* "
                  "materials -- run 'LS Cam: Add Doppler Material "
                  "Controller' first.")
        return 0

    n = 0
    for mat in duplicates:
        if mat.GetType() != c4d.Mmaterial:
            # Octane / Redshift / etc. -- handled in the dedicated
            # placeholder mode, not here.
            continue
        users = _objects_using_material(doc, mat)
        if not users:
            continue
        centroid = c4d.Vector(0.0, 0.0, 0.0)
        for u in users:
            centroid += u.GetMg().off
        centroid /= float(len(users))

        cos_theta = _cos_theta_for_position(forward, cam_pos, centroid)
        factor = RM.searchlight_intensity_factor(beta, cos_theta, strength=strength)
        factor = _clamp_factor(factor, max_intensity)

        _ensure_material_lumi_baseline(mat)

        # The luminance channel is additive on top of the colour
        # channel. We treat factor==1 as "no extra glow" and only emit
        # when factor > 1; below 1 we simply leave the channel at zero
        # (the Doppler colour shift will already darken receding
        # surfaces via MATERIAL_COLOR_COLOR).
        glow = max(0.0, factor - 1.0)

        # Use the live colour channel as the glow tint so the emission
        # tracks the Doppler shift naturally.
        try:
            tint = mat[c4d.MATERIAL_COLOR_COLOR]
        except Exception:
            tint = c4d.Vector(1.0, 1.0, 1.0)
        if not isinstance(tint, c4d.Vector):
            tint = c4d.Vector(1.0, 1.0, 1.0)

        glow_color = c4d.Vector(tint.x * glow, tint.y * glow, tint.z * glow)
        try:
            mat[c4d.MATERIAL_USE_LUMINANCE] = True
            mat[c4d.MATERIAL_LUMINANCE_COLOR] = glow_color
        except Exception:
            continue

        n += 1
        if debug:
            print("[searchlight][debug] luminance {0}: cos_theta={1:+.4f} "
                  "factor={2:.4g} glow={3}".format(
                      mat.GetName(), cos_theta, factor, glow_color))
    return n


def _apply_octane_placeholder_mode(doc, debug):
    """One-shot logged no-op until Octane node-material emission is mapped."""
    global _OCTANE_PLACEHOLDER_LOGGED
    # Restore other modes' baselines so nothing keeps drifting while
    # this mode is active.
    _restore_object_colors(doc)
    _restore_material_luminance(doc)
    if not _OCTANE_PLACEHOLDER_LOGGED:
        _OCTANE_PLACEHOLDER_LOGGED = True
        ls_ui.log(
            "Searchlight mode 'Octane Material Placeholder' is not "
            "implemented yet -- node-material emission slots need to be "
            "mapped per Octane version (TODO in ls_searchlight.py)."
        )
    if debug:
        print("[searchlight][debug] octane-placeholder: no-op")
    return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_searchlight(doc, controller, camera, beta, strength, mode,
                      max_intensity, debug=False):
    """
    Drive the searchlight effect for the active mode.

    Parameters
    ----------
    doc : c4d.documents.BaseDocument
    controller : c4d.BaseTag or None
        Source of the velocity-axis settings.
    camera : c4d.BaseObject or None
    beta : float
        Already clamped by the caller via :func:`clamp_beta`.
    strength : float
        Compounded ``searchlight_strength * effect_strength``; we floor
        at 0 here defensively.
    mode : int
        One of ``K.SEARCHLIGHT_MODE_*``. Unknown values fall through to
        a logged no-op.
    max_intensity : float
        Upper clamp on the per-target factor. Defaulted to
        ``K.UD_RANGES[K.UD_MAX_INTENSITY_MULTIPLIER][2]`` (= 10) by the
        evaluator; floored at 1.0 here so factor==0 isn't possible.
    debug : bool
        Print per-target ``cos_theta`` + factor lines.

    Returns the number of targets touched.
    """
    if doc is None:
        return 0
    if strength < 0.0:
        strength = 0.0
    if max_intensity < 1.0:
        max_intensity = 1.0

    if mode == K.SEARCHLIGHT_MODE_VIEWPORT:
        return _apply_viewport_mode(doc, controller, camera, beta,
                                    strength, max_intensity, debug)
    if mode == K.SEARCHLIGHT_MODE_LUMINANCE:
        return _apply_luminance_mode(doc, controller, camera, beta,
                                     strength, max_intensity, debug)
    if mode == K.SEARCHLIGHT_MODE_OCTANE:
        return _apply_octane_placeholder_mode(doc, debug)

    # Unknown mode value: bail out cleanly and restore so we never
    # silently leave the scene in a half-modified state.
    restore_searchlight(doc)
    if debug:
        print("[searchlight][debug] unknown mode={0}; restored.".format(mode))
    return 0
