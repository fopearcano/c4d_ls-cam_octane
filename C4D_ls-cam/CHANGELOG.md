# Changelog

All notable changes to **C4D_ls-cam** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- Geometry deformation (Lorentz contraction applied to scene meshes) is
  not implemented yet -- the FOV update is the only camera-side effect
  currently driven by `beta_velocity`.
- Material / shader updates (Doppler color shift) are not implemented yet.
- Motion-blur multiplier is computed but not written to any render
  setting; the value is exposed in the debug log only.
- `PLUGIN_ID` is a development-only placeholder and must be replaced with
  a Maxon-registered ID before public distribution.
- `OCTANE_CAMERA_TAG_ID` is `None`; Octane tag attachment is intentionally
  skipped until the integrator confirms the correct ID.
- No custom icon shipped yet (`icon=None` in registration).
