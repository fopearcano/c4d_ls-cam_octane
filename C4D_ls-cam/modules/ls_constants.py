"""
ls_constants.py
---------------
Centralized constants for the C4D_ls-cam plugin.

Keeping IDs, names, and parameter keys in one place avoids drift between the
rig builder, the UI layer, and the Octane integration helpers.
"""

# ---------------------------------------------------------------------------
# Distribution metadata
# ---------------------------------------------------------------------------

# Semantic version. ``alpha`` suffix signals the API + scene-graph
# layout may still change between drops. Bump in lockstep with
# CHANGELOG entries.
__version__ = "0.1.0-alpha"
PLUGIN_VERSION = __version__

# One-line description used in the registration logs and in the
# Help/About text Cinema 4D shows for the menu items.
PLUGIN_DESCRIPTION = (
    "Special-relativistic camera rig for Cinema 4D 2025+: gamma + "
    "Lorentz contraction, FOV / DoF / exposure modes, Doppler "
    "material colour shift, searchlight beaming, geometry proxy, "
    "Octane camera-tag integration, A Slower Speed of Light "
    "presets, and an artistic Terrell-rotation placeholder."
)

# ---------------------------------------------------------------------------
# Plugin identity
# ---------------------------------------------------------------------------

# NOTE: Cinema 4D plugin IDs MUST be registered with Maxon at
# https://plugincafe.maxon.net/c4dpluginid_cp before public distribution.
# The value below is a development-only placeholder in the user-id range
# (1000001 - 1000010) reserved by Maxon for in-house testing. Replace it
# with a registered ID before shipping the plugin.
PLUGIN_ID = 1000001
PLUGIN_ID_GEOM_PROXY_ADD = 1000002
PLUGIN_ID_GEOM_PROXY_REMOVE = 1000003
PLUGIN_ID_DOPPLER_MAT_ADD = 1000004
PLUGIN_ID_DOPPLER_MAT_RESTORE = 1000005
PLUGIN_ID_PRESETS = 1000006
PLUGIN_ID_DIAG_TOGGLE = 1000007
PLUGIN_ID_RESTORE_CAMERA = 1000008
PLUGIN_ID_REMOVE_RIG = 1000009

PLUGIN_NAME = "C4D_ls-cam"
COMMAND_NAME = "Create LS Relativistic Camera Rig"
COMMAND_HELP = "Builds a relativistic camera rig (camera + null + controller tag)."

GEOM_PROXY_ADD_NAME = "LS Cam: Add Relativistic Geometry Proxy"
GEOM_PROXY_ADD_HELP = "Wraps selected (or all) scene objects in a contractable proxy null."
GEOM_PROXY_REMOVE_NAME = "LS Cam: Remove Relativistic Geometry Proxy"
GEOM_PROXY_REMOVE_HELP = "Unwraps the LS_Geometry_Proxy and restores object world transforms."

DOPPLER_MAT_ADD_NAME = "LS Cam: Add Doppler Material Controller"
DOPPLER_MAT_ADD_HELP = "Duplicates affected materials as LS_Doppler_<name> for relativistic colour shifting."
DOPPLER_MAT_RESTORE_NAME = "LS Cam: Restore Original Materials"
DOPPLER_MAT_RESTORE_HELP = "Reassigns texture tags to the originals and deletes LS_Doppler_* duplicates."

PRESETS_NAME = "LS Cam: Apply Relativity Preset"
PRESETS_HELP = "Opens a dialog to apply curated beta/strength presets to the controller."

RESTORE_CAMERA_NAME = "LS Cam: Restore Camera Defaults"
RESTORE_CAMERA_HELP = "Snaps the camera + outputs back to baseline (FOV, focus, aperture, displays, materials, proxy, Terrell)."

REMOVE_RIG_NAME = "LS Cam: Remove LS Camera Rig"
REMOVE_RIG_HELP = "Resets the camera state then deletes the LS_Camera_Rig hierarchy. Geometry-proxy and Doppler-material clones are left in place."

DIAG_TOGGLE_NAME = "LS Cam: Toggle Diagnostic Overlay"
DIAG_TOGGLE_HELP = "Adds or removes a HUD-style overlay near the camera that shows live beta/gamma/contraction/Doppler/searchlight values."

# Prefix used for every duplicated material; also acts as the recognition
# token in restore_original_materials() so we never delete a material the
# user happened to name "LS_Doppler_<x>" by hand (we additionally check
# for the marker BC slot below).
DOPPLER_MATERIAL_PREFIX = "LS_Doppler_"

# ---------------------------------------------------------------------------
# Object names used in the C4D scene
# ---------------------------------------------------------------------------

CAMERA_NAME = "LS_Relativistic_Camera"
RIG_NULL_NAME = "LS_Camera_Rig"
CONTROLLER_TAG_NAME = "LS_Relativity_Controller"
GEOMETRY_PROXY_NAME = "LS_Geometry_Proxy"
DIAGNOSTIC_OVERLAY_NAME = "LS_Diagnostic_Overlay"

# ---------------------------------------------------------------------------
# User-data parameter keys
# ---------------------------------------------------------------------------
# These string keys are the source of truth for the user-data layout. The
# rig builder uses them as labels and the UI / future relativistic math
# modules can look up the corresponding DescID from a dict on the tag.

UD_BETA_VELOCITY = "beta_velocity"
UD_SOL_SCALE = "speed_of_light_scale"
UD_EFFECT_STRENGTH = "effect_strength"

# FOV controls (added in the camera-effects pass).
UD_FOV_MODE = "fov_mode"
UD_FOV_STRENGTH = "fov_strength"

# Per-effect toggles + per-effect strengths.
UD_ENABLE_LORENTZ = "enable_lorentz_geometry"
UD_ENABLE_DOPPLER = "enable_doppler_color"
UD_ENABLE_SEARCHLIGHT = "enable_searchlight_effect"
UD_ENABLE_DOF = "enable_relativistic_dof"
UD_ENABLE_EXPOSURE = "enable_relativistic_exposure"
UD_ENABLE_OCTANE_TAG = "enable_octane_camera_tag"
UD_DOF_STRENGTH = "dof_strength"
UD_EXPOSURE_STRENGTH = "exposure_strength"

UD_DEBUG_MODE = "debug_mode"

# ---- Geometry proxy controls ----------------------------------------------
UD_GEOMETRY_MODE = "geometry_mode"
UD_VELOCITY_AXIS_SOURCE = "velocity_axis_source"
UD_CONTRACTION_STRENGTH = "contraction_strength"
UD_AFFECT_SELECTED_ONLY = "affect_selected_only"
UD_VELOCITY_CUSTOM_VECTOR = "velocity_custom_vector"

# ---- Doppler material controls --------------------------------------------
# Per-material RGB shift strength. Multiplied into the wavelength-shift
# alpha by ls_materials.apply_doppler_color_shift; 0 freezes the
# duplicates at their baseline colour (matches the "effect off" path
# the evaluator already runs when enable_doppler_color is False).
UD_DOPPLER_COLOR_STRENGTH = "doppler_color_strength"

# ---- Searchlight controls -------------------------------------------------
# enable_searchlight_effect already exists above as the master toggle;
# these three add the per-effect knobs requested by the brief.
UD_SEARCHLIGHT_STRENGTH = "searchlight_strength"
UD_SEARCHLIGHT_MODE = "searchlight_mode"
UD_MAX_INTENSITY_MULTIPLIER = "max_intensity_multiplier"

# ---- Diagnostics ----------------------------------------------------------
# Bool master switch for the cos-theta heatmap that overrides
# LS_Doppler_<x> material colours with a debug palette. Off by default
# so the production render path is untouched until the user opts in.
UD_DEBUG_MATERIAL_PREVIEW = "debug_material_preview"

# ---- Advanced (Terrell placeholder + ray-level future work) --------------
# Important: this is NOT a true Terrell-Penrose rotation. Real Terrell
# requires per-ray retarded-time sampling that has to live at the
# render-engine / shader level. The placeholder here applies a small
# heading-axis rotation to the LS_Geometry_Proxy null so artists have
# *something* visible to dial when they're prototyping shots, while
# keeping the production-relevant approximations cleanly separated.
UD_ENABLE_TERRELL_PLACEHOLDER = "enable_terrell_placeholder"
UD_TERRELL_STRENGTH = "terrell_strength"
UD_RAY_LEVEL_WARNING = "ray_level_warning"

# Default text written into the UD_RAY_LEVEL_WARNING string field on rig
# creation. Treated as read-only by convention -- it's a STRING UD field
# so a user *could* edit it, but the rig never re-reads it.
TERRELL_WARNING_TEXT = (
    "This is an artistic approximation. True Terrell rotation requires "
    "ray-level rendering or custom shader/camera implementation."
)

# ---- Computed (read-only) outputs --------------------------------------------
# These fields are written by ls_evaluator.update_ls_camera_rig() every time
# the controller is evaluated. They are exposed as user-data so artists can
# see the effective values in the Attribute Manager, but they are
# overwritten on every evaluation -- treat them as read-only.
UD_OUT_GAMMA = "gamma"
UD_OUT_CONTRACTION = "contraction_factor"
UD_OUT_DOPPLER_FWD = "doppler_forward_factor"
UD_OUT_SEARCHLIGHT = "searchlight_multiplier"
# Doppler-driven color-temperature shift in Kelvin (delta from rest temp).
# Positive = bluer (approach), negative = redder (recession).
UD_OUT_DOPPLER_TEMP_SHIFT = "doppler_temperature_shift"

# ---- Internal caches --------------------------------------------------------
# Original camera state captured at rig creation. Every camera-side
# effect derives its live value from these baselines, so toggling an
# effect off (or calling reset_ls_camera_rig) restores the camera to
# exactly its initial state.
UD_REST_FOV_RAD = "_rest_fov_rad"
UD_REST_FOCUS_DIST = "_rest_focus_dist"
UD_REST_APERTURE = "_rest_aperture"

# Set of UD keys that are computed outputs (used by the evaluator and the
# UI to label them as read-only).
UD_OUTPUT_KEYS = (
    UD_OUT_GAMMA,
    UD_OUT_CONTRACTION,
    UD_OUT_DOPPLER_FWD,
    UD_OUT_SEARCHLIGHT,
    UD_OUT_DOPPLER_TEMP_SHIFT,
)

# ---- Geometry mode enum ---------------------------------------------------
# Only PROXY_SCALE is implemented in this pass. POINT_DEFORM is reserved
# so the dropdown order matches the project brief; selecting it currently
# falls through to a no-op with a TODO marker.
GEOM_MODE_OFF = 0
GEOM_MODE_PROXY_SCALE = 1
GEOM_MODE_POINT_DEFORM = 2
GEOM_MODE_ITEMS = ("Off", "Proxy Scale", "Point Deform Approx")

# ---- Searchlight mode enum ------------------------------------------------
# Modes determine WHERE the per-object intensity factor is written:
#   VIEWPORT   -- ID_BASEOBJECT_USECOLOR + ID_BASEOBJECT_COLOR (cheap,
#                 always available, only visible in the viewport).
#   LUMINANCE  -- MATERIAL_USE_LUMINANCE + MATERIAL_LUMINANCE_COLOR on
#                 the LS_Doppler_<x> material clones (renders, but only
#                 affects the materials that have already been wrapped).
#   OCTANE     -- placeholder for future Octane node-material emission
#                 driving; currently a one-shot logged no-op.
SEARCHLIGHT_MODE_VIEWPORT = 0
SEARCHLIGHT_MODE_LUMINANCE = 1
SEARCHLIGHT_MODE_OCTANE = 2
SEARCHLIGHT_MODE_ITEMS = (
    "Viewport Only",
    "Material Luminance",
    "Octane Material Placeholder",
)

# ---- Velocity axis source enum --------------------------------------------
AXIS_SOURCE_CAMERA_FORWARD = 0
AXIS_SOURCE_WORLD_Z = 1
AXIS_SOURCE_CUSTOM = 2
AXIS_SOURCE_ITEMS = ("Camera Forward", "World Z", "Custom Vector")

# ---- FOV mode enum ---------------------------------------------------------
# fov_mode is a CYCLE / DTYPE_LONG user-data field; the integer value
# stored in the field maps to one of these mode constants.
FOV_MODE_SUBTLE = 0
FOV_MODE_EXTREME = 1
FOV_MODE_SCIENTIFIC = 2

# Items shown in the cycle dropdown, indexed by the mode constants above.
FOV_MODE_ITEMS = ("Subtle", "Extreme", "Scientific-ish")

# Coefficients for the "Subtle" and "Extreme" artistic modes; the
# "Scientific-ish" mode uses sqrt((1-beta)/(1+beta)) directly and is not
# parameterised here. Tunable in one place if the art direction shifts.
FOV_MODE_SUBTLE_COEFF = 0.3   # FOV mult = 1 + COEFF * beta * fov_strength
FOV_MODE_EXTREME_COEFF = 1.5

# ---- Doppler color temperature ---------------------------------------------
# A blackbody peak shifts as T_obs = T_emit * D (Wien's law inverted).
# We need a reference rest temperature to express the shift as a delta.
# 6500 K matches the "neutral daylight" white point used in most colour
# pipelines and gives intuitive numbers (positive = bluer, negative =
# redder). Pure artistic choice -- spectral renderers should ignore.
COLOR_TEMP_REST_K = 6500.0

# Human-readable labels shown in the Attribute Manager.
UD_LABELS = {
    UD_BETA_VELOCITY: "Beta Velocity (v/c)",
    UD_SOL_SCALE: "Speed of Light Scale",
    UD_EFFECT_STRENGTH: "Effect Strength",
    UD_FOV_MODE: "FOV Mode",
    UD_FOV_STRENGTH: "FOV Strength",
    UD_ENABLE_LORENTZ: "Enable Lorentz Geometry",
    UD_ENABLE_DOPPLER: "Enable Doppler Color",
    UD_ENABLE_SEARCHLIGHT: "Enable Searchlight Effect",
    UD_ENABLE_DOF: "Enable Relativistic DoF",
    UD_ENABLE_EXPOSURE: "Enable Relativistic Exposure",
    UD_ENABLE_OCTANE_TAG: "Enable Octane Camera Tag",
    UD_DOF_STRENGTH: "DoF Strength",
    UD_EXPOSURE_STRENGTH: "Exposure Strength",
    UD_DEBUG_MODE: "Debug Mode",
    UD_GEOMETRY_MODE: "Geometry Mode",
    UD_VELOCITY_AXIS_SOURCE: "Velocity Axis Source",
    UD_CONTRACTION_STRENGTH: "Contraction Strength",
    UD_AFFECT_SELECTED_ONLY: "Affect Selected Only",
    UD_VELOCITY_CUSTOM_VECTOR: "Velocity Custom Vector",
    UD_DOPPLER_COLOR_STRENGTH: "Doppler Color Strength",
    UD_SEARCHLIGHT_STRENGTH: "Searchlight Strength",
    UD_SEARCHLIGHT_MODE: "Searchlight Mode",
    UD_MAX_INTENSITY_MULTIPLIER: "Max Intensity Multiplier",
    UD_DEBUG_MATERIAL_PREVIEW: "Debug Material Preview",
    UD_ENABLE_TERRELL_PLACEHOLDER: "Advanced: Enable Terrell Placeholder",
    UD_TERRELL_STRENGTH: "Advanced: Terrell Strength",
    UD_RAY_LEVEL_WARNING: "Advanced: Ray-Level Note (read-only)",
    UD_OUT_GAMMA: "Gamma (computed)",
    UD_OUT_CONTRACTION: "Contraction Factor (computed)",
    UD_OUT_DOPPLER_FWD: "Doppler Forward Factor (computed)",
    UD_OUT_SEARCHLIGHT: "Searchlight Multiplier (computed)",
    UD_OUT_DOPPLER_TEMP_SHIFT: "Doppler Temperature Shift K (computed)",
    UD_REST_FOV_RAD: "Rest FOV rad (internal)",
    UD_REST_FOCUS_DIST: "Rest Focus Distance (internal)",
    UD_REST_APERTURE: "Rest Aperture (internal)",
}

# Default values + ranges for the numeric user-data fields.
# (min, max, default) -- only used for REAL/float parameters.
UD_RANGES = {
    UD_BETA_VELOCITY: (0.0, 0.999, 0.0),
    UD_SOL_SCALE: (0.0001, 1000.0, 1.0),
    UD_EFFECT_STRENGTH: (0.0, 2.0, 1.0),
    UD_FOV_STRENGTH: (0.0, 2.0, 1.0),
    UD_DOF_STRENGTH: (0.0, 2.0, 1.0),
    UD_EXPOSURE_STRENGTH: (0.0, 2.0, 1.0),
    UD_CONTRACTION_STRENGTH: (0.0, 2.0, 1.0),
    UD_DOPPLER_COLOR_STRENGTH: (0.0, 2.0, 1.0),
    UD_SEARCHLIGHT_STRENGTH: (0.0, 2.0, 1.0),
    UD_MAX_INTENSITY_MULTIPLIER: (1.0, 1000.0, 10.0),
    UD_TERRELL_STRENGTH: (0.0, 2.0, 1.0),
}

# String user-data fields. The default string is also written as the
# field's value at rig creation; rigs never re-read these (treated as
# read-only).
UD_STRINGS = {
    UD_RAY_LEVEL_WARNING: TERRELL_WARNING_TEXT,
}

# Enum (cycle) fields. ``items`` is the ordered list of dropdown entries;
# the integer stored in the field is the selected index.
UD_ENUMS = {
    UD_FOV_MODE: {
        "items": FOV_MODE_ITEMS,
        "default": FOV_MODE_SUBTLE,
    },
    UD_GEOMETRY_MODE: {
        "items": GEOM_MODE_ITEMS,
        "default": GEOM_MODE_OFF,
    },
    UD_VELOCITY_AXIS_SOURCE: {
        "items": AXIS_SOURCE_ITEMS,
        "default": AXIS_SOURCE_CAMERA_FORWARD,
    },
    UD_SEARCHLIGHT_MODE: {
        "items": SEARCHLIGHT_MODE_ITEMS,
        "default": SEARCHLIGHT_MODE_VIEWPORT,
    },
}

# Vector user-data fields (DTYPE_VECTOR). Tuple is (default_xyz,).
UD_VECTORS = {
    UD_VELOCITY_CUSTOM_VECTOR: ((0.0, 0.0, 1.0),),
}

# Generous display ranges for the read-only numeric outputs. The slider
# range is just for visualization in the Attribute Manager; the evaluator
# never writes values outside the physically-motivated bounds.
UD_OUTPUT_RANGES = {
    UD_OUT_GAMMA: (1.0, 1000.0, 1.0),
    UD_OUT_CONTRACTION: (0.0, 1.0, 1.0),
    UD_OUT_DOPPLER_FWD: (0.0, 1000.0, 1.0),
    UD_OUT_SEARCHLIGHT: (0.0, 1.0e9, 1.0),
    UD_OUT_DOPPLER_TEMP_SHIFT: (-50000.0, 50000.0, 0.0),
    UD_REST_FOV_RAD: (0.0, 6.283185307, 0.0),
    UD_REST_FOCUS_DIST: (0.0, 1.0e9, 0.0),
    UD_REST_APERTURE: (0.0, 1.0e6, 0.0),
}

# Default values for the bool fields.
UD_BOOL_DEFAULTS = {
    UD_ENABLE_LORENTZ: True,
    UD_ENABLE_DOPPLER: True,
    UD_ENABLE_SEARCHLIGHT: True,
    UD_ENABLE_DOF: False,
    UD_ENABLE_EXPOSURE: False,
    UD_ENABLE_OCTANE_TAG: False,
    UD_DEBUG_MODE: False,
    UD_AFFECT_SELECTED_ONLY: True,
    UD_DEBUG_MATERIAL_PREVIEW: False,
    UD_ENABLE_TERRELL_PLACEHOLDER: False,
}

# Ordered list driving the order of fields in the Attribute Manager.
UD_ORDER = [
    # Inputs.
    UD_BETA_VELOCITY,
    UD_SOL_SCALE,
    UD_EFFECT_STRENGTH,
    UD_FOV_MODE,
    UD_FOV_STRENGTH,
    UD_DOF_STRENGTH,
    UD_EXPOSURE_STRENGTH,
    # Effect toggles.
    UD_ENABLE_LORENTZ,
    UD_ENABLE_DOPPLER,
    UD_ENABLE_SEARCHLIGHT,
    UD_ENABLE_DOF,
    UD_ENABLE_EXPOSURE,
    UD_ENABLE_OCTANE_TAG,
    UD_DEBUG_MODE,
    # Geometry proxy controls.
    UD_GEOMETRY_MODE,
    UD_VELOCITY_AXIS_SOURCE,
    UD_CONTRACTION_STRENGTH,
    UD_AFFECT_SELECTED_ONLY,
    UD_VELOCITY_CUSTOM_VECTOR,
    # Doppler material controls.
    UD_DOPPLER_COLOR_STRENGTH,
    # Searchlight controls.
    UD_SEARCHLIGHT_STRENGTH,
    UD_SEARCHLIGHT_MODE,
    UD_MAX_INTENSITY_MULTIPLIER,
    # Diagnostics.
    UD_DEBUG_MATERIAL_PREVIEW,
    # Advanced (Terrell placeholder + ray-level future work).
    UD_ENABLE_TERRELL_PLACEHOLDER,
    UD_TERRELL_STRENGTH,
    UD_RAY_LEVEL_WARNING,
    # Computed (read-only) outputs.
    UD_OUT_GAMMA,
    UD_OUT_CONTRACTION,
    UD_OUT_DOPPLER_FWD,
    UD_OUT_SEARCHLIGHT,
    UD_OUT_DOPPLER_TEMP_SHIFT,
    # Internal caches -- last so they're least visible in the AM.
    UD_REST_FOV_RAD,
    UD_REST_FOCUS_DIST,
    UD_REST_APERTURE,
]

# ---------------------------------------------------------------------------
# FOV / motion-blur tuning constants
# ---------------------------------------------------------------------------
# Linear coefficients applied to ``beta * effect_strength`` when deriving
# the live camera FOV and the motion-blur multiplier. Tuned for "feels
# right at beta ~ 0.9", not for spectral accuracy. Adjust here, not in
# the evaluator, so the math stays grouped with the rest of the constants.
FOV_BETA_COEFF = 0.5          # legacy fallback when fov_mode field is missing
MOTION_BLUR_BETA_COEFF = 1.0  # blur multiplier = 1 + MOTION_BLUR_BETA_COEFF * beta * strength

# DoF tuning (artistic). C4D camera path multiplies the rest aperture by
# (1 + DOF_BETA_COEFF * beta * dof_strength). Octane path multiplies its
# baseline aperture similarly. Wider aperture -> shallower DoF, which
# reads as "subjective time slowing on the focal plane" at high speed.
DOF_BETA_COEFF = 1.0

# Exposure tuning (artistic). When the relativistic exposure flag is on,
# we scale the imager exposure by D^(EXPOSURE_BETA_EXPONENT * strength)
# where D is the forward Doppler factor. The exponent governs how
# aggressively forward beaming brightens the image.
EXPOSURE_BETA_EXPONENT = 4.0

