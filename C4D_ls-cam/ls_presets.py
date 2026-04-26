"""
ls_presets.py
=============
Curated beta / strength presets inspired by MIT Game Lab's
*A Slower Speed of Light*.

Each preset writes a small set of controller user-data fields:

    * ``beta_velocity``
    * ``effect_strength``
    * ``fov_strength``
    * ``dof_strength``
    * ``doppler_color_strength``
    * ``searchlight_strength``
    * ``contraction_strength``

Presets only touch *strength* knobs and beta -- they intentionally do
not flip the per-effect ``enable_*`` toggles, the ``geometry_mode`` /
``searchlight_mode`` enums, or the ``debug_mode`` flag. That keeps the
presets safe to re-apply on any rig regardless of how the user has
configured the toggles, and means a preset never accidentally enables
geometry contraction in a scene where the proxy hasn't been built.

Editing presets
---------------
The :data:`PRESETS_ORDERED` list is the single source of truth -- add,
remove, or rename entries there and both the dialog dropdown and the
:func:`apply_preset` lookup will see the change. Each entry is a
``(name, dict)`` tuple; the dict maps any of the constants in
:mod:`ls_constants` to the value to write. Unknown / typo'd keys are
ignored at apply time (with a console warning), so renaming a UD
constant won't crash the preset system.
"""

import ls_constants as K
# c4d / ls_ui are imported lazily inside the functions that need them so
# this module can be sanity-checked outside Cinema 4D.


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------
# Format: (display name, { K.UD_<key>: numeric_value, ... })
#
# Beta values are taken verbatim from the project brief. The strength
# values are tuned to "feel right" at the corresponding beta -- gentle
# at low beta, exaggerated at high beta. Easy to retune without touching
# any other module: edit the dict literal below.

PRESETS_ORDERED = [
    ("Human Speed", {
        # Effect should be invisible at human speeds; we still write the
        # default 1.0 strengths so a previous preset's exaggerated values
        # don't linger when the artist switches back.
        K.UD_BETA_VELOCITY: 0.001,
        K.UD_EFFECT_STRENGTH: 1.0,
        K.UD_FOV_STRENGTH: 1.0,
        K.UD_DOF_STRENGTH: 0.0,        # no DoF break at human speed
        K.UD_DOPPLER_COLOR_STRENGTH: 1.0,
        K.UD_SEARCHLIGHT_STRENGTH: 1.0,
        K.UD_CONTRACTION_STRENGTH: 1.0,
    }),
    ("Orb 25", {
        K.UD_BETA_VELOCITY: 0.25,
        K.UD_EFFECT_STRENGTH: 1.0,
        K.UD_FOV_STRENGTH: 1.0,
        K.UD_DOF_STRENGTH: 0.5,
        K.UD_DOPPLER_COLOR_STRENGTH: 1.0,
        K.UD_SEARCHLIGHT_STRENGTH: 1.0,
        K.UD_CONTRACTION_STRENGTH: 1.0,
    }),
    ("Orb 50", {
        K.UD_BETA_VELOCITY: 0.50,
        K.UD_EFFECT_STRENGTH: 1.0,
        K.UD_FOV_STRENGTH: 1.0,
        K.UD_DOF_STRENGTH: 1.0,
        K.UD_DOPPLER_COLOR_STRENGTH: 1.0,
        K.UD_SEARCHLIGHT_STRENGTH: 1.0,
        K.UD_CONTRACTION_STRENGTH: 1.0,
    }),
    ("Orb 75", {
        K.UD_BETA_VELOCITY: 0.75,
        K.UD_EFFECT_STRENGTH: 1.0,
        K.UD_FOV_STRENGTH: 1.0,
        K.UD_DOF_STRENGTH: 1.0,
        K.UD_DOPPLER_COLOR_STRENGTH: 1.2,
        K.UD_SEARCHLIGHT_STRENGTH: 1.2,
        K.UD_CONTRACTION_STRENGTH: 1.0,
    }),
    ("Near Light", {
        K.UD_BETA_VELOCITY: 0.95,
        K.UD_EFFECT_STRENGTH: 1.5,
        K.UD_FOV_STRENGTH: 1.5,
        K.UD_DOF_STRENGTH: 1.5,
        K.UD_DOPPLER_COLOR_STRENGTH: 1.5,
        K.UD_SEARCHLIGHT_STRENGTH: 1.5,
        K.UD_CONTRACTION_STRENGTH: 1.0,
    }),
    ("Absurd Artistic", {
        # beta_velocity max is 0.999 in UD_RANGES; 0.99 is well inside.
        K.UD_BETA_VELOCITY: 0.99,
        K.UD_EFFECT_STRENGTH: 2.0,
        K.UD_FOV_STRENGTH: 2.0,
        K.UD_DOF_STRENGTH: 2.0,
        K.UD_DOPPLER_COLOR_STRENGTH: 2.0,
        K.UD_SEARCHLIGHT_STRENGTH: 2.0,
        K.UD_CONTRACTION_STRENGTH: 1.0,
    }),
]

# Dict view for O(1) name lookup. Built once at import time.
PRESETS = dict(PRESETS_ORDERED)


def list_preset_names():
    """Return preset names in display order."""
    return [name for name, _ in PRESETS_ORDERED]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_ud_lookup(host):
    """Map UD label string -> DescID for every user-data field on *host*."""
    import c4d  # local: keeps module importable outside Cinema 4D
    out = {}
    for desc_id, bc in host.GetUserDataContainer():
        out[bc[c4d.DESC_NAME]] = desc_id
    return out


def _write_ud(host, lookup, key, value):
    """
    Write *value* to user-data parameter *key* on *host*.

    Returns True on success, False if the field is missing or write
    failed. Per-field write errors are tolerated so one mismatched
    constant can't abort the whole preset application.
    """
    label = K.UD_LABELS.get(key)
    if label is None:
        return False
    desc_id = lookup.get(label)
    if desc_id is None:
        return False
    try:
        host[desc_id] = value
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_preset(controller, preset_name):
    """
    Write the named preset's values to *controller*'s user data.

    Parameters
    ----------
    controller : c4d.BaseTag
        The LS_Relativity_Controller Python tag.
    preset_name : str
        One of :func:`list_preset_names`.

    Returns
    -------
    int
        Number of user-data fields successfully written. ``0`` means
        nothing matched (bad preset name, missing controller, or every
        field was missing on the controller).
    """
    if controller is None:
        return 0

    # Local imports keep the module importable outside Cinema 4D.
    import c4d
    import ls_ui

    preset = PRESETS.get(preset_name)
    if preset is None:
        ls_ui.log("apply_preset: unknown preset '{0}'.".format(preset_name))
        return 0

    lookup = _build_ud_lookup(controller)
    written = 0
    skipped = []
    for key, value in preset.items():
        if _write_ud(controller, lookup, key, value):
            written += 1
        else:
            skipped.append(key)

    if skipped:
        ls_ui.log(
            "apply_preset '{0}': {1} field(s) not present on this "
            "controller and were skipped: {2}".format(
                preset_name, len(skipped), skipped
            )
        )

    # Trigger a redraw + scene evaluation so the new values are picked
    # up by the controller's Python tag immediately.
    c4d.EventAdd()
    return written
