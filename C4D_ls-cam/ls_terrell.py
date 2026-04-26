"""
ls_terrell.py
=============
Artistic placeholder for Terrell-Penrose rotation.

Classification:
    [ARTISTIC]      -- the heading-axis rotation written in
                       :func:`apply_terrell_placeholder`.
    [UNIMPLEMENTED] -- real Terrell-Penrose rotation. See the
                       "Future ray-level work" section below.

**This is not real Terrell rotation.** Real Terrell-Penrose is a
per-ray, retarded-time visual phenomenon: light from different
points of a moving object reaches the observer at different
*emission* times, so the apparent shape is rotated rather than
contracted. Computing this correctly requires either a custom
ray-level renderer, a custom shader that warps screen-space samples,
or a per-vertex evaluator that knows the camera's world line. None
of those live in this plugin.

What this module does instead
-----------------------------
:func:`apply_terrell_placeholder` writes a small heading-axis (Y)
rotation onto the ``LS_Geometry_Proxy`` null. The angle is
``asin(beta) * strength`` (clamped); it composes on top of the
proxy's captured baseline rotation so the contraction axis the
geometry pass set up at creation time is preserved when the
placeholder is disabled.

This is **strictly artistic**. It is intentionally kept in its own
module, gated behind its own user-data flag, and labelled as
"Advanced" in the Attribute Manager so it never gets confused with
the physically motivated approximations in
:mod:`ls_relativity_math`. The accompanying ``ray_level_warning``
string field on the controller carries the same disclaimer in the
UI.

Reversibility
-------------
Just like the searchlight + doppler passes, the proxy's baseline
rotation is stamped into a private BaseContainer slot the first
time the placeholder runs. :func:`restore_terrell` writes the
baseline back and clears the marker so a subsequent re-enable
re-captures from the now-restored state. The evaluator's reset
path also calls :func:`restore_terrell`.

Future ray-level work
---------------------
TODO: a real implementation would need either a custom Octane
script-camera (or equivalent ScriptedCamera in C4D 2025+ Python),
a custom render-pass that warps screen-space samples per their
retarded-time arrival, or a per-vertex deformer that solves the
light-cone intersection. Anything along those lines belongs in a
separate ``ls_terrell_ray.py`` (or shader file) rather than this
placeholder.
"""

import math

import c4d


# ---------------------------------------------------------------------------
# Private BaseContainer slots used to remember the proxy's baseline
# rotation. Distinct from every other module's private slots so the
# searchlight + terrell baselines can co-exist on the same proxy.
# ---------------------------------------------------------------------------
_BC_KEY_BASELINE_ROT = 1500       # vec  -- captured ID_BASEOBJECT_REL_ROTATION
_BC_KEY_HAS_BASELINE = 1501       # int  -- 1 once baseline stored


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
# Cap the placeholder rotation a hair below pi/2 so asin(beta) never
# blows up at beta -> 1 and the proxy never snaps to a 90-degree pose.
_BETA_CAP_FOR_ANGLE = 0.999


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_baseline(proxy):
    """Stamp the proxy's current REL_ROTATION into a private BC slot (once)."""
    bc = proxy.GetDataInstance()
    if bc is None:
        return False
    try:
        if bc.GetInt32(_BC_KEY_HAS_BASELINE):
            return True
    except Exception:
        pass
    try:
        rot = proxy[c4d.ID_BASEOBJECT_REL_ROTATION]
    except Exception:
        rot = c4d.Vector(0.0, 0.0, 0.0)
    if not isinstance(rot, c4d.Vector):
        rot = c4d.Vector(0.0, 0.0, 0.0)
    try:
        bc.SetVector(_BC_KEY_BASELINE_ROT, rot)
        bc.SetInt32(_BC_KEY_HAS_BASELINE, 1)
        return True
    except Exception:
        return False


def _read_baseline(proxy):
    """Return the stored baseline rotation, or zero vector if missing."""
    bc = proxy.GetDataInstance()
    if bc is None:
        return c4d.Vector(0.0, 0.0, 0.0)
    try:
        if not bc.GetInt32(_BC_KEY_HAS_BASELINE):
            return c4d.Vector(0.0, 0.0, 0.0)
        rot = bc.GetVector(_BC_KEY_BASELINE_ROT)
        if not isinstance(rot, c4d.Vector):
            return c4d.Vector(0.0, 0.0, 0.0)
        return rot
    except Exception:
        return c4d.Vector(0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_terrell_placeholder(proxy_object, camera, beta, strength):
    """
    Apply the artistic Terrell rotation placeholder to *proxy_object*.

    Parameters
    ----------
    proxy_object : c4d.BaseObject or None
        Typically the LS_Geometry_Proxy null. ``None`` is a no-op so
        callers don't need to gate on proxy existence.
    camera : c4d.BaseObject or None
        Reserved for future ray-level work; the placeholder ignores it
        and rotates around the proxy's local Y axis (heading) so the
        rotation is visible regardless of camera framing.
    beta : float
        v / c. Caller is expected to have clamped this to (-1, 1) via
        :func:`ls_relativity_math.clamp_beta`. We re-clamp defensively.
    strength : float
        Artistic multiplier. ``0`` disables the rotation; ``1`` is the
        nominal visible effect; values up to ``2`` are accepted (and
        clamped at the ``asin`` step).

    Returns the angle (radians) actually applied, or ``0.0`` on no-op.
    """
    if proxy_object is None:
        return 0.0
    if strength <= 0.0:
        # Zero strength: still capture a baseline so a later re-enable
        # gets a clean reference, but don't rotate.
        _ensure_baseline(proxy_object)
        baseline = _read_baseline(proxy_object)
        try:
            proxy_object[c4d.ID_BASEOBJECT_REL_ROTATION] = baseline
        except Exception:
            pass
        return 0.0

    # Defensive beta clamp: asin's domain is [-1, 1] and we don't want
    # the angle to snap to ±pi/2 either.
    b = float(beta)
    if b > _BETA_CAP_FOR_ANGLE:
        b = _BETA_CAP_FOR_ANGLE
    elif b < -_BETA_CAP_FOR_ANGLE:
        b = -_BETA_CAP_FOR_ANGLE

    if not _ensure_baseline(proxy_object):
        return 0.0
    baseline = _read_baseline(proxy_object)

    # Artistic angle: asin(|beta|) scales nicely in [0, pi/2 * cap),
    # giving 0 at rest and approaching but not reaching pi/2 near c.
    # Sign of beta picks the rotation direction.
    angle = math.asin(abs(b)) * float(strength)
    if b < 0.0:
        angle = -angle

    # Compose the artistic angle onto the baseline heading (Y / .y in
    # C4D's HPB convention). Pitch + bank stay at baseline so the
    # geometry pass's contraction axis (which lives on local Z) is
    # preserved.
    new_rot = c4d.Vector(baseline.x, baseline.y + angle, baseline.z)
    try:
        proxy_object[c4d.ID_BASEOBJECT_REL_ROTATION] = new_rot
    except Exception:
        return 0.0

    return angle


def restore_terrell(proxy_object):
    """
    Undo the placeholder rotation: write the baseline back and clear
    the marker so the next apply re-captures from the current state.

    Cheap when there is no marker (single BC read).
    """
    if proxy_object is None:
        return False
    bc = proxy_object.GetDataInstance()
    if bc is None:
        return False
    try:
        if not bc.GetInt32(_BC_KEY_HAS_BASELINE):
            return False
    except Exception:
        return False
    try:
        baseline = bc.GetVector(_BC_KEY_BASELINE_ROT)
        if not isinstance(baseline, c4d.Vector):
            baseline = c4d.Vector(0.0, 0.0, 0.0)
        try:
            proxy_object[c4d.ID_BASEOBJECT_REL_ROTATION] = baseline
        except Exception:
            pass
    except Exception:
        pass
    try:
        bc.SetInt32(_BC_KEY_HAS_BASELINE, 0)
    except Exception:
        pass
    return True
