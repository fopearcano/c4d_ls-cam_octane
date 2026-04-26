"""
ls_evaluator.py
===============
Connects the LS_Relativity_Controller user data to the rig's camera.

The controller's Python tag calls :func:`update_ls_camera_rig` on every
scene evaluation. The function reads the user-data inputs, computes the
relativistic quantities (via the pure-Python helpers in
:mod:`ls_relativity_math`), writes the computed outputs back to the
controller's read-only fields, and adjusts the camera's FOV.

Design notes
------------
* The function is **non-destructive**: the camera's FOV is always derived
  from the rest-FOV captured at rig-creation time. Setting beta back to
  zero (or disabling Lorentz geometry) restores the original FOV exactly.
* Geometry deformation, material/shader updates, and Octane integration
  are intentionally out of scope for this module. They will land in
  follow-up commits as separate evaluator passes.
* Importing :mod:`c4d` happens lazily inside the function so unit tests
  for the math layer keep running outside Cinema 4D. The user-data
  helpers below do touch ``c4d``, but only at call time.
"""

import c4d

import ls_constants as K
import ls_relativity_math as RM


# ---------------------------------------------------------------------------
# User-data lookup helpers
# ---------------------------------------------------------------------------

def _build_ud_lookup(host):
    """
    Map UD label -> DescID for every user-data field on *host*.

    We iterate the user-data container fresh on every call; this is O(N)
    in the number of fields (~13 for our controller) and avoids stale
    caches if the user reorders or renames fields. The map is keyed by
    the label string we set in :mod:`ls_constants`, so callers go through
    ``K.UD_LABELS[K.UD_KEY]`` to look up a field.
    """
    out = {}
    for desc_id, bc in host.GetUserDataContainer():
        out[bc[c4d.DESC_NAME]] = desc_id
    return out


def _read(host, lookup, key, default=None):
    """Read user-data parameter *key* from *host* with a defensive fallback."""
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


def _write(host, lookup, key, value):
    """Write *value* back to user-data parameter *key* if it exists."""
    label = K.UD_LABELS.get(key)
    if label is None:
        return
    desc_id = lookup.get(label)
    if desc_id is None:
        return
    try:
        host[desc_id] = value
    except Exception:
        # A user could conceivably delete one of our fields; tolerate it.
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_ls_camera_rig(doc, controller, camera):
    """
    Re-evaluate the relativistic camera rig.

    Parameters
    ----------
    doc : c4d.documents.BaseDocument or None
        The owning document. Currently unused -- accepted so future passes
        (geometry deformation, etc.) can iterate scene objects without
        changing this signature.
    controller : c4d.BaseTag
        The ``LS_Relativity_Controller`` Python tag carrying the user data.
    camera : c4d.BaseObject
        The ``LS_Relativistic_Camera`` standard C4D camera.

    Returns
    -------
    dict or None
        Dictionary of the computed quantities, or ``None`` if the call was
        skipped because of bad inputs (e.g. missing camera). The dict
        always contains the same keys, even when individual effect flags
        are off, so callers can log it uniformly.
    """
    if controller is None or camera is None:
        return None

    lookup = _build_ud_lookup(controller)

    # ---- read inputs -------------------------------------------------------
    beta_raw = _read(controller, lookup, K.UD_BETA_VELOCITY, default=0.0)
    strength_raw = _read(controller, lookup, K.UD_EFFECT_STRENGTH, default=1.0)
    enable_lorentz = bool(_read(controller, lookup, K.UD_ENABLE_LORENTZ, default=True))
    enable_searchlight = bool(_read(controller, lookup, K.UD_ENABLE_SEARCHLIGHT, default=True))
    debug = bool(_read(controller, lookup, K.UD_DEBUG_MODE, default=False))

    # Defensive coercion: user data could in principle hold any type if a
    # third-party script overwrote the field. clamp_beta also handles the
    # numeric range, but we still want a float to feed the helpers.
    try:
        beta = float(beta_raw)
    except (TypeError, ValueError):
        beta = 0.0
    try:
        strength = float(strength_raw)
    except (TypeError, ValueError):
        strength = 1.0

    beta = RM.clamp_beta(beta)
    if strength < 0.0:
        strength = 0.0

    # ---- compute relativistic quantities ----------------------------------
    gamma = RM.gamma_from_beta(beta)
    contraction = RM.lorentz_contraction_factor(beta)
    # Forward direction = cos_theta = +1 (line of sight straight ahead).
    doppler_fwd = RM.doppler_factor(beta, 1.0)
    searchlight_mult = (
        RM.searchlight_intensity_factor(beta, 1.0, strength=strength)
        if enable_searchlight else 1.0
    )

    # ---- write computed outputs back to the controller --------------------
    _write(controller, lookup, K.UD_OUT_GAMMA, float(gamma))
    _write(controller, lookup, K.UD_OUT_CONTRACTION, float(contraction))
    _write(controller, lookup, K.UD_OUT_DOPPLER_FWD, float(doppler_fwd))
    _write(controller, lookup, K.UD_OUT_SEARCHLIGHT, float(searchlight_mult))

    # ---- drive the camera (FOV only at this stage) ------------------------
    rest_fov = _read(controller, lookup, K.UD_REST_FOV_RAD, default=0.0)
    try:
        rest_fov = float(rest_fov)
    except (TypeError, ValueError):
        rest_fov = 0.0

    # If we never captured a rest FOV (e.g. tag attached to an existing
    # camera by hand), do it lazily on the first useful evaluation.
    if rest_fov <= 0.0:
        rest_fov = float(camera[c4d.CAMERAOBJECT_FOV])
        _write(controller, lookup, K.UD_REST_FOV_RAD, rest_fov)

    if enable_lorentz and rest_fov > 0.0:
        fov_mult = 1.0 + K.FOV_BETA_COEFF * beta * strength
        new_fov = rest_fov * fov_mult
        # 2*pi is a safe upper bound; the camera object would clip negative
        # values, but the math above never produces them.
        camera[c4d.CAMERAOBJECT_FOV] = float(new_fov)
    else:
        # Effect off: snap back to rest FOV so the rig is fully reversible.
        if rest_fov > 0.0:
            camera[c4d.CAMERAOBJECT_FOV] = float(rest_fov)

    # Motion-blur multiplier is a placeholder: we compute it here so the
    # value is available for debug logging and future render-engine wiring,
    # but we deliberately don't poke any render settings yet -- different
    # engines (Standard, Physical, Redshift, Octane) expose motion blur in
    # different places and we want one engine-agnostic story.
    motion_blur_mult = 1.0 + K.MOTION_BLUR_BETA_COEFF * beta * strength

    # ---- debug ------------------------------------------------------------
    if debug:
        print(
            "[C4D_ls-cam][debug] beta={0:.4f} strength={1:.3f} "
            "gamma={2:.4f} contraction={3:.4f} doppler_fwd={4:.4f} "
            "searchlight={5:.4g} fov_mult={6:.4f} mb_mult={7:.4f}".format(
                beta, strength, gamma, contraction, doppler_fwd,
                searchlight_mult,
                1.0 + K.FOV_BETA_COEFF * beta * strength,
                motion_blur_mult,
            )
        )

    return {
        "beta": beta,
        "strength": strength,
        "gamma": gamma,
        "contraction_factor": contraction,
        "doppler_forward_factor": doppler_fwd,
        "searchlight_multiplier": searchlight_mult,
        "rest_fov_rad": rest_fov,
        "motion_blur_multiplier": motion_blur_mult,
    }
