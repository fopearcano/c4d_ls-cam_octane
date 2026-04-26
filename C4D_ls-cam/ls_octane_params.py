"""
ls_octane_params.py
===================
Symbolic mapping table for Octane Camera Tag parameters.

Why this file exists
--------------------
Octane for Cinema 4D exposes its camera-tag parameters via numeric IDs
that are **not** part of any public, version-stable schema. The IDs can
shift between Octane releases and even between Octane "Studio" /
"Enterprise" / "Demo" builds. Hardcoding them blindly would silently
poke the wrong knobs (or, worse, no knobs at all) on machines we never
tested against.

Instead, we keep a table of *symbolic* parameter slots here. Each slot
records:

    * a human-readable name
    * a short description of what the slot is meant to control
    * a placeholder ``param_id`` of ``None``

The integrator (you) is expected to:

    1. Open a scene with the installed Octane build.
    2. Select an Octane Camera Tag.
    3. Run :func:`ls_octane.dump_octane_tag_parameters` from the C4D
       Python console (or set ``debug_mode`` on the controller and trigger
       it from there once the helper is wired into a menu command).
    4. Copy the printed DescID for each slot into this file by replacing
       the corresponding ``None`` value.

Until a slot's ``param_id`` is filled in, downstream code MUST treat the
slot as "not yet mapped" and skip it -- never guess.

Param-ID format
---------------
Octane params are accessed in C4D Python via ``c4d.DescID`` objects, e.g.

    c4d.DescID(c4d.DescLevel(1234, c4d.DTYPE_REAL, 0))

For convenience this file lets you store either:

    * a plain ``int`` (the DescID's first level), in which case downstream
      code wraps it in a single-level DescID at access time, or
    * a fully-formed ``c4d.DescID`` if you need a multi-level descriptor.

Both are valid; pick whichever the dump shows.
"""

# ---------------------------------------------------------------------------
# Symbolic parameter slots
# ---------------------------------------------------------------------------
# Every slot is keyed by a stable string used elsewhere in the plugin. The
# string keys are the contract; the numeric IDs are an implementation
# detail that may change per Octane version.

# Depth-of-field master switch / state.
PARAM_DEPTH_OF_FIELD = "depth_of_field"

# Aperture size (controls bokeh width).
PARAM_APERTURE = "aperture"

# Motion-blur master switch / shutter.
PARAM_MOTION_BLUR = "motion_blur"

# Imager exposure (EV / linear multiplier, version-dependent).
PARAM_IMAGER_EXPOSURE = "imager_exposure"

# Imager saturation.
PARAM_IMAGER_SATURATION = "imager_saturation"

# Post-processing bloom / glare master amount.
PARAM_POSTFX_BLOOM_GLARE = "postfx_bloom_glare"


# ---------------------------------------------------------------------------
# Mapping table -- ALL ENTRIES START AS None.
# ---------------------------------------------------------------------------
# Replace ``"param_id": None`` with the DescID dumped from your Octane
# install. Do NOT commit guessed IDs -- a wrong ID can silently misroute
# the value into an unrelated parameter.
#
# Schema:
#   <key>: {
#       "label":        str  -- human-readable name shown in logs
#       "description":  str  -- one-line "what this controls"
#       "param_id":     int | c4d.DescID | None
#   }

OCTANE_CAMERA_PARAMS = {
    PARAM_DEPTH_OF_FIELD: {
        "label": "Depth of Field",
        "description": "Enables / disables Octane's DoF integrator on the camera.",
        "param_id": None,  # TODO: fill from dump_octane_tag_parameters()
    },
    PARAM_APERTURE: {
        "label": "Aperture",
        "description": "Lens aperture size; drives bokeh diameter.",
        "param_id": None,  # TODO: fill from dump_octane_tag_parameters()
    },
    PARAM_MOTION_BLUR: {
        "label": "Motion Blur",
        "description": "Camera motion-blur shutter / strength.",
        "param_id": None,  # TODO: fill from dump_octane_tag_parameters()
    },
    PARAM_IMAGER_EXPOSURE: {
        "label": "Imager Exposure",
        "description": "Output imager exposure (EV or linear, per Octane version).",
        "param_id": None,  # TODO: fill from dump_octane_tag_parameters()
    },
    PARAM_IMAGER_SATURATION: {
        "label": "Imager Saturation",
        "description": "Output imager saturation.",
        "param_id": None,  # TODO: fill from dump_octane_tag_parameters()
    },
    PARAM_POSTFX_BLOOM_GLARE: {
        "label": "Post FX: Bloom / Glare",
        "description": "Post-processing bloom or glare master amount.",
        "param_id": None,  # TODO: fill from dump_octane_tag_parameters()
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_param_mapped(key):
    """Return True if *key* has a non-None ``param_id`` entry."""
    entry = OCTANE_CAMERA_PARAMS.get(key)
    if entry is None:
        return False
    return entry.get("param_id") is not None


def get_param_id(key):
    """Return the raw param_id for *key* or ``None`` if unmapped."""
    entry = OCTANE_CAMERA_PARAMS.get(key)
    if entry is None:
        return None
    return entry.get("param_id")


def unmapped_keys():
    """List every slot that still has ``param_id is None``."""
    return [k for k, v in OCTANE_CAMERA_PARAMS.items() if v.get("param_id") is None]
