"""
ls_constants.py
---------------
Centralized constants for the C4D_ls-cam plugin.

Keeping IDs, names, and parameter keys in one place avoids drift between the
rig builder, the UI layer, and the Octane integration helpers.
"""

# ---------------------------------------------------------------------------
# Plugin identity
# ---------------------------------------------------------------------------

# NOTE: Cinema 4D plugin IDs MUST be registered with Maxon at
# https://plugincafe.maxon.net/c4dpluginid_cp before public distribution.
# The value below is a development-only placeholder in the user-id range
# (1000001 - 1000010) reserved by Maxon for in-house testing. Replace it
# with a registered ID before shipping the plugin.
PLUGIN_ID = 1000001

PLUGIN_NAME = "C4D_ls-cam"
COMMAND_NAME = "Create LS Relativistic Camera Rig"
COMMAND_HELP = "Builds a relativistic camera rig (camera + null + controller tag)."

# ---------------------------------------------------------------------------
# Object names used in the C4D scene
# ---------------------------------------------------------------------------

CAMERA_NAME = "LS_Relativistic_Camera"
RIG_NULL_NAME = "LS_Camera_Rig"
CONTROLLER_TAG_NAME = "LS_Relativity_Controller"

# ---------------------------------------------------------------------------
# User-data parameter keys
# ---------------------------------------------------------------------------
# These string keys are the source of truth for the user-data layout. The
# rig builder uses them as labels and the UI / future relativistic math
# modules can look up the corresponding DescID from a dict on the tag.

UD_BETA_VELOCITY = "beta_velocity"
UD_SOL_SCALE = "speed_of_light_scale"
UD_ENABLE_LORENTZ = "enable_lorentz_geometry"
UD_ENABLE_DOPPLER = "enable_doppler_color"
UD_ENABLE_SEARCHLIGHT = "enable_searchlight_effect"
UD_ENABLE_OCTANE_TAG = "enable_octane_camera_tag"
UD_EFFECT_STRENGTH = "effect_strength"
UD_DEBUG_MODE = "debug_mode"

# ---- Computed (read-only) outputs --------------------------------------------
# These fields are written by ls_evaluator.update_ls_camera_rig() every time
# the controller is evaluated. They are exposed as user-data so artists can
# see the effective values in the Attribute Manager, but they are
# overwritten on every evaluation -- treat them as read-only.
UD_OUT_GAMMA = "gamma"
UD_OUT_CONTRACTION = "contraction_factor"
UD_OUT_DOPPLER_FWD = "doppler_forward_factor"
UD_OUT_SEARCHLIGHT = "searchlight_multiplier"

# ---- Internal cache ---------------------------------------------------------
# The camera's FOV at rig-creation time. We capture this so FOV updates
# stay non-destructive: the live FOV is always derived from this stored
# baseline rather than from the previous frame's value (which would drift).
UD_REST_FOV_RAD = "_rest_fov_rad"

# Set of UD keys that are computed outputs (used by the evaluator and the
# UI to label them as read-only).
UD_OUTPUT_KEYS = (
    UD_OUT_GAMMA,
    UD_OUT_CONTRACTION,
    UD_OUT_DOPPLER_FWD,
    UD_OUT_SEARCHLIGHT,
)

# Human-readable labels shown in the Attribute Manager.
UD_LABELS = {
    UD_BETA_VELOCITY: "Beta Velocity (v/c)",
    UD_SOL_SCALE: "Speed of Light Scale",
    UD_ENABLE_LORENTZ: "Enable Lorentz Geometry",
    UD_ENABLE_DOPPLER: "Enable Doppler Color",
    UD_ENABLE_SEARCHLIGHT: "Enable Searchlight Effect",
    UD_ENABLE_OCTANE_TAG: "Enable Octane Camera Tag",
    UD_EFFECT_STRENGTH: "Effect Strength",
    UD_DEBUG_MODE: "Debug Mode",
    UD_OUT_GAMMA: "Gamma (computed)",
    UD_OUT_CONTRACTION: "Contraction Factor (computed)",
    UD_OUT_DOPPLER_FWD: "Doppler Forward Factor (computed)",
    UD_OUT_SEARCHLIGHT: "Searchlight Multiplier (computed)",
    UD_REST_FOV_RAD: "Rest FOV (rad, internal)",
}

# Default values + ranges for the numeric user-data fields.
# (min, max, default) -- only used for REAL/float parameters.
UD_RANGES = {
    UD_BETA_VELOCITY: (0.0, 0.999, 0.0),
    UD_SOL_SCALE: (0.0001, 1000.0, 1.0),
    UD_EFFECT_STRENGTH: (0.0, 2.0, 1.0),
}

# Generous display ranges for the read-only numeric outputs. The slider
# range is just for visualization in the Attribute Manager; the evaluator
# never writes values outside the physically-motivated bounds.
UD_OUTPUT_RANGES = {
    UD_OUT_GAMMA: (1.0, 1000.0, 1.0),
    UD_OUT_CONTRACTION: (0.0, 1.0, 1.0),
    UD_OUT_DOPPLER_FWD: (0.0, 1000.0, 1.0),
    UD_OUT_SEARCHLIGHT: (0.0, 1.0e9, 1.0),
    UD_REST_FOV_RAD: (0.0, 6.283185307, 0.0),
}

# Default values for the bool fields.
UD_BOOL_DEFAULTS = {
    UD_ENABLE_LORENTZ: True,
    UD_ENABLE_DOPPLER: True,
    UD_ENABLE_SEARCHLIGHT: True,
    UD_ENABLE_OCTANE_TAG: False,
    UD_DEBUG_MODE: False,
}

# Ordered list driving the order of fields in the Attribute Manager.
UD_ORDER = [
    UD_BETA_VELOCITY,
    UD_SOL_SCALE,
    UD_EFFECT_STRENGTH,
    UD_ENABLE_LORENTZ,
    UD_ENABLE_DOPPLER,
    UD_ENABLE_SEARCHLIGHT,
    UD_ENABLE_OCTANE_TAG,
    UD_DEBUG_MODE,
    # Computed (read-only) outputs follow.
    UD_OUT_GAMMA,
    UD_OUT_CONTRACTION,
    UD_OUT_DOPPLER_FWD,
    UD_OUT_SEARCHLIGHT,
    # Internal cache -- last so it's least visible.
    UD_REST_FOV_RAD,
]

# ---------------------------------------------------------------------------
# FOV / motion-blur tuning constants
# ---------------------------------------------------------------------------
# Linear coefficients applied to ``beta * effect_strength`` when deriving
# the live camera FOV and the motion-blur multiplier. Tuned for "feels
# right at beta ~ 0.9", not for spectral accuracy. Adjust here, not in
# the evaluator, so the math stays grouped with the rest of the constants.
FOV_BETA_COEFF = 0.5          # FOV multiplier = 1 + FOV_BETA_COEFF * beta * strength
MOTION_BLUR_BETA_COEFF = 1.0  # blur multiplier = 1 + MOTION_BLUR_BETA_COEFF * beta * strength

