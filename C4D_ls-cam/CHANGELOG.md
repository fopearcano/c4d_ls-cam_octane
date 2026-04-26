# Changelog

All notable changes to **C4D_ls-cam** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Camera-level relativistic effects in `ls_evaluator`:
  - **FOV mode enum** (`fov_mode`: Subtle / Extreme / Scientific-ish)
    with `fov_strength`. Subtle and Extreme are linear widenings;
    Scientific-ish uses the physically-motivated `sqrt((1-β)/(1+β))`
    forward narrowing applied as a uniform FOV multiplier (artistic
    approximation -- the real aberration skews angles differently).
  - **Relativistic DoF** (`enable_relativistic_dof`, `dof_strength`).
    Drives Octane `aperture` / `depth_of_field` slots when they are
    mapped in `ls_octane_params`; otherwise scales the C4D camera's
    `CAMERAOBJECT_APERTURE` from its rest baseline.
  - **Relativistic exposure** (`enable_relativistic_exposure`,
    `exposure_strength`). When Octane imager slots are mapped, scales
    `imager_exposure`, drops `imager_saturation`, and boosts
    `postfx_bloom_glare` from per-slot baselines. With no Octane
    mapping the multiplier is computed but not written (the C4D
    standard camera has no unified exposure field).
  - **Color-perception output** `doppler_temperature_shift` (Kelvin
    delta from a 6500 K rest temperature, positive = bluer). Materials
    are NOT modified at this stage per the spec.
- `reset_ls_camera_rig(doc, controller, camera)`: restores camera FOV
  / focus distance / aperture from the captured baselines, restores
  every mapped Octane parameter from its per-slot
  `_baseline_octane_<slot>` field on the controller, and clears the
  computed-output user-data fields back to their identity values.
  Idempotent and tolerant of missing baselines.
- Per-Octane-slot baselines are captured lazily on first write into
  hidden-style `_baseline_octane_<slot>` user-data fields on the
  controller, persisted with the scene file so reset works after
  reopen.
- C4D camera baselines (`_rest_focus_dist`, `_rest_aperture`)
  captured at rig creation alongside the existing `_rest_fov_rad`.
- `ls_octane_params.py`: new module with a symbolic slot table
  (`OCTANE_CAMERA_PARAMS`) covering depth-of-field, aperture, motion
  blur, imager exposure, imager saturation, and post-processing
  bloom/glare. Every slot ships with `param_id: None` -- the integrator
  fills them in after running the dump helper. Includes
  `is_param_mapped`, `get_param_id`, `unmapped_keys` helpers.
- `ls_octane.find_octane_camera_tag_id(force_refresh=False)`: searches
  registered tag plugins for one whose name contains both `octane` and
  `camera`. Result is cached at module level.
- `ls_octane.find_existing_octane_tag(camera)`: returns an Octane Camera
  Tag already on the camera (so attachment never duplicates).
- `ls_octane.dump_octane_tag_parameters(tag)` and
  `ls_octane.dump_octane_tag_on_camera(camera)`: print every Octane
  camera-tag parameter as `DescID : name = value`, plus a list of
  symbolic slots in `ls_octane_params` that still need mapping.
- README "How to map Octane parameter IDs" section walking through the
  dump-and-paste workflow.

### Changed
- `ls_octane.add_octane_camera_tag` now takes a
  `show_dialog_on_failure` flag (default False). When True and
  attachment fails, surfaces the fixed dialog *"Octane Camera Tag not
  found. Add it manually, then rerun Update LS Camera Rig."*. Returns
  the attached / pre-existing `BaseTag` instead of a bool. The rig
  builder calls it silently so creating a rig in a non-Octane scene is
  not intrusive.

### Added
- `ls_evaluator.py`: new module with `update_ls_camera_rig(doc, controller,
  camera)`. Reads the controller's user data, computes
  `gamma`, `contraction_factor`, `doppler_forward_factor`, and
  `searchlight_multiplier`, writes them to read-only-by-convention
  output fields on the controller, and adjusts the camera's FOV from a
  cached rest-FOV baseline. Motion-blur multiplier is computed but not
  yet applied to any render setting (engine-agnostic placeholder).
- Read-only output user-data fields on the controller: `gamma`,
  `contraction_factor`, `doppler_forward_factor`,
  `searchlight_multiplier`. Plus an internal `_rest_fov_rad` cache so FOV
  changes stay non-destructive.
- The controller's Python tag is no longer a no-op: its `main()` now
  finds the camera under the rig null and forwards to
  `ls_evaluator.update_ls_camera_rig`.
- Debug print (gated on `debug_mode`) showing beta, strength, gamma,
  contraction, doppler factor, searchlight, FOV multiplier, and
  motion-blur multiplier.

### Changed
- `ls_rig.py` now also captures the camera's rest FOV onto the controller
  at rig creation, and embeds the new evaluator-shim source as the
  Python tag body.

- `ls_relativity_math.py`: pure-Python helpers (no C4D dependency) for
  special-relativistic visual effects -- `clamp_beta`, `gamma_from_beta`,
  `lorentz_contraction_factor`, `doppler_factor`,
  `relativistic_aberration_cos`, `searchlight_intensity_factor`, and
  `wavelength_shift_rgb_approx`. Includes a `__main__` self-test block
  runnable outside Cinema 4D.
- Initial plugin skeleton for Cinema 4D 2025+ Python SDK.
- `CommandData` plugin **Create LS Relativistic Camera Rig** registered
  under the Extensions menu.
- Rig builder (`ls_rig.build_rig`) that creates:
  - `LS_Camera_Rig` (Null controller)
  - `LS_Relativistic_Camera` (standard C4D Camera, parented under the null)
  - `LS_Relativity_Controller` (Python Tag attached to the null)
- User-data parameters on the controller tag:
  `beta_velocity`, `speed_of_light_scale`, `effect_strength`,
  `enable_lorentz_geometry`, `enable_doppler_color`,
  `enable_searchlight_effect`, `enable_octane_camera_tag`, `debug_mode`.
- Single-step undo wrapping the entire rig creation.
- Octane integration placeholder (`ls_octane.add_octane_camera_tag`) with
  a documented procedure for inserting a verified Octane Camera Tag ID.
- README with installation instructions and module layout.

### Known limitations
- Geometry deformation (Lorentz contraction applied to scene meshes)
  is still not implemented.
- Material / shader updates (Doppler color shift on assets) are not
  implemented; only the global `doppler_temperature_shift` output is
  exposed.
- Exposure path needs Octane parameter mapping to actually drive
  anything -- with no mapping the multiplier is computed only.
- Motion-blur multiplier is computed but not written to any render
  setting; the value is exposed in the debug log only.
- All three FOV modes apply a single uniform multiplier; even
  "Scientific-ish" is not a true raytraced aberration pass.
- `PLUGIN_ID` is a development-only placeholder and must be replaced with
  a Maxon-registered ID before public distribution.
- `OCTANE_CAMERA_TAG_ID` is `None` by default; the plugin auto-discovers
  the Octane Camera Tag by plugin-name search. Override the constant
  only if discovery picks the wrong plugin.
- All slots in `ls_octane_params.OCTANE_CAMERA_PARAMS` start with
  `param_id: None`; downstream code skips unmapped slots until the
  integrator runs `dump_octane_tag_parameters` and pastes the IDs.
- No custom icon shipped yet (`icon=None` in registration).
