"""
ls_evaluator.py
===============
Connects the LS_Relativity_Controller user data to the rig's camera (and
optionally to its Octane Camera Tag).

The controller's Python tag calls :func:`update_ls_camera_rig` on every
scene evaluation. The function reads the user-data inputs, computes the
relativistic quantities (via the pure-Python helpers in
:mod:`ls_relativity_math`), writes the computed outputs back to the
controller's read-only fields, and drives camera + Octane parameters.

Design notes
------------
* Every effect is **reversible**. The camera's FOV / focus distance /
  aperture are derived from baselines captured on the controller at rig
  creation; toggling an effect off snaps the parameter back to its
  baseline. Octane parameters that the evaluator touches are baselined
  lazily on first write into per-slot UD fields on the controller, so
  :func:`reset_ls_camera_rig` can restore them precisely.
* Effects that have no math-physics analogue (FOV widening modes,
  exposure beaming, DoF aperture scaling) are explicitly flagged as
  artistic approximations in the comments.
* Geometry deformation and material updates are still out of scope.
"""

import math

import c4d

import ls_constants as K
import ls_relativity_math as RM
import ls_octane
import ls_octane_params as OP
import ls_geometry
import ls_doppler_materials
import ls_searchlight
import ls_diagnostics
import ls_terrell


# Prefix used to store per-Octane-slot baselines on the controller as
# extra REAL user-data fields. Visible in the Attribute Manager so the
# user can see what was captured, but treated as read-only by reset.
_OCTANE_BASELINE_PREFIX = "_baseline_octane_"


# ---------------------------------------------------------------------------
# User-data lookup helpers
# ---------------------------------------------------------------------------

def _build_ud_lookup(host):
    """Map UD label -> DescID for every user-data field on *host*."""
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


def _read_label(host, lookup, label, default=None):
    """Same as :func:`_read` but takes the raw UD label string directly."""
    desc_id = lookup.get(label)
    if desc_id is None:
        return default
    try:
        return host[desc_id]
    except Exception:
        return default


def _write_label(host, lookup, label, value):
    """Same as :func:`_write` but takes the raw UD label string directly."""
    desc_id = lookup.get(label)
    if desc_id is None:
        return
    try:
        host[desc_id] = value
    except Exception:
        pass


def _coerce_float(value, fallback):
    """Best-effort float coercion with *fallback* on any failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


# ---------------------------------------------------------------------------
# Octane-baseline cache helpers
# ---------------------------------------------------------------------------
# Octane parameter IDs aren't known until the integrator fills in
# ls_octane_params.OCTANE_CAMERA_PARAMS, so we can't pre-create baseline
# UD fields at rig creation -- we add them on demand the first time we
# touch a given mapped slot. The fields persist with the scene file, so
# reset_ls_camera_rig() works after the document is reopened.

def _octane_baseline_label(slot_key):
    return _OCTANE_BASELINE_PREFIX + slot_key


def _ensure_octane_baseline(controller, lookup, slot_key, current_value):
    """
    Make sure the controller has a baseline UD field for *slot_key*.

    If the field already exists, leave its value alone (we baseline only
    once per slot). If it doesn't, create it as a hidden-ish REAL field
    seeded with *current_value*. Returns the DescID of the baseline
    field, or ``None`` if creation failed.

    The baseline is stored on the controller (not on the Octane tag)
    because the Octane tag could be deleted and re-created -- the
    controller is the stable owner of this rig's "memory".
    """
    label = _octane_baseline_label(slot_key)
    desc_id = lookup.get(label)
    if desc_id is not None:
        return desc_id

    bc = c4d.GetCustomDataTypeDefault(c4d.DTYPE_REAL)
    bc[c4d.DESC_NAME] = label
    bc[c4d.DESC_SHORT_NAME] = label
    bc[c4d.DESC_DEFAULT] = float(current_value) if current_value is not None else 0.0
    # Wide range: we don't know the param's natural scale.
    bc[c4d.DESC_MIN] = -1.0e12
    bc[c4d.DESC_MAX] = 1.0e12
    bc[c4d.DESC_CUSTOMGUI] = c4d.CUSTOMGUI_REAL
    desc_id = controller.AddUserData(bc)
    if desc_id is None:
        return None
    try:
        controller[desc_id] = float(current_value) if current_value is not None else 0.0
    except Exception:
        pass
    # Mutate the lookup so subsequent calls in this evaluation tick see it.
    lookup[label] = desc_id
    return desc_id


# ---------------------------------------------------------------------------
# Per-effect helpers
# ---------------------------------------------------------------------------

def _compute_fov_multiplier(mode, beta, fov_strength):
    """
    Return the multiplier applied to the rest FOV.

    Three modes, all of them artistic approximations:

    * ``Subtle`` -- linear widening, ``1 + 0.3·β·s``. Reads as "the
      world is leaning into the camera" without breaking framing.
    * ``Extreme`` -- linear widening, ``1 + 1.5·β·s``. Visceral
      fish-eye-y look at large beta.
    * ``Scientific-ish`` -- physically-motivated headlight effect
      using ``tan(θ'/2) = sqrt((1-β)/(1+β)) · tan(θ/2)``. The forward
      half-angle shrinks, so the FOV multiplier is < 1 (the image
      narrows). Strength blends between rest (1.0) and the full
      aberration factor.

    The "Scientific-ish" mode is still an artistic approximation: the
    real aberration formula doesn't act as a uniform FOV multiplier --
    it skews different angles differently. Treating it as a single
    multiplier is good enough for camera framing previews but won't
    match a true raytraced aberration pass.
    """
    if mode == K.FOV_MODE_SUBTLE:
        return 1.0 + K.FOV_MODE_SUBTLE_COEFF * beta * fov_strength
    if mode == K.FOV_MODE_EXTREME:
        return 1.0 + K.FOV_MODE_EXTREME_COEFF * beta * fov_strength
    if mode == K.FOV_MODE_SCIENTIFIC:
        # Physically-motivated, but applied to the whole FOV as a single
        # multiplier -- see docstring caveat.
        ab = math.sqrt((1.0 - beta) / (1.0 + beta))
        return 1.0 + (ab - 1.0) * fov_strength
    # Unknown mode index: behave like "off".
    return 1.0


def _apply_fov(controller, lookup, camera, beta, fov_strength,
               enable_lorentz, fov_mode):
    """
    Drive the camera's FOV non-destructively.

    Returns the multiplier actually written (1.0 if the effect was off
    or the rest FOV is missing).
    """
    rest_fov = _coerce_float(_read(controller, lookup, K.UD_REST_FOV_RAD,
                                   default=0.0), 0.0)

    # Lazily capture rest FOV if rig was hand-assembled.
    if rest_fov <= 0.0:
        try:
            rest_fov = float(camera[c4d.CAMERAOBJECT_FOV])
        except Exception:
            rest_fov = 0.0
        if rest_fov > 0.0:
            _write(controller, lookup, K.UD_REST_FOV_RAD, rest_fov)

    if rest_fov <= 0.0:
        return 1.0

    if not enable_lorentz:
        # Effect off: snap back to rest.
        try:
            camera[c4d.CAMERAOBJECT_FOV] = float(rest_fov)
        except Exception:
            pass
        return 1.0

    mult = _compute_fov_multiplier(fov_mode, beta, fov_strength)
    new_fov = rest_fov * mult
    # Guard: refuse to write nonsensical values. The camera would clamp
    # internally, but a hard floor here keeps the debug log readable.
    if new_fov <= 0.0:
        new_fov = 1.0e-3
    try:
        camera[c4d.CAMERAOBJECT_FOV] = float(new_fov)
    except Exception:
        pass
    return mult


def _apply_dof(controller, lookup, camera, octane_tag,
               beta, dof_strength, enable_dof):
    """
    Drive depth-of-field parameters.

    If an Octane Camera Tag is present and any of the DoF-related
    symbolic slots are mapped (depth_of_field, aperture), drive those.
    Otherwise drive the standard C4D camera's aperture parameter so the
    user still gets *some* feedback in non-Octane scenes.

    Artistic approximation: aperture is multiplied by
    ``1 + DOF_BETA_COEFF · β · dof_strength``. Wider aperture reads as
    a shallower focal plane, which we use as a stand-in for "subjective
    time slowing on the focal subject" at high speed. There is no real
    relativistic DoF effect -- this is purely a look.
    """
    rest_aperture = _coerce_float(
        _read(controller, lookup, K.UD_REST_APERTURE, default=0.0), 0.0)

    factor = 1.0 + K.DOF_BETA_COEFF * beta * dof_strength

    octane_drove_anything = False

    if octane_tag is not None:
        # Octane "aperture" slot: scale baseline by factor.
        ap_id = OP.get_param_id(OP.PARAM_APERTURE)
        if ap_id is not None:
            try:
                current = octane_tag[ap_id]
            except Exception:
                current = None
            baseline_id = _ensure_octane_baseline(
                controller, lookup, OP.PARAM_APERTURE, current)
            baseline = _coerce_float(
                controller[baseline_id] if baseline_id is not None else current,
                _coerce_float(current, 0.0))
            target = baseline * factor if enable_dof else baseline
            try:
                octane_tag[ap_id] = float(target)
                octane_drove_anything = True
            except Exception:
                pass

        # Octane "depth_of_field" slot: bool toggle. We baseline its
        # current state on first touch and only write while the effect
        # is active; reset will restore the baseline directly.
        dof_id = OP.get_param_id(OP.PARAM_DEPTH_OF_FIELD)
        if dof_id is not None:
            try:
                current = octane_tag[dof_id]
            except Exception:
                current = None
            baseline_id = _ensure_octane_baseline(
                controller, lookup, OP.PARAM_DEPTH_OF_FIELD,
                1.0 if current else 0.0)
            try:
                octane_tag[dof_id] = bool(enable_dof) if enable_dof else bool(
                    int(controller[baseline_id]) if baseline_id is not None else False)
                octane_drove_anything = True
            except Exception:
                pass

    if not octane_drove_anything:
        # C4D camera fallback: scale CAMERAOBJECT_APERTURE.
        # Some camera variants don't expose APERTURE; tolerate.
        if rest_aperture <= 0.0:
            try:
                rest_aperture = float(camera[c4d.CAMERAOBJECT_APERTURE])
            except Exception:
                rest_aperture = 0.0
            if rest_aperture > 0.0:
                _write(controller, lookup, K.UD_REST_APERTURE, rest_aperture)

        if rest_aperture > 0.0:
            target = rest_aperture * factor if enable_dof else rest_aperture
            try:
                camera[c4d.CAMERAOBJECT_APERTURE] = float(target)
            except Exception:
                pass

    return factor


def _apply_exposure(controller, lookup, octane_tag,
                    beta, exposure_strength, enable_exposure,
                    searchlight_mult):
    """
    Drive imager exposure / saturation if Octane mapping exists.

    Artistic approximation: the exposure factor is the relativistic
    beaming intensity ``D^(EXPOSURE_BETA_EXPONENT · s)``. In strict
    physics this is the multiplier on specific intensity, not on
    imager exposure, but for a quick "headlight gets brighter as you
    accelerate" look it lands in the right ballpark.

    If Octane parameters are unmapped or no Octane tag is present, we
    only return the computed multiplier so the caller can store it as
    a read-only output. We do NOT touch the C4D camera's exposure --
    standard C4D camera doesn't have a unified exposure field; the
    Physical-Renderer-specific knobs are out of scope for this pass.
    """
    if not enable_exposure:
        factor = 1.0
    else:
        # Reuse the searchlight multiplier as the exposure factor when
        # exposure_strength == effect_strength used elsewhere; otherwise
        # recompute with this slot's own strength.
        factor = RM.searchlight_intensity_factor(
            beta, 1.0, strength=exposure_strength)

    if octane_tag is None:
        return factor

    # Octane "imager_exposure" slot.
    exp_id = OP.get_param_id(OP.PARAM_IMAGER_EXPOSURE)
    if exp_id is not None:
        try:
            current = octane_tag[exp_id]
        except Exception:
            current = None
        baseline_id = _ensure_octane_baseline(
            controller, lookup, OP.PARAM_IMAGER_EXPOSURE, current)
        baseline = _coerce_float(
            controller[baseline_id] if baseline_id is not None else current,
            _coerce_float(current, 1.0))
        try:
            octane_tag[exp_id] = float(baseline * factor)
        except Exception:
            pass

    # Octane "imager_saturation" slot. Highly compressed saturation at
    # extreme blueshift mimics colour washout in beamed light.
    sat_id = OP.get_param_id(OP.PARAM_IMAGER_SATURATION)
    if sat_id is not None and enable_exposure:
        try:
            current = octane_tag[sat_id]
        except Exception:
            current = None
        baseline_id = _ensure_octane_baseline(
            controller, lookup, OP.PARAM_IMAGER_SATURATION, current)
        baseline = _coerce_float(
            controller[baseline_id] if baseline_id is not None else current,
            _coerce_float(current, 1.0))
        # Saturation drops as forward intensity climbs (artistic).
        sat_factor = 1.0 / (1.0 + 0.25 * beta * exposure_strength)
        try:
            octane_tag[sat_id] = float(baseline * sat_factor)
        except Exception:
            pass

    # Octane "postfx_bloom_glare" slot: bigger glare at high beta.
    glare_id = OP.get_param_id(OP.PARAM_POSTFX_BLOOM_GLARE)
    if glare_id is not None and enable_exposure:
        try:
            current = octane_tag[glare_id]
        except Exception:
            current = None
        baseline_id = _ensure_octane_baseline(
            controller, lookup, OP.PARAM_POSTFX_BLOOM_GLARE, current)
        baseline = _coerce_float(
            controller[baseline_id] if baseline_id is not None else current,
            _coerce_float(current, 0.0))
        try:
            octane_tag[glare_id] = float(baseline * (1.0 + beta * exposure_strength))
        except Exception:
            pass

    return factor


def _compute_doppler_temperature_shift(beta, doppler_fwd):
    """
    Approximate Doppler-driven colour-temperature shift in Kelvin.

    Wien's law inverted gives ``T_obs / T_emit = D`` for a blackbody
    peak. We express this as a delta from the rest temperature so the
    sign is intuitive (positive = bluer / approach, negative = redder
    / recession).

    This is a colour-perception cue only -- materials are not modified
    in this pass per the spec.
    """
    if beta == 0.0:
        return 0.0
    return K.COLOR_TEMP_REST_K * doppler_fwd - K.COLOR_TEMP_REST_K


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_ls_camera_rig(doc, controller, camera):
    """
    Re-evaluate the relativistic camera rig.

    Returns a dict of computed quantities, or ``None`` if the call was
    skipped (missing controller / camera).
    """
    if controller is None or camera is None:
        return None

    lookup = _build_ud_lookup(controller)

    # ---- read inputs -------------------------------------------------------
    beta = RM.clamp_beta(_coerce_float(
        _read(controller, lookup, K.UD_BETA_VELOCITY, default=0.0), 0.0))
    strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_EFFECT_STRENGTH, default=1.0), 1.0))
    fov_mode = int(_coerce_float(
        _read(controller, lookup, K.UD_FOV_MODE, default=K.FOV_MODE_SUBTLE),
        K.FOV_MODE_SUBTLE))
    fov_strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_FOV_STRENGTH, default=1.0), 1.0))
    dof_strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_DOF_STRENGTH, default=1.0), 1.0))
    exposure_strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_EXPOSURE_STRENGTH, default=1.0), 1.0))

    contraction_strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_CONTRACTION_STRENGTH, default=1.0), 1.0))
    geom_mode = int(_coerce_float(
        _read(controller, lookup, K.UD_GEOMETRY_MODE, default=K.GEOM_MODE_OFF),
        K.GEOM_MODE_OFF))

    enable_lorentz = bool(_read(controller, lookup, K.UD_ENABLE_LORENTZ, default=True))
    enable_searchlight = bool(_read(controller, lookup, K.UD_ENABLE_SEARCHLIGHT, default=True))
    enable_dof = bool(_read(controller, lookup, K.UD_ENABLE_DOF, default=False))
    enable_exposure = bool(_read(controller, lookup, K.UD_ENABLE_EXPOSURE, default=False))
    enable_octane = bool(_read(controller, lookup, K.UD_ENABLE_OCTANE_TAG, default=False))
    debug = bool(_read(controller, lookup, K.UD_DEBUG_MODE, default=False))

    # ---- relativistic quantities ------------------------------------------
    gamma = RM.gamma_from_beta(beta)
    contraction = RM.lorentz_contraction_factor(beta)
    doppler_fwd = RM.doppler_factor(beta, 1.0)
    searchlight_mult = (
        RM.searchlight_intensity_factor(beta, 1.0, strength=strength)
        if enable_searchlight else 1.0
    )
    doppler_temp_shift = _compute_doppler_temperature_shift(beta, doppler_fwd)

    # ---- locate Octane tag (only if user enabled the integration) --------
    octane_tag = None
    if enable_octane:
        octane_tag = ls_octane.find_existing_octane_tag(camera)
        # Don't auto-attach here -- attaching has user-visible side
        # effects and a per-frame path should never silently mutate the
        # scene graph beyond writing parameters.

    # ---- effect 1: FOV ----------------------------------------------------
    fov_mult = _apply_fov(
        controller, lookup, camera,
        beta=beta, fov_strength=fov_strength,
        enable_lorentz=enable_lorentz, fov_mode=fov_mode,
    )

    # ---- effect 2: Depth of field ----------------------------------------
    dof_factor = _apply_dof(
        controller, lookup, camera, octane_tag,
        beta=beta, dof_strength=dof_strength, enable_dof=enable_dof,
    )

    # ---- effect 3: Exposure / searchlight --------------------------------
    exposure_factor = _apply_exposure(
        controller, lookup, octane_tag,
        beta=beta, exposure_strength=exposure_strength,
        enable_exposure=enable_exposure,
        searchlight_mult=searchlight_mult,
    )

    # ---- effect 4: Doppler colour temperature ----------------------------
    # Scalar output; the Doppler-material colour shift below is the
    # actual material driver.

    # ---- effect 4b: Doppler colour shift on duplicate materials ----------
    # The duplicates themselves are created/removed via the menu commands
    # in ls_doppler_materials.py; this call only paints them every tick.
    # When the Doppler flag is off we snap the duplicates back to their
    # baseline colour so toggling the flag is fully reversible without
    # having to rebuild any duplicates.
    enable_doppler = bool(_read(controller, lookup, K.UD_ENABLE_DOPPLER, default=True))
    doppler_color_strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_DOPPLER_COLOR_STRENGTH, default=1.0), 1.0))
    if enable_doppler:
        # effect_strength compounds with the per-effect strength so a
        # single master slider can dim everything at once.
        ls_doppler_materials.apply_doppler_color_shift(
            doc=doc,
            controller=controller,
            camera=camera,
            beta=beta,
            strength=doppler_color_strength * strength,
        )
    else:
        ls_doppler_materials.restore_baseline_colors(doc)

    # ---- effect 4c: Searchlight per-target intensity --------------------
    # The scalar searchlight_mult above is just a single forward-direction
    # number; the per-target driver here paints viewport colours or
    # material-luminance channels for each "controlled" object. Mode +
    # strength + ceiling come from dedicated UD fields.
    searchlight_strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_SEARCHLIGHT_STRENGTH, default=1.0), 1.0))
    searchlight_mode = int(_coerce_float(
        _read(controller, lookup, K.UD_SEARCHLIGHT_MODE,
              default=K.SEARCHLIGHT_MODE_VIEWPORT),
        K.SEARCHLIGHT_MODE_VIEWPORT))
    max_intensity = max(1.0, _coerce_float(
        _read(controller, lookup, K.UD_MAX_INTENSITY_MULTIPLIER, default=10.0),
        10.0))
    if enable_searchlight:
        ls_searchlight.apply_searchlight(
            doc=doc,
            controller=controller,
            camera=camera,
            beta=beta,
            strength=searchlight_strength * strength,
            mode=searchlight_mode,
            max_intensity=max_intensity,
            debug=debug,
        )
    else:
        ls_searchlight.restore_searchlight(doc)

    # ---- effect 5: Geometry contraction (proxy null) ---------------------
    # The proxy null itself is created/removed via the menu commands in
    # ls_geometry.py; this call only drives its local Z scale every tick.
    # No-op if no proxy exists or geometry_mode is "Off".
    ls_geometry.apply_proxy_contraction(
        doc=doc,
        geom_mode=geom_mode,
        contraction_factor=contraction,
        contraction_strength=contraction_strength,
    )

    # ---- effect 6 (Advanced): Terrell rotation placeholder ---------------
    # Strictly artistic; lives in its own module + own UD flag so it
    # never gets mixed up with the physical approximations above. The
    # heading-axis rotation is composed on top of the proxy's captured
    # baseline rotation so the contraction axis stays aligned, and a
    # restore writes the baseline back when the flag is off.
    enable_terrell = bool(_read(controller, lookup,
                                K.UD_ENABLE_TERRELL_PLACEHOLDER,
                                default=False))
    terrell_strength = max(0.0, _coerce_float(
        _read(controller, lookup, K.UD_TERRELL_STRENGTH, default=1.0), 1.0))
    proxy = ls_geometry.find_existing_proxy(doc)
    if enable_terrell:
        ls_terrell.apply_terrell_placeholder(
            proxy_object=proxy,
            camera=camera,
            beta=beta,
            strength=terrell_strength * strength,
        )
    else:
        ls_terrell.restore_terrell(proxy)

    # ---- diagnostics: cos-theta heatmap (after Doppler/searchlight) ------
    # When debug_material_preview is on, override LS_Doppler_<x> colours
    # with a heatmap so the user can see at a glance which surfaces the
    # rig considers approaching vs receding. Runs *after* the Doppler
    # and searchlight passes so the heatmap wins for that tick;
    # toggling the flag off lets the next tick's Doppler shift overwrite
    # the heatmap automatically.
    debug_material_preview = bool(_read(controller, lookup,
                                        K.UD_DEBUG_MATERIAL_PREVIEW,
                                        default=False))
    if debug_material_preview:
        ls_diagnostics.apply_debug_material_preview(doc, controller, camera)

    # ---- write outputs ---------------------------------------------------
    _write(controller, lookup, K.UD_OUT_GAMMA, float(gamma))
    _write(controller, lookup, K.UD_OUT_CONTRACTION, float(contraction))
    _write(controller, lookup, K.UD_OUT_DOPPLER_FWD, float(doppler_fwd))
    _write(controller, lookup, K.UD_OUT_SEARCHLIGHT, float(searchlight_mult))
    _write(controller, lookup, K.UD_OUT_DOPPLER_TEMP_SHIFT, float(doppler_temp_shift))

    motion_blur_mult = 1.0 + K.MOTION_BLUR_BETA_COEFF * beta * strength

    if debug:
        geom_label = K.GEOM_MODE_ITEMS[geom_mode] if 0 <= geom_mode < len(K.GEOM_MODE_ITEMS) else str(geom_mode)
        print(
            "[C4D_ls-cam][debug] beta={0:.4f} strength={1:.3f} "
            "gamma={2:.4f} contraction={3:.4f} doppler_fwd={4:.4f} "
            "searchlight={5:.4g} fov_mult={6:.4f} dof_factor={7:.4f} "
            "exposure_factor={8:.4g} doppler_dT={9:+.1f}K "
            "mb_mult={10:.4f} geom={11} octane_tag={12}".format(
                beta, strength, gamma, contraction, doppler_fwd,
                searchlight_mult, fov_mult, dof_factor, exposure_factor,
                doppler_temp_shift, motion_blur_mult, geom_label,
                "yes" if octane_tag is not None else "no",
            )
        )

    computed = {
        "beta": beta,
        "strength": strength,
        "gamma": gamma,
        "contraction_factor": contraction,
        "doppler_forward_factor": doppler_fwd,
        "searchlight_multiplier": searchlight_mult,
        "doppler_temperature_shift": doppler_temp_shift,
        "fov_multiplier": fov_mult,
        "dof_factor": dof_factor,
        "exposure_factor": exposure_factor,
        "motion_blur_multiplier": motion_blur_mult,
        "octane_tag_present": octane_tag is not None,
    }

    # ---- diagnostics: HUD overlay text (cheap walk if no overlay) --------
    ls_diagnostics.update_overlay(camera, computed)

    return computed


def reset_ls_camera_rig(doc, controller, camera):
    """
    Restore the rig's camera (and any touched Octane parameters) to the
    state captured at rig creation.

    Idempotent: calling reset twice is safe. If a baseline is missing
    (e.g. the user deleted an internal cache field) the corresponding
    reset is silently skipped rather than raising -- a partial restore
    is better than aborting in the middle.

    Behaviour
    ---------
    * Camera FOV  -> ``_rest_fov_rad``
    * Camera focus distance / aperture -> ``_rest_focus_dist`` / ``_rest_aperture``
    * Octane mapped params -> per-slot ``_baseline_octane_<slot>`` fields
    * Computed output user-data fields -> their identity values
      (gamma=1, contraction=1, doppler_fwd=1, searchlight=1,
      doppler_temp_shift=0)

    The user's *input* fields (beta_velocity, fov_mode, ...) are left
    alone -- reset undoes the rig's effect on the scene, not the user's
    parameter choices.
    """
    if controller is None or camera is None:
        return False

    lookup = _build_ud_lookup(controller)

    # ---- camera ------------------------------------------------------------
    rest_fov = _coerce_float(_read(controller, lookup, K.UD_REST_FOV_RAD, 0.0), 0.0)
    if rest_fov > 0.0:
        try:
            camera[c4d.CAMERAOBJECT_FOV] = float(rest_fov)
        except Exception:
            pass

    rest_focus = _coerce_float(_read(controller, lookup, K.UD_REST_FOCUS_DIST, 0.0), 0.0)
    if rest_focus > 0.0:
        try:
            camera[c4d.CAMERAOBJECT_TARGETDISTANCE] = float(rest_focus)
        except Exception:
            pass

    rest_aperture = _coerce_float(_read(controller, lookup, K.UD_REST_APERTURE, 0.0), 0.0)
    if rest_aperture > 0.0:
        try:
            camera[c4d.CAMERAOBJECT_APERTURE] = float(rest_aperture)
        except Exception:
            pass

    # ---- Octane ------------------------------------------------------------
    octane_tag = ls_octane.find_existing_octane_tag(camera)
    if octane_tag is not None:
        for slot_key in OP.OCTANE_CAMERA_PARAMS.keys():
            param_id = OP.get_param_id(slot_key)
            if param_id is None:
                continue
            label = _octane_baseline_label(slot_key)
            baseline_desc = lookup.get(label)
            if baseline_desc is None:
                continue
            try:
                value = controller[baseline_desc]
            except Exception:
                continue
            try:
                octane_tag[param_id] = value
            except Exception:
                # Wrong dtype? Try bool / int conversion before giving up.
                try:
                    octane_tag[param_id] = bool(value)
                except Exception:
                    pass

    # ---- outputs back to identity values ----------------------------------
    _write(controller, lookup, K.UD_OUT_GAMMA, 1.0)
    _write(controller, lookup, K.UD_OUT_CONTRACTION, 1.0)
    _write(controller, lookup, K.UD_OUT_DOPPLER_FWD, 1.0)
    _write(controller, lookup, K.UD_OUT_SEARCHLIGHT, 1.0)
    _write(controller, lookup, K.UD_OUT_DOPPLER_TEMP_SHIFT, 0.0)

    # ---- snap Doppler material duplicates back to baseline (if any) -----
    # We do NOT delete the duplicates -- restoration of the originals is
    # the explicit "LS Cam: Restore Original Materials" command. Reset
    # just paints the duplicates with their baseline RGB so the viewport
    # looks as it did before any beta sweep.
    ls_doppler_materials.restore_baseline_colors(doc)

    # ---- restore searchlight baselines ------------------------------------
    # Both viewport and material-luminance modes leave private BC slots
    # on each touched object/material; restore writes the baseline back
    # and clears the markers so the next enable re-captures from the
    # current state.
    ls_searchlight.restore_searchlight(doc)

    # ---- restore Terrell placeholder rotation (if any) -------------------
    # The placeholder stamps its baseline onto the proxy itself, so we
    # find the proxy first and hand it to ls_terrell.restore_terrell.
    # Cheap when there's no marker (single BC read).
    proxy_for_terrell = ls_geometry.find_existing_proxy(doc)
    ls_terrell.restore_terrell(proxy_for_terrell)

    # ---- snap geometry proxy back to identity scale (if present) ---------
    # We do NOT delete or unwrap the proxy here -- removal is the
    # explicit "LS Cam: Remove Relativistic Geometry Proxy" command.
    # Reset just zeroes out the live contraction so the proxy's
    # children are visible at full size again.
    proxy = ls_geometry.find_existing_proxy(doc)
    if proxy is not None:
        try:
            proxy[c4d.ID_BASEOBJECT_REL_SCALE] = c4d.Vector(1.0, 1.0, 1.0)
        except Exception:
            pass

    c4d.EventAdd()
    return True
