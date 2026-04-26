# Changelog

All notable changes to **C4D_ls-cam** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Searchlight (relativistic beaming) per-target driver** in
  `ls_searchlight.py`:
  - `apply_searchlight(doc, controller, camera, beta, strength,
    mode, max_intensity, debug)`: dispatches by mode.
  - **Viewport Only** mode writes `ID_BASEOBJECT_USECOLOR` (=2) and
    a baseline-tinted `ID_BASEOBJECT_COLOR` per controlled object;
    output is per-channel-clamped to `[0, 1]` so out-of-gamut values
    never reach the viewport.
  - **Material Luminance** mode enables
    `MATERIAL_USE_LUMINANCE` and writes `MATERIAL_LUMINANCE_COLOR`
    on every `LS_Doppler_<x>` classic-material clone; glow tints
    from the clone's live colour so the emission tracks the
    Doppler shift. `cos_theta` is per-material via the centroid of
    its user objects.
  - **Octane Material Placeholder** mode is a one-shot logged
    no-op; node-material emission needs per-Octane-version mapping
    (TODO in `ls_searchlight.py`).
  - `restore_searchlight(doc)`: walks every stamped object +
    material, writes the saved baseline back, clears the marker.
  - "Controlled object" = geometry-proxy children ∪ objects whose
    texture tags reference an `LS_Doppler_<x>` clone. The
    searchlight is a no-op if neither system has been used.
  - Switching modes auto-restores the previous mode's baselines.
- New controller user-data fields: `searchlight_strength` (float
  0..2, default 1), `searchlight_mode` (enum), and
  `max_intensity_multiplier` (float 1..1000, default 10) acting as
  the absolute clamp ceiling on the per-target factor.

### Changed
- `ls_evaluator.update_ls_camera_rig`:
  - Reads the three new searchlight UD fields and calls
    `ls_searchlight.apply_searchlight` when
    `enable_searchlight_effect` is on, `restore_searchlight` when
    off. `searchlight_strength * effect_strength` is the compounded
    strength passed to the math helper.
  - `reset_ls_camera_rig` now also calls `restore_searchlight(doc)`.

### Notes
- Live colour writes are still gated to classic `c4d.Mmaterial`
  (Material Luminance mode skips Octane / Redshift / Arnold
  duplicates). Octane node-material emission is on the TODO list.
- The Material Luminance mode's `cos_theta` is per-material (via
  user centroid), not per-object: per-object overrides would
  require per-tag overrides which are out of scope.

### Added
- Non-destructive **Doppler material controller** in
  `ls_doppler_materials.py`:
  - `add_doppler_controller(doc)`: gathers the unique set of materials
    from the Material-Manager selection plus every texture tag on
    selected objects, clones each one as
    `LS_Doppler_<OriginalName>`, captures baseline RGB +
    original-name + original-type into private BaseContainer slots,
    and re-points every texture tag in the document. One undo step.
  - `restore_original_materials(doc)`: re-points every texture tag
    that referenced an `LS_Doppler_*` clone at the original (found by
    stored name) and deletes the clones. Reports any originals it
    can't find by name.
  - `apply_doppler_color_shift(doc, controller, camera, beta,
    strength)`: per-tick colour write driven by
    `RM.doppler_factor(beta, cos_theta)` and
    `RM.wavelength_shift_rgb_approx`. `cos_theta` derives from
    forward · `(centroid_of_users − camera_pos).normalized()`, with
    `forward` resolved through the same `velocity_axis_source` /
    `velocity_custom_vector` controls the geometry pass uses.
  - `restore_baseline_colors(doc)`: snaps duplicates back to
    baseline RGB without unwrapping (used when
    `enable_doppler_color` is False, and from `reset_ls_camera_rig`).
  - `is_doppler_duplicate(mat)`: requires both the name prefix AND
    the private BC marker, so a user-named `LS_Doppler_*` material
    is never deleted.
- New CommandData plugins registered in `c4d_ls_cam.pyp`:
  - **LS Cam: Add Doppler Material Controller** (id `1000004`).
  - **LS Cam: Restore Original Materials** (id `1000005`, greyed
    out when no `LS_Doppler_*` duplicates exist).
- `doppler_color_strength` user-data field (float, 0..2, default 1).
- Public aliases `ls_geometry.camera_forward_vector` and
  `ls_geometry.resolve_velocity_axis` so the doppler module reuses
  the exact axis resolution the geometry pass already uses.

### Notes
- Live colour writes are gated to classic `c4d.Mmaterial` only.
  Octane / Redshift / Arnold node-graph materials are still **cloned**
  (so add/restore work identically), but their per-tick colour write
  is skipped with a one-shot console warning. Per-engine
  node-material support is a TODO documented at the top of
  `ls_doppler_materials.py`.
- Texture / multi-shader chains aren't re-tinted; only the flat
  `MATERIAL_COLOR_COLOR` channel is shifted.
- Original lookup is by name. Renaming the original after
  duplication breaks restore for that material; the restore command
  reports which names it couldn't find.

- Non-destructive **LS_Geometry_Proxy** system in `ls_geometry.py`:
  - `add_geometry_proxy(doc)`: gathers targets (current selection or
    every top-level non-rig object, gated on
    `affect_selected_only`), builds a null whose local Z axis is
    aligned with the resolved velocity direction, and reparents each
    target under it preserving world transforms. Stamps each child
    with an `LS_GeomProxyMember` annotation tag holding the original
    parent's name. Warns (console + dialog) when targets carry
    animated tracks or skin/morph tags.
  - `remove_geometry_proxy(doc)`: re-inserts each child at the
    proxy's parent level (or doc root) with world transforms
    preserved, strips the marker tags, and deletes the proxy null.
  - `apply_proxy_contraction(doc, mode, factor, strength)`: called
    from the evaluator each tick to drive the proxy's local Z scale
    to `1 + (factor - 1) * strength`.
  - Velocity axis math: `_camera_forward(camera)` (uses
    `-camera.GetMg().v3` because C4D cameras look along local -Z),
    `_resolve_velocity_axis(...)`, `_build_axis_aligned_matrix(...)`.
- New CommandData plugins registered in `c4d_ls_cam.pyp`:
  - **LS Cam: Add Relativistic Geometry Proxy** (id `1000002`)
  - **LS Cam: Remove Relativistic Geometry Proxy** (id `1000003`,
    greyed out when no proxy is present).
- Controller user-data fields: `geometry_mode` (Off / Proxy Scale /
  Point Deform Approx), `velocity_axis_source` (Camera Forward /
  World Z / Custom Vector), `contraction_strength` (0..2),
  `affect_selected_only`, and `velocity_custom_vector` (vec3).
- `_add_vector_ud` helper in `ls_rig.py` for `DTYPE_VECTOR` fields,
  plus a `UD_VECTORS` table in `ls_constants.py`.
- `reset_ls_camera_rig` now also snaps any existing proxy back to
  identity scale (without unwrapping it -- removal is the explicit
  command).
- Debug log gains a `geom=<mode>` field.

### Notes
- Only **Proxy Scale** is implemented in this pass. **Point Deform
  Approx** is reserved -- selecting it currently no-ops with a TODO
  comment.
- Terrell-Penrose rotation, retarded-time sampling, and per-vertex
  ray-level visual transforms are explicitly out of scope and flagged
  with TODO comments in `ls_geometry.py`.

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
- Geometry contraction is currently uniform-scale-on-a-parent only
  (the proxy-null approach). Per-vertex deformation, Terrell rotation,
  and ray-level visual transforms are not implemented.
- The proxy's orientation is captured at creation time. Changing
  `velocity_axis_source` or rotating the camera afterwards does not
  re-orient the proxy -- remove and re-add to refresh.
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
