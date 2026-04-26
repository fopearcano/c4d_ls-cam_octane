"""
ls_geometry.py
==============
Non-destructive "Lorentz Geometry Proxy" support.

Workflow
--------
1. The user selects scene objects (or none, with ``affect_selected_only``
   off, in which case every top-level object outside the rig is wrapped).
2. The user runs the menu command **LS Cam: Add Relativistic Geometry
   Proxy**, which calls :func:`add_geometry_proxy`.
3. This module creates an ``LS_Geometry_Proxy`` null whose local Z axis
   is aligned with the chosen velocity axis, reparents the targets under
   it (preserving their world transforms), and stores the captured
   velocity direction on the proxy so the evaluator can contract the
   proxy along that axis on every tick.
4. To unwrap, the user runs **LS Cam: Remove Relativistic Geometry
   Proxy**, which calls :func:`remove_geometry_proxy`. Children are
   moved back out (world transforms preserved) and the proxy is deleted.

Only the ``Proxy Scale`` mode is implemented in this pass:

* Proxy Scale -- the proxy null's local Z scale is driven by the
  Lorentz contraction factor ``sqrt(1 - β²)``. Wider beta => more
  contraction.
* Point Deform Approx -- reserved; currently a no-op with a TODO.

What this is NOT
----------------
This module performs a **uniform scale along one axis**. It is not a
relativistic raytracer: it does not implement Terrell-Penrose rotation,
true light-time aberration of geometry, or per-vertex relativistic
visual transforms. Those belong in a future pass that operates at the
ray level.

TODO: ray-level visual transformation (Terrell rotation, retarded-time
sampling, per-pixel aberration warp). That work likely lives in a
shader or a custom render-pass plugin, not in this evaluator.

Classification:
    [PHYSICAL]      -- the contraction factor sqrt(1 - beta^2) used
                       to drive the proxy null's local Z scale.
    [ARTISTIC]      -- the contraction_strength blend that lets
                       artists exaggerate (or fade out) the
                       contraction without touching beta.
    [UNIMPLEMENTED] -- per-vertex deformation, retarded-time sampling,
                       Terrell-Penrose rotation, per-pixel aberration
                       warp. See the GEOM_MODE_POINT_DEFORM branch in
                       :func:`apply_proxy_contraction` for the TODO.
"""

import c4d

import ls_constants as K
import ls_ui


# Tag whose presence on an object marks it as a geometry-proxy member.
# We store the original parent's name in the tag's BaseContainer so
# remove_geometry_proxy can put each child back near its original spot.
# (We use TAnnotation since it has no side effects on rendering.)
_MEMBER_TAG_NAME = "LS_GeomProxyMember"
_BC_KEY_ORIGINAL_PARENT = 1100   # Private container slot for the parent name.

# How close two unit vectors have to be (dot product) before we treat
# them as parallel and pick a different up vector when building the
# proxy's local frame.
_PARALLEL_DOT_THRESHOLD = 0.999


# ---------------------------------------------------------------------------
# Lookup helpers (mirrors the evaluator's UD lookup approach)
# ---------------------------------------------------------------------------

def _build_ud_lookup(host):
    out = {}
    for desc_id, bc in host.GetUserDataContainer():
        out[bc[c4d.DESC_NAME]] = desc_id
    return out


def _read_ud(host, lookup, key, default=None):
    label = K.UD_LABELS.get(key)
    if label is None:
        return default
    desc_id = lookup.get(label)
    if desc_id is None:
        return default
    try:
        return host[desc_id]
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Rig discovery
# ---------------------------------------------------------------------------

def _find_rig_null(doc):
    """Return the first ``LS_Camera_Rig`` null in *doc* (or None)."""
    if doc is None:
        return None
    obj = doc.GetFirstObject()
    while obj is not None:
        if obj.GetName() == K.RIG_NULL_NAME and obj.GetType() == c4d.Onull:
            return obj
        obj = obj.GetNext()
    return None


def _find_camera_in_rig(rig_null):
    """Return the camera child of *rig_null* (or None)."""
    if rig_null is None:
        return None
    child = rig_null.GetDown()
    while child is not None:
        if child.GetType() == c4d.Ocamera:
            return child
        child = child.GetNext()
    return None


def _find_controller_tag(rig_null):
    """Return the controller Python tag on *rig_null* (or None)."""
    if rig_null is None:
        return None
    tag = rig_null.GetFirstTag()
    while tag is not None:
        if (tag.GetType() == c4d.Tpython
                and tag.GetName() == K.CONTROLLER_TAG_NAME):
            return tag
        tag = tag.GetNext()
    return None


def find_existing_proxy(doc):
    """Return the existing ``LS_Geometry_Proxy`` null in *doc* (or None)."""
    if doc is None:
        return None
    obj = doc.GetFirstObject()
    while obj is not None:
        if (obj.GetName() == K.GEOMETRY_PROXY_NAME
                and obj.GetType() == c4d.Onull):
            return obj
        obj = obj.GetNext()
    return None


# ---------------------------------------------------------------------------
# Velocity axis + matrix helpers
# ---------------------------------------------------------------------------

# Public aliases -- other modules (e.g. ls_doppler_materials) import these.
def camera_forward_vector(camera):
    """Public alias for :func:`_camera_forward`."""
    return _camera_forward(camera)


def resolve_velocity_axis(camera, source_idx, custom_vec):
    """Public alias for :func:`_resolve_velocity_axis`."""
    return _resolve_velocity_axis(camera, source_idx, custom_vec)


def _camera_forward(camera):
    """
    Return the camera's forward direction in world space as a unit vector.

    Cinema 4D cameras look along their local -Z axis. ``GetMg().v3`` is
    the world-space basis vector for local +Z, so the forward direction
    is its negation.
    """
    if camera is None:
        return c4d.Vector(0.0, 0.0, 1.0)
    mg = camera.GetMg()
    forward = -mg.v3
    if forward.GetLength() < 1.0e-9:
        return c4d.Vector(0.0, 0.0, 1.0)
    return forward.GetNormalized()


def _resolve_velocity_axis(camera, source_idx, custom_vec):
    """
    Pick the world-space velocity axis based on the controller setting.

    Falls back to world +Z if the chosen source resolves to a zero-length
    vector (defensive against an empty Custom field or a degenerate
    camera matrix).
    """
    if source_idx == K.AXIS_SOURCE_CAMERA_FORWARD:
        return _camera_forward(camera)
    if source_idx == K.AXIS_SOURCE_WORLD_Z:
        return c4d.Vector(0.0, 0.0, 1.0)
    if source_idx == K.AXIS_SOURCE_CUSTOM:
        if custom_vec is None or custom_vec.GetLength() < 1.0e-9:
            return c4d.Vector(0.0, 0.0, 1.0)
        return custom_vec.GetNormalized()
    return c4d.Vector(0.0, 0.0, 1.0)


def _build_axis_aligned_matrix(direction, position):
    """
    Build a world-space matrix whose local Z axis is *direction*.

    The proxy null is created with this matrix so that scaling its local
    Z compresses geometry along the velocity axis. The X and Y basis
    vectors are constructed via cross products against an "up" vector
    that is intentionally non-parallel to *direction*.
    """
    z = direction.GetNormalized()
    up = c4d.Vector(0.0, 1.0, 0.0)
    if abs(z * up) > _PARALLEL_DOT_THRESHOLD:
        # Direction is (almost) world Y; pick world X as up instead.
        up = c4d.Vector(1.0, 0.0, 0.0)
    x = (up % z).GetNormalized()
    y = (z % x).GetNormalized()
    return c4d.Matrix(position, x, y, z)


def _selection_centroid(targets):
    """Return the average of each target's world-space origin."""
    if not targets:
        return c4d.Vector(0.0, 0.0, 0.0)
    s = c4d.Vector(0.0, 0.0, 0.0)
    for o in targets:
        s += o.GetMg().off
    return s / float(len(targets))


# ---------------------------------------------------------------------------
# Animation / skinning warnings
# ---------------------------------------------------------------------------

# Tag types that signal an object is more than a static mesh. Reparenting
# such objects works mechanically, but the contraction may interact
# badly with skin deformers / cached animation, so we warn the user.
_DEFORMING_TAG_TYPES = (
    c4d.Tweights,        # Skin weights tag
    c4d.Tposemorph,      # Pose Morph tag
)


def _check_deforming(targets):
    """
    Return a list of (object_name, reason) tuples describing potential
    issues with wrapping each target in a proxy.
    """
    issues = []
    for obj in targets:
        name = obj.GetName() or "<unnamed>"
        # Animated tracks?
        try:
            tracks = obj.GetCTracks()
        except Exception:
            tracks = None
        if tracks:
            issues.append((name, "has animated tracks; proxy scale "
                                 "is applied on top of the animation."))
        # Skinning / morph tags?
        tag = obj.GetFirstTag()
        while tag is not None:
            if tag.GetType() in _DEFORMING_TAG_TYPES:
                issues.append((name, "carries a deforming tag ({0}); "
                                     "results may differ from a true "
                                     "Lorentz contraction.".format(
                                         tag.GetName() or tag.GetType())))
                break
            tag = tag.GetNext()
    return issues


# ---------------------------------------------------------------------------
# Member-tag helpers (track original parent for restore)
# ---------------------------------------------------------------------------

def _attach_member_tag(child, original_parent):
    """
    Stamp *child* with a marker tag remembering its original parent name.

    We use an Annotation tag (Tannotation) because it has no side effects
    on rendering. The original parent's name is stored in a private slot
    on the tag's BaseContainer so a future remove_proxy call can attempt
    to put the child back next to its original sibling.
    """
    try:
        tag = c4d.BaseTag(c4d.Tannotation)
    except Exception:
        return None
    if tag is None:
        return None
    tag.SetName(_MEMBER_TAG_NAME)
    parent_name = original_parent.GetName() if original_parent is not None else ""
    try:
        bc = tag.GetDataInstance()
        if bc is not None:
            bc.SetString(_BC_KEY_ORIGINAL_PARENT, parent_name)
    except Exception:
        pass
    child.InsertTag(tag)
    return tag


def _find_member_tag(child):
    """Return the proxy-member marker tag on *child*, or None."""
    tag = child.GetFirstTag()
    while tag is not None:
        if tag.GetName() == _MEMBER_TAG_NAME:
            return tag
        tag = tag.GetNext()
    return None


def _read_original_parent_name(child):
    """Return the original-parent name stored on *child*'s member tag."""
    tag = _find_member_tag(child)
    if tag is None:
        return ""
    try:
        bc = tag.GetDataInstance()
        if bc is None:
            return ""
        return bc.GetString(_BC_KEY_ORIGINAL_PARENT) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API: create / remove
# ---------------------------------------------------------------------------

def add_geometry_proxy(doc):
    """
    Wrap selected (or all top-level) objects in an LS_Geometry_Proxy null.

    Returns the proxy ``BaseObject`` on success, ``None`` on a recoverable
    error (no rig, no targets, proxy already present). All errors surface
    via dialogs; the caller's command can simply return ``True`` after
    delegating here.

    The whole operation is wrapped in a single undo block.
    """
    if doc is None:
        ls_ui.error("No active document.")
        return None

    rig = _find_rig_null(doc)
    if rig is None:
        ls_ui.error(
            "No LS_Camera_Rig found in this scene. "
            "Run 'Create LS Relativistic Camera Rig' first."
        )
        return None

    controller = _find_controller_tag(rig)
    camera = _find_camera_in_rig(rig)
    if controller is None:
        ls_ui.error("LS_Camera_Rig is missing its LS_Relativity_Controller tag.")
        return None

    if find_existing_proxy(doc) is not None:
        ls_ui.error(
            "An LS_Geometry_Proxy already exists. "
            "Run 'LS Cam: Remove Relativistic Geometry Proxy' first."
        )
        return None

    lookup = _build_ud_lookup(controller)
    affect_selected = bool(_read_ud(controller, lookup,
                                    K.UD_AFFECT_SELECTED_ONLY, default=True))
    axis_source = int(_read_ud(controller, lookup,
                               K.UD_VELOCITY_AXIS_SOURCE,
                               default=K.AXIS_SOURCE_CAMERA_FORWARD) or 0)
    custom_vec = _read_ud(controller, lookup,
                          K.UD_VELOCITY_CUSTOM_VECTOR,
                          default=c4d.Vector(0.0, 0.0, 1.0))

    # ---- gather targets ---------------------------------------------------
    if affect_selected:
        try:
            targets = list(doc.GetActiveObjects(0))
        except Exception:
            targets = []
    else:
        targets = []
        obj = doc.GetFirstObject()
        while obj is not None:
            if obj is not rig:
                targets.append(obj)
            obj = obj.GetNext()

    # Filter out the rig itself or anything already inside the rig.
    targets = [t for t in targets if not _is_inside(t, rig)]
    if not targets:
        ls_ui.error(
            "No objects to wrap. Select scene objects "
            "(or disable 'affect_selected_only' on the controller) and rerun."
        )
        return None

    # ---- warn about animated / skinned targets ---------------------------
    issues = _check_deforming(targets)
    if issues:
        # Print to console and surface a single combined dialog so the
        # user can review before the (already-completed) rewrap.
        print("[C4D_ls-cam] Geometry-proxy warnings:")
        msg_lines = []
        for name, reason in issues:
            line = "  - {0}: {1}".format(name, reason)
            print(line)
            msg_lines.append(line)
        ls_ui.info(
            "Geometry proxy created with caveats:\n\n"
            + "\n".join(msg_lines)
            + "\n\nYou can remove the proxy with "
              "'LS Cam: Remove Relativistic Geometry Proxy'."
        )

    # ---- compute proxy frame ---------------------------------------------
    direction = _resolve_velocity_axis(camera, axis_source, custom_vec)
    centroid = _selection_centroid(targets)
    proxy_matrix = _build_axis_aligned_matrix(direction, centroid)

    # ---- build proxy + reparent under undo --------------------------------
    doc.StartUndo()
    try:
        proxy = c4d.BaseObject(c4d.Onull)
        if proxy is None:
            raise RuntimeError("Failed to allocate proxy null.")
        proxy.SetName(K.GEOMETRY_PROXY_NAME)
        proxy[c4d.NULLOBJECT_DISPLAY] = c4d.NULLOBJECT_DISPLAY_HEXAGON
        # Keep it visible-but-quiet in the viewport.
        proxy[c4d.NULLOBJECT_RADIUS] = 50.0
        proxy.SetMg(proxy_matrix)
        doc.InsertObject(proxy)
        doc.AddUndo(c4d.UNDOTYPE_NEW, proxy)

        for target in targets:
            world = target.GetMg()
            original_parent = target.GetUp()
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, target)
            target.InsertUnder(proxy)
            # Recompute local matrix so world transform is preserved.
            target.SetMl(~proxy_matrix * world)
            _attach_member_tag(target, original_parent)
    except Exception:
        doc.EndUndo()
        c4d.EventAdd()
        raise

    doc.EndUndo()
    c4d.EventAdd()
    return proxy


def remove_geometry_proxy(doc):
    """
    Unwrap the LS_Geometry_Proxy null and restore world transforms.

    Children are inserted back at the proxy's parent level (or the doc
    root if the proxy was a top-level object). Their world matrices are
    preserved.

    Returns True on success, False if no proxy exists.
    """
    if doc is None:
        ls_ui.error("No active document.")
        return False

    proxy = find_existing_proxy(doc)
    if proxy is None:
        ls_ui.error("No LS_Geometry_Proxy found.")
        return False

    parent_above = proxy.GetUp()  # may be None (proxy is at doc root)

    # Snapshot children first; reparenting modifies the sibling chain.
    children = []
    c = proxy.GetDown()
    while c is not None:
        children.append(c)
        c = c.GetNext()

    doc.StartUndo()
    try:
        for child in children:
            world = child.GetMg()
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, child)
            if parent_above is not None:
                child.InsertUnder(parent_above)
            else:
                # Document root.
                child.Remove()
                doc.InsertObject(child)
            child.SetMg(world)

            # Strip the marker tag so re-wrapping later doesn't pick up
            # stale data.
            tag = _find_member_tag(child)
            if tag is not None:
                doc.AddUndo(c4d.UNDOTYPE_DELETE, tag)
                tag.Remove()

        doc.AddUndo(c4d.UNDOTYPE_DELETE, proxy)
        proxy.Remove()
    except Exception:
        doc.EndUndo()
        c4d.EventAdd()
        raise

    doc.EndUndo()
    c4d.EventAdd()
    return True


# ---------------------------------------------------------------------------
# Live contraction (called by the evaluator)
# ---------------------------------------------------------------------------

def apply_proxy_contraction(doc, geom_mode, contraction_factor,
                             contraction_strength):
    """
    Drive the proxy null's local Z scale based on the Lorentz factor.

    Parameters
    ----------
    doc : c4d.documents.BaseDocument
    geom_mode : int
        One of ``K.GEOM_MODE_*``.
    contraction_factor : float
        ``sqrt(1 - β²)`` from :mod:`ls_relativity_math`. Always in (0, 1].
    contraction_strength : float
        Artistic blend in ``[0, 2]``. Clamped to ``[0, 1]`` for
        interpolation but values above 1 are tolerated (over-contraction
        is occasionally desirable for stylized work).

    The function is a no-op if no proxy exists or the mode is "Off".
    For the unimplemented "Point Deform Approx" mode it leaves a TODO
    marker and otherwise no-ops.
    """
    if doc is None:
        return

    proxy = find_existing_proxy(doc)
    if proxy is None:
        return

    if geom_mode == K.GEOM_MODE_OFF:
        # Snap proxy back to identity scale so the rig is reversible.
        try:
            proxy[c4d.ID_BASEOBJECT_REL_SCALE] = c4d.Vector(1.0, 1.0, 1.0)
        except Exception:
            pass
        return

    if geom_mode == K.GEOM_MODE_PROXY_SCALE:
        # Blend identity scale (1.0) toward contraction_factor by
        # contraction_strength. strength==0 -> off, strength==1 -> full
        # physical contraction, strength==2 -> over-contracted (look only).
        s = max(0.0, contraction_strength)
        scale_z = 1.0 + (contraction_factor - 1.0) * s
        if scale_z <= 0.0:
            scale_z = 1.0e-3  # never collapse to a singular matrix
        try:
            proxy[c4d.ID_BASEOBJECT_REL_SCALE] = c4d.Vector(1.0, 1.0, scale_z)
        except Exception:
            pass
        return

    if geom_mode == K.GEOM_MODE_POINT_DEFORM:
        # TODO: per-vertex deformation with retarded-time sampling and
        # optional Terrell-Penrose rotation. This requires walking each
        # PolygonObject's points and writing into a deform-cache; it is
        # intentionally not implemented in the proxy-scale skeleton.
        return


# ---------------------------------------------------------------------------
# Internal: ancestry check
# ---------------------------------------------------------------------------

def _is_inside(obj, ancestor):
    """Return True if *obj* is *ancestor* or one of its descendants."""
    cur = obj
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur.GetUp()
    return False
