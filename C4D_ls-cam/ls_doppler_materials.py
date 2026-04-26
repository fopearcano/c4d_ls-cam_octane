"""
ls_doppler_materials.py
=======================
Non-destructive Doppler colour-shift system for scene materials.

User flow
---------
1. The user selects scene objects (in the Object Manager) and/or materials
   (in the Material Manager).
2. The user runs **LS Cam: Add Doppler Material Controller**, which calls
   :func:`add_doppler_controller`. For every "affected" material (a
   classic C4D ``Mmaterial`` referenced by a selected object's texture
   tag, or directly selected in the Material Manager), the plugin:

       a. Clones the material.
       b. Renames the clone ``LS_Doppler_<OriginalName>``.
       c. Stores the original material's name and baseline RGB in the
          clone's BaseContainer (private slots), so we can both undo the
          duplication and reset the colour later.
       d. Walks every texture tag in the document that pointed at the
          original and re-points it at the clone.

   Every step is wrapped in a single undo block. The original materials
   stay in the document untouched.

3. On every scene evaluation the controller's Python tag calls
   :func:`apply_doppler_color_shift`. For each ``LS_Doppler_*`` clone it
   estimates the line of sight to the average position of the objects
   that use the clone, computes the relativistic Doppler factor for that
   direction, and writes a wavelength-shifted colour into the clone's
   ``MATERIAL_COLOR_COLOR`` channel. Approaching objects trend bluer,
   receding objects trend redder.

4. To undo, the user runs **LS Cam: Restore Original Materials**, which
   calls :func:`restore_original_materials`. Every texture tag pointing
   at an ``LS_Doppler_*`` clone is repointed at the original (looked up
   by the stored name); every clone is then deleted.

What is NOT in this pass
------------------------
* Octane / Redshift / Arnold node-graph materials. Their colour lives
  in shader nodes, not on a single ``MATERIAL_COLOR_COLOR`` channel, so
  patching them safely requires per-engine code. We still **clone** non-
  classic materials (so the structure is identical and restore works),
  but the per-tick colour write is gated to ``Mmaterial`` and a single
  warning is logged the first time we see another type.

  TODO: implement per-engine colour shift for Octane node materials,
  Redshift node materials, and Arnold standard surfaces.
* Texture / gradient / multi-shader chains. We only patch the flat
  colour channel; baseline-textured materials will look approximately
  shifted via the colour multiplier but will not have their textures
  re-tinted spectrum-correctly.

Classification:
    [PHYSICAL]      -- ``RM.doppler_factor(beta, cos_theta)``;
                       cos_theta from forward . line-of-sight in the
                       observer frame.
    [ARTISTIC]      -- ``RM.wavelength_shift_rgb_approx``: the
                       R<->G<->B cascade tinted by the strength
                       slider. Visually consistent with blueshift /
                       redshift but not a spectral renderer.
    [UNIMPLEMENTED] -- spectrum-correct shift on textured / node-
                       graph materials; per-engine colour writes for
                       Octane / Redshift / Arnold (see TODO above).
"""

import c4d

import ls_constants as K
import ls_geometry
import ls_relativity_math as RM
import ls_ui


# ---------------------------------------------------------------------------
# Private BaseContainer slots used on the duplicate materials.
# ---------------------------------------------------------------------------
# These integer keys are scoped to the duplicate's data instance, so they
# don't conflict with anything Maxon (or third-party render engines) put
# in their own BaseContainers. Keep the values stable across releases.
_BC_KEY_ORIG_NAME = 1200       # str  -- the original material's name
_BC_KEY_BASE_COLOR = 1201      # vec  -- baseline MATERIAL_COLOR_COLOR
_BC_KEY_ORIG_TYPE = 1202       # int  -- the original material's GetType()


# ---------------------------------------------------------------------------
# Logging gate so we only print "non-classic material skipped" once per
# session per material type. Module-level state is fine because it just
# avoids console spam; correctness doesn't depend on it.
# ---------------------------------------------------------------------------
_NON_CLASSIC_LOGGED = set()


def _is_classic_material(mat):
    """Return True if *mat* is a stock Cinema 4D ``Mmaterial``."""
    return mat is not None and mat.GetType() == c4d.Mmaterial


def is_doppler_duplicate(mat):
    """
    Return True if *mat* is a clone created by :func:`add_doppler_controller`.

    We require BOTH the name prefix and the private marker slot in the
    BaseContainer, so a user-named ``LS_Doppler_MyShinyThing`` material
    is never deleted by the restore command.
    """
    if mat is None:
        return False
    if not (mat.GetName() or "").startswith(K.DOPPLER_MATERIAL_PREFIX):
        return False
    bc = mat.GetDataInstance()
    if bc is None:
        return False
    try:
        # GetString returns "" for unset slots; the marker is the
        # original material's name, which is never empty.
        return bool(bc.GetString(_BC_KEY_ORIG_NAME))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Document walks
# ---------------------------------------------------------------------------

def _iter_objects(doc):
    """Yield every object in *doc*, recursively, in scene-graph order."""
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
    """Yield every material in *doc*'s material list."""
    if doc is None:
        return
    m = doc.GetFirstMaterial()
    while m is not None:
        yield m
        m = m.GetNext()


def _iter_texture_tags(obj):
    """Yield every texture tag (Ttexture) attached to *obj*."""
    tag = obj.GetFirstTag()
    while tag is not None:
        if tag.GetType() == c4d.Ttexture:
            yield tag
        tag = tag.GetNext()


def _objects_using_material(doc, mat):
    """Return the list of objects whose texture tags reference *mat*."""
    out = []
    for obj in _iter_objects(doc):
        for tag in _iter_texture_tags(obj):
            try:
                ref = tag[c4d.TEXTURETAG_MATERIAL]
            except Exception:
                ref = None
            if ref is mat:
                out.append(obj)
                break
    return out


def _find_material_by_name(doc, name):
    """First material in *doc* whose name equals *name*, or None."""
    for m in _iter_materials(doc):
        if m.GetName() == name:
            return m
    return None


# ---------------------------------------------------------------------------
# Selection -> affected-material set
# ---------------------------------------------------------------------------

def _gather_affected_materials(doc):
    """
    Return the unique list of materials we should duplicate.

    Sources (combined, de-duplicated):
      * Materials currently selected in the Material Manager.
      * Materials referenced by texture tags on selected objects.

    Materials that are themselves Doppler duplicates are skipped so the
    user can't accidentally chain ``LS_Doppler_LS_Doppler_*``.
    """
    seen = set()
    out = []

    def _consider(mat):
        if mat is None or is_doppler_duplicate(mat):
            return
        # id() is fine here -- materials are stable BaseList2D objects.
        key = id(mat)
        if key in seen:
            return
        seen.add(key)
        out.append(mat)

    # Material Manager selection.
    try:
        for m in doc.GetActiveMaterials() or []:
            _consider(m)
    except Exception:
        pass

    # Object Manager selection -> texture tags.
    try:
        actives = doc.GetActiveObjects(0) or []
    except Exception:
        actives = []
    for obj in actives:
        for tag in _iter_texture_tags(obj):
            try:
                _consider(tag[c4d.TEXTURETAG_MATERIAL])
            except Exception:
                pass

    return out


# ---------------------------------------------------------------------------
# Duplicate creation
# ---------------------------------------------------------------------------

def _capture_baseline(dup, original):
    """
    Stamp *dup* with bookkeeping needed for live shifting and restore.
    """
    bc = dup.GetDataInstance()
    if bc is None:
        return
    try:
        bc.SetString(_BC_KEY_ORIG_NAME, original.GetName() or "")
        bc.SetInt32(_BC_KEY_ORIG_TYPE, int(original.GetType()))
        # Baseline colour: only meaningful for classic materials; for
        # non-classic we still store something so apply/restore have a
        # consistent shape.
        if _is_classic_material(original):
            base = original[c4d.MATERIAL_COLOR_COLOR]
            if not isinstance(base, c4d.Vector):
                base = c4d.Vector(1.0, 1.0, 1.0)
            bc.SetVector(_BC_KEY_BASE_COLOR, base)
        else:
            bc.SetVector(_BC_KEY_BASE_COLOR, c4d.Vector(1.0, 1.0, 1.0))
    except Exception:
        # If the engine refuses our private slots, the worst case is
        # restore won't be able to look up the original by name --
        # tolerable for the skeleton.
        pass


def _create_duplicate(doc, original):
    """
    Clone *original*, rename, capture baseline, insert into the document.

    Returns the duplicate ``BaseMaterial`` or ``None`` on failure.
    """
    try:
        dup = original.GetClone(c4d.COPYFLAGS_NONE)
    except Exception:
        return None
    if dup is None:
        return None

    new_name = "{0}{1}".format(K.DOPPLER_MATERIAL_PREFIX, original.GetName() or "")
    dup.SetName(new_name)
    _capture_baseline(dup, original)

    doc.InsertMaterial(dup)
    doc.AddUndo(c4d.UNDOTYPE_NEW, dup)
    return dup


def _swap_texture_tags(doc, original, duplicate):
    """
    Re-point every texture tag in *doc* that referenced *original* at
    *duplicate*. Returns the number of tags swapped.
    """
    count = 0
    for obj in _iter_objects(doc):
        for tag in _iter_texture_tags(obj):
            try:
                ref = tag[c4d.TEXTURETAG_MATERIAL]
            except Exception:
                continue
            if ref is original:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
                tag[c4d.TEXTURETAG_MATERIAL] = duplicate
                count += 1
    return count


# ---------------------------------------------------------------------------
# Public API: add / restore
# ---------------------------------------------------------------------------

def add_doppler_controller(doc):
    """
    Wrap selected materials (or selected-object materials) in
    ``LS_Doppler_<name>`` duplicates.

    Returns the number of duplicates created (0 on no-op or recoverable
    error). Errors surface via dialogs.
    """
    if doc is None:
        ls_ui.error("No active document.")
        return 0

    affected = _gather_affected_materials(doc)
    if not affected:
        ls_ui.error(
            "No materials to wrap.\n\n"
            "Select objects in the Object Manager (so their texture-tag "
            "materials are picked up) and/or materials in the Material "
            "Manager, then rerun this command."
        )
        return 0

    doc.StartUndo()
    created = 0
    skipped_non_classic = 0
    try:
        for original in affected:
            dup = _create_duplicate(doc, original)
            if dup is None:
                continue
            _swap_texture_tags(doc, original, dup)
            created += 1
            if not _is_classic_material(original):
                skipped_non_classic += 1
    except Exception:
        doc.EndUndo()
        c4d.EventAdd()
        raise
    doc.EndUndo()
    c4d.EventAdd()

    if skipped_non_classic:
        ls_ui.info(
            "Created {0} duplicate(s); {1} use a non-classic material "
            "type and will not have their colour shifted live yet "
            "(node-graph engines such as Octane / Redshift need per-"
            "engine code -- see TODO in ls_doppler_materials.py).".format(
                created, skipped_non_classic
            )
        )
    else:
        ls_ui.status("Created {0} Doppler material duplicate(s).".format(created))

    return created


def restore_original_materials(doc):
    """
    Re-point every Doppler-duplicate reference back to the original and
    delete the duplicates.

    Returns the number of duplicates deleted (0 on no-op).
    """
    if doc is None:
        ls_ui.error("No active document.")
        return 0

    duplicates = [m for m in _iter_materials(doc) if is_doppler_duplicate(m)]
    if not duplicates:
        ls_ui.info("No LS_Doppler_* materials found; nothing to restore.")
        return 0

    # Build name -> original lookup once (the document only changes via
    # our undo block below, which doesn't add/rename non-duplicates).
    duplicate_name_set = {m.GetName() for m in duplicates}

    doc.StartUndo()
    restored_tags = 0
    deleted = 0
    missing_originals = []
    try:
        for dup in duplicates:
            bc = dup.GetDataInstance()
            orig_name = ""
            if bc is not None:
                try:
                    orig_name = bc.GetString(_BC_KEY_ORIG_NAME) or ""
                except Exception:
                    orig_name = ""
            original = _find_material_by_name(doc, orig_name) if orig_name else None

            if original is not None and original.GetName() in duplicate_name_set:
                # Defensive: never restore to another duplicate.
                original = None

            # Re-point texture tags.
            for obj in _iter_objects(doc):
                for tag in _iter_texture_tags(obj):
                    try:
                        ref = tag[c4d.TEXTURETAG_MATERIAL]
                    except Exception:
                        continue
                    if ref is dup:
                        doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
                        tag[c4d.TEXTURETAG_MATERIAL] = original
                        restored_tags += 1

            if original is None and orig_name:
                missing_originals.append(orig_name)

            doc.AddUndo(c4d.UNDOTYPE_DELETE, dup)
            dup.Remove()
            deleted += 1
    except Exception:
        doc.EndUndo()
        c4d.EventAdd()
        raise
    doc.EndUndo()
    c4d.EventAdd()

    if missing_originals:
        ls_ui.info(
            "Restored {0} duplicate(s); {1} original material(s) could "
            "not be found by name and the corresponding texture tags "
            "were left unassigned: {2}".format(
                deleted, len(missing_originals),
                ", ".join(sorted(set(missing_originals))),
            )
        )
    else:
        ls_ui.status(
            "Restored originals for {0} material(s); cleared {1} texture "
            "tag reference(s).".format(deleted, restored_tags)
        )
    return deleted


# ---------------------------------------------------------------------------
# Live evaluation
# ---------------------------------------------------------------------------

def _baseline_color(dup):
    """Return the baseline colour stamped into *dup* (Vector)."""
    bc = dup.GetDataInstance()
    if bc is None:
        return c4d.Vector(1.0, 1.0, 1.0)
    try:
        return bc.GetVector(_BC_KEY_BASE_COLOR)
    except Exception:
        return c4d.Vector(1.0, 1.0, 1.0)


def _write_classic_color(mat, color):
    """Write *color* to *mat*'s standard colour channel (no-op if absent)."""
    try:
        mat[c4d.MATERIAL_COLOR_COLOR] = color
    except Exception:
        pass


def _shift_classic_material(dup, doppler_d, strength):
    """Apply the wavelength-shift approximation to *dup*'s colour channel."""
    base = _baseline_color(dup)
    rgb = (float(base.x), float(base.y), float(base.z))
    out = RM.wavelength_shift_rgb_approx(rgb, doppler_d, strength=strength)
    _write_classic_color(dup, c4d.Vector(out[0], out[1], out[2]))


def restore_baseline_colors(doc):
    """
    Snap every duplicate's classic colour channel back to its baseline.

    Used by the evaluator when ``enable_doppler_color`` is False, so the
    duplicates keep existing (and texture-tag wiring stays valid) while
    showing the original colour.
    """
    if doc is None:
        return
    for mat in _iter_materials(doc):
        if not is_doppler_duplicate(mat):
            continue
        if _is_classic_material(mat):
            _write_classic_color(mat, _baseline_color(mat))


def apply_doppler_color_shift(doc, controller, camera, beta, strength):
    """
    Drive every ``LS_Doppler_*`` material's colour from the relativistic
    Doppler factor for the line of sight to the objects using it.

    Parameters
    ----------
    doc : c4d.documents.BaseDocument
    controller : c4d.BaseTag or None
        Used only to read ``velocity_axis_source`` /
        ``velocity_custom_vector`` for axis resolution.
    camera : c4d.BaseObject or None
        Position + forward vector source. If absent we fall back to
        world origin and world +Z so the function still produces a
        reasonable shift in headless contexts.
    beta : float
        Already clamped by the caller via :func:`clamp_beta`.
    strength : float
        ``doppler_color_strength * effect_strength``-style multiplier.
        Clamped to ``[0, 2]`` here so out-of-band UD values can't hang
        the colour pipeline.

    Returns the number of materials updated.
    """
    if doc is None:
        return 0

    if strength < 0.0:
        strength = 0.0
    elif strength > 2.0:
        strength = 2.0

    # ---- resolve velocity axis -------------------------------------------
    axis_source = K.AXIS_SOURCE_CAMERA_FORWARD
    custom_vec = c4d.Vector(0.0, 0.0, 1.0)
    if controller is not None:
        # We mirror the lookup the evaluator/geometry modules do, but
        # inline-and-defensive so a stripped-down controller doesn't
        # break colour evaluation.
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

    # ---- iterate duplicates ---------------------------------------------
    updated = 0
    for mat in _iter_materials(doc):
        if not is_doppler_duplicate(mat):
            continue

        if not _is_classic_material(mat):
            # Non-classic materials: log once, skip per-tick colour write.
            type_id = mat.GetType()
            if type_id not in _NON_CLASSIC_LOGGED:
                _NON_CLASSIC_LOGGED.add(type_id)
                ls_ui.log(
                    "Doppler shift: skipping live update for material type "
                    "{0} ('{1}') -- node-graph colour writes need per-engine "
                    "code (TODO).".format(type_id, mat.GetName())
                )
            continue

        # Average position of objects using this duplicate. If nothing
        # uses it, fall back to the camera position so the duplicate
        # shows its baseline colour (cos_theta resolves to 0; D ~ 1/gamma
        # which is mild).
        users = _objects_using_material(doc, mat)
        if users:
            centroid = c4d.Vector(0.0, 0.0, 0.0)
            for u in users:
                centroid += u.GetMg().off
            centroid /= float(len(users))
        else:
            centroid = cam_pos

        look = centroid - cam_pos
        if look.GetLength() < 1.0e-9:
            cos_theta = 0.0
        else:
            cos_theta = forward * look.GetNormalized()
            # Clamp into [-1, 1] -- forward is unit, look.normalized is
            # unit, but FP rounding can push us a hair beyond.
            if cos_theta > 1.0:
                cos_theta = 1.0
            elif cos_theta < -1.0:
                cos_theta = -1.0

        d = RM.doppler_factor(beta, cos_theta)
        _shift_classic_material(mat, d, strength)
        updated += 1

    return updated
