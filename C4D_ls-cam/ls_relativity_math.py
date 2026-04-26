"""
ls_relativity_math.py
=====================
Pure-Python helpers for special-relativistic visual effects.

This module is intentionally **independent from Cinema 4D**: it imports only
the standard library, takes plain numbers / tuples, and returns plain
numbers / tuples. That way it can be unit-tested outside C4D, reused from a
Python tag, or eventually ported to a shader.

Conventions
-----------
* ``beta`` is the speed of the camera relative to the scene, expressed as a
  fraction of the speed of light: ``beta = v / c``.
* ``cos_theta`` is the cosine of the angle between the camera's direction
  of motion and the line of sight to a given point in the scene, measured
  in the **observer's** frame. ``cos_theta == 1`` means the point lies
  straight ahead; ``cos_theta == -1`` means it lies straight behind.
* All formulas use approximations suitable for visual art, not for
  laboratory-grade physics. They are stable, monotonic, and bounded; they
  are *not* meant to reproduce exact spectral radiance.

References
----------
* Relativistic aberration:  cos(theta') = (cos(theta) - beta) / (1 - beta cos(theta))
* Relativistic Doppler:     D = 1 / (gamma (1 - beta cos(theta)))
* Relativistic beaming:     I_obs / I_src ~ D^4  (specific intensity)

Effect classification used across the project
---------------------------------------------
Comments throughout the codebase prefix each computation with one of:

    [PHYSICAL]      -- formula derived from special relativity; bounded
                       and stable, suitable for visual approximation but
                       not for laboratory measurements.
    [ARTISTIC]      -- knob with no direct physical meaning; tuned by
                       feel. Always gated by a strength slider so
                       artists can dial the effect down to identity.
    [UNIMPLEMENTED] -- placeholder where a real ray-level pass would
                       live. Comment explains what the real
                       implementation would have to compute.

Every helper in *this* module is [PHYSICAL] (with the artistic
``strength`` knobs documented per-function).
"""

import math


# ---------------------------------------------------------------------------
# Internal limits
# ---------------------------------------------------------------------------

# Hard ceiling on |beta| to keep gamma finite. The user-data slider already
# stops at 0.999, but downstream code might call us with raw values, so we
# defend ourselves here too.
_BETA_MAX = 0.999999

# Floor on the Doppler-denominator (1 - beta cos_theta). When the source
# moves directly toward the observer at beta -> 1 this denominator goes to
# zero; we clamp it so the output stays representable.
_DENOM_MIN = 1.0e-6


# ---------------------------------------------------------------------------
# Core scalar helpers
# ---------------------------------------------------------------------------

def clamp_beta(beta):
    """
    Clamp ``beta`` into the open interval (-1, 1) using a small safety margin.

    Returning |beta| == 1 would make ``gamma`` blow up; returning anything
    above 1 would make ``sqrt(1 - beta^2)`` imaginary. We therefore squeeze
    the input into ``[-_BETA_MAX, _BETA_MAX]`` (default ``+/- 0.999999``).

    Parameters
    ----------
    beta : float
        Velocity as a fraction of the speed of light. May be negative.

    Returns
    -------
    float
        ``beta`` clamped to ``[-_BETA_MAX, _BETA_MAX]``.
    """
    b = float(beta)
    if b > _BETA_MAX:
        return _BETA_MAX
    if b < -_BETA_MAX:
        return -_BETA_MAX
    return b


def gamma_from_beta(beta):
    """
    Lorentz factor ``gamma = 1 / sqrt(1 - beta^2)``.

    The input is clamped via :func:`clamp_beta` first, so this function is
    safe to call for any finite float.

    Parameters
    ----------
    beta : float
        Velocity as a fraction of the speed of light.

    Returns
    -------
    float
        Always >= 1.0.
    """
    b = clamp_beta(beta)
    return 1.0 / math.sqrt(1.0 - b * b)


def lorentz_contraction_factor(beta):
    """
    Length-contraction factor along the direction of motion.

    A moving rod of rest length ``L0`` is observed to have length
    ``L = L0 * lorentz_contraction_factor(beta)``. Equivalently this is
    ``1 / gamma == sqrt(1 - beta^2)``.

    Parameters
    ----------
    beta : float
        Velocity as a fraction of the speed of light.

    Returns
    -------
    float
        A value in ``(0, 1]``. ``1.0`` at ``beta == 0``, approaching ``0``
        as ``|beta|`` approaches ``1``.
    """
    b = clamp_beta(beta)
    return math.sqrt(1.0 - b * b)


def doppler_factor(beta, cos_theta):
    """
    Relativistic Doppler factor ``D``.

    ``D = f_obs / f_emit = 1 / (gamma * (1 - beta * cos(theta)))``

    * ``D > 1`` means blueshift (the source is approaching).
    * ``D < 1`` means redshift  (the source is receding).
    * ``D == 1`` only at ``beta == 0``.

    The denominator is clamped to ``_DENOM_MIN`` so the result remains
    finite even when ``beta -> 1`` and ``cos_theta -> 1`` (a head-on
    approach).

    Parameters
    ----------
    beta : float
        Velocity as a fraction of the speed of light.
    cos_theta : float
        Cosine of the line-of-sight angle in the observer frame.

    Returns
    -------
    float
        Strictly positive Doppler factor.
    """
    b = clamp_beta(beta)
    gamma = gamma_from_beta(b)
    denom = gamma * (1.0 - b * float(cos_theta))
    if denom < _DENOM_MIN:
        denom = _DENOM_MIN
    return 1.0 / denom


def relativistic_aberration_cos(beta, cos_theta):
    """
    Apply relativistic aberration to a line-of-sight cosine.

    Given a direction with cosine ``cos_theta`` in the rest frame, return
    the cosine of the same direction as seen by an observer moving with
    velocity ``beta`` along the reference axis:

        cos(theta') = (cos(theta) - beta) / (1 - beta * cos(theta))

    The result is clamped to ``[-1, 1]`` to absorb any tiny floating-point
    overshoot from the analytic formula.

    Parameters
    ----------
    beta : float
        Observer velocity as a fraction of the speed of light.
    cos_theta : float
        Cosine in the original (rest) frame.

    Returns
    -------
    float
        Cosine in the moving (observer) frame, in ``[-1, 1]``.
    """
    b = clamp_beta(beta)
    c = float(cos_theta)
    denom = 1.0 - b * c
    if abs(denom) < _DENOM_MIN:
        denom = _DENOM_MIN if denom >= 0 else -_DENOM_MIN
    out = (c - b) / denom
    if out > 1.0:
        return 1.0
    if out < -1.0:
        return -1.0
    return out


def searchlight_intensity_factor(beta, cos_theta, strength=1.0):
    """
    Relativistic-beaming (a.k.a. "headlight" or "searchlight") intensity factor.

    For specific intensity, the standard result is ``I_obs / I_src = D^4``
    where ``D`` is the Doppler factor. We expose ``strength`` as an artistic
    knob: the effective exponent becomes ``4 * strength``, so

        * ``strength == 0``  -> factor is always 1.0 (effect off)
        * ``strength == 1``  -> physically motivated D^4
        * ``strength == 2``  -> exaggerated D^8

    Parameters
    ----------
    beta : float
        Observer velocity as a fraction of the speed of light.
    cos_theta : float
        Cosine of the line-of-sight angle in the observer frame.
    strength : float, optional
        Artistic scale for the exponent. Default ``1.0`` (physical).

    Returns
    -------
    float
        Strictly positive intensity multiplier.
    """
    d = doppler_factor(beta, cos_theta)
    s = float(strength)
    if s <= 0.0:
        return 1.0
    return math.pow(d, 4.0 * s)


# ---------------------------------------------------------------------------
# Color shift
# ---------------------------------------------------------------------------

def _clamp01(x):
    """Clamp a single float into ``[0, 1]``."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def wavelength_shift_rgb_approx(rgb, doppler_factor, strength=1.0):
    """
    Approximate Doppler color shift on a linear-ish RGB triple.

    This is a *visual* approximation, not a spectral renderer. We treat R,
    G, B as three lobes along an ordered "wavelength" axis (R = long
    wavelength, B = short wavelength) and slide energy between adjacent
    channels:

      * blueshift (``D > 1``)  -> R drains into G, G drains into B
      * redshift  (``D < 1``)  -> B drains into G, G drains into R

    The amount of bleed is ``alpha = clamp((D - 1) * strength, -1, 1)``.
    Total energy is approximately preserved (sum of channels stays close to
    its input), and each channel is finally clamped to ``[0, 1]`` so the
    output is safe to feed to any sRGB-style display path.

    For exact spectral results you would integrate the source SPD against
    shifted CIE matching curves; we deliberately avoid that complexity at
    the skeleton stage.

    Parameters
    ----------
    rgb : tuple[float, float, float]
        Input color, each channel in ``[0, 1]`` (values outside that range
        are tolerated but the output is always clamped).
    doppler_factor : float
        Doppler factor ``D`` from :func:`doppler_factor`. ``1.0`` means no
        shift.
    strength : float, optional
        Artistic multiplier. ``0`` disables the effect; ``1`` is the
        default; values above ``1`` exaggerate it.

    Returns
    -------
    tuple[float, float, float]
        Shifted RGB triple.
    """
    r, g, b = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    s = float(strength)
    if s <= 0.0:
        return (_clamp01(r), _clamp01(g), _clamp01(b))

    alpha = (float(doppler_factor) - 1.0) * s
    if alpha > 1.0:
        alpha = 1.0
    elif alpha < -1.0:
        alpha = -1.0

    if alpha > 0.0:
        # Blueshift: cascade R -> G -> B.
        r_out = r * (1.0 - alpha)
        g_out = g * (1.0 - alpha) + r * alpha
        b_out = b + g * alpha
    elif alpha < 0.0:
        # Redshift: cascade B -> G -> R.
        a = -alpha
        b_out = b * (1.0 - a)
        g_out = g * (1.0 - a) + b * a
        r_out = r + g * a
    else:
        r_out, g_out, b_out = r, g, b

    return (_clamp01(r_out), _clamp01(g_out), _clamp01(b_out))


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run with:  python ls_relativity_math.py
    # No external test framework so the file works in any Python install.

    EPS = 1e-9

    def _close(a, b, tol=1e-6):
        return abs(a - b) <= tol

    # --- clamp_beta ---------------------------------------------------------
    assert clamp_beta(0.0) == 0.0
    assert clamp_beta(0.5) == 0.5
    assert clamp_beta(1.5) <= _BETA_MAX
    assert clamp_beta(-2.0) >= -_BETA_MAX
    assert clamp_beta(_BETA_MAX) == _BETA_MAX

    # --- gamma_from_beta ---------------------------------------------------
    assert _close(gamma_from_beta(0.0), 1.0)
    # beta = 0.6 -> gamma = 1.25 exactly.
    assert _close(gamma_from_beta(0.6), 1.25)
    # gamma is symmetric in beta.
    assert _close(gamma_from_beta(-0.6), gamma_from_beta(0.6))
    # gamma must be finite even at the cap.
    assert math.isfinite(gamma_from_beta(0.999999999))

    # --- lorentz_contraction_factor ----------------------------------------
    assert _close(lorentz_contraction_factor(0.0), 1.0)
    # At beta = 0.6, contraction factor = 0.8.
    assert _close(lorentz_contraction_factor(0.6), 0.8)
    # Contraction is always in (0, 1] for any beta.
    for b in (0.1, 0.5, 0.9, 0.999):
        f = lorentz_contraction_factor(b)
        assert 0.0 < f <= 1.0

    # --- doppler_factor ----------------------------------------------------
    # At rest, Doppler factor must be 1 regardless of angle.
    for c in (-1.0, -0.3, 0.0, 0.7, 1.0):
        assert _close(doppler_factor(0.0, c), 1.0)
    # Approaching (cos_theta = 1) yields blueshift D > 1.
    assert doppler_factor(0.5, 1.0) > 1.0
    # Receding (cos_theta = -1) yields redshift D < 1.
    assert doppler_factor(0.5, -1.0) < 1.0
    # Output is always strictly positive (no zero / negative).
    assert doppler_factor(0.999999, 1.0) > 0.0

    # --- relativistic_aberration_cos --------------------------------------
    # Identity at beta = 0.
    for c in (-1.0, -0.4, 0.0, 0.7, 1.0):
        assert _close(relativistic_aberration_cos(0.0, c), c)
    # cos = 1 maps to cos = 1 (forward stays forward).
    assert _close(relativistic_aberration_cos(0.7, 1.0), 1.0)
    # cos = -1 maps to cos = -1 (backward stays backward).
    assert _close(relativistic_aberration_cos(0.7, -1.0), -1.0)
    # A perpendicular ray in the rest frame (cos = 0) appears tilted
    # backward in the moving frame: cos(theta') = (0 - beta) / (1 - 0) = -beta.
    assert _close(relativistic_aberration_cos(0.7, 0.0), -0.7)
    # Output always in [-1, 1].
    for b in (0.1, 0.5, 0.9):
        for c in (-1.0, -0.5, 0.0, 0.5, 1.0):
            o = relativistic_aberration_cos(b, c)
            assert -1.0 <= o <= 1.0

    # --- searchlight_intensity_factor -------------------------------------
    # strength = 0 disables the effect.
    assert _close(searchlight_intensity_factor(0.9, 1.0, strength=0.0), 1.0)
    # At rest, factor is always 1.
    assert _close(searchlight_intensity_factor(0.0, 0.5, strength=1.0), 1.0)
    # Forward intensity is amplified, backward is suppressed.
    fwd = searchlight_intensity_factor(0.5, 1.0)
    bwd = searchlight_intensity_factor(0.5, -1.0)
    assert fwd > 1.0 > bwd > 0.0
    # Stronger 'strength' amplifies the asymmetry.
    assert searchlight_intensity_factor(0.5, 1.0, strength=2.0) > fwd

    # --- wavelength_shift_rgb_approx --------------------------------------
    # No shift when strength = 0.
    assert wavelength_shift_rgb_approx((0.4, 0.5, 0.6), 1.5, strength=0.0) == (0.4, 0.5, 0.6)
    # No shift when D == 1.
    assert wavelength_shift_rgb_approx((0.4, 0.5, 0.6), 1.0) == (0.4, 0.5, 0.6)
    # Blueshift moves energy from R toward B.
    r0, g0, b0 = 1.0, 0.0, 0.0
    r1, g1, b1 = wavelength_shift_rgb_approx((r0, g0, b0), 1.5)
    assert r1 < r0
    assert g1 > g0
    # Redshift moves energy from B toward R.
    r0, g0, b0 = 0.0, 0.0, 1.0
    r1, g1, b1 = wavelength_shift_rgb_approx((r0, g0, b0), 0.5)
    assert b1 < b0
    assert g1 > g0
    # Output is always in [0, 1].
    for D in (0.1, 0.5, 1.0, 1.5, 3.0):
        out = wavelength_shift_rgb_approx((0.7, 0.3, 0.9), D, strength=1.5)
        for ch in out:
            assert 0.0 <= ch <= 1.0

    print("ls_relativity_math: all self-tests passed.")
