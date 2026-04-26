# C4D_ls-cam

A Cinema 4D 2025+ Python plugin that builds a **Relativistic Camera Rig**
ready for special-relativity (Lorentz contraction, relativistic Doppler,
relativistic aberration / "searchlight effect") experiments and Octane
rendering integration.

> Status: **skeleton**. The rig and all user-data parameters are wired up,
> but the relativistic math is intentionally not implemented yet.

---

## What it creates

When you run **Extensions ▸ Create LS Relativistic Camera Rig**, the plugin
inserts the following into the active document:

```
LS_Camera_Rig                (Null, controller)
└── LS_Relativistic_Camera   (Standard C4D Camera)

Tag on LS_Camera_Rig:
    LS_Relativity_Controller (Python Tag, with user data)
```

### User-data parameters on `LS_Relativity_Controller`

| Parameter                       | Type  | Default | Range            |
|---------------------------------|-------|---------|------------------|
| `beta_velocity`                 | float | 0.0     | 0.0 – 0.999      |
| `speed_of_light_scale`          | float | 1.0     | 0.0001 – 1000    |
| `effect_strength`               | float | 1.0     | 0.0 – 2.0        |
| `fov_mode`                      | enum  | Subtle  | Subtle / Extreme / Scientific-ish |
| `fov_strength`                  | float | 1.0     | 0.0 – 2.0        |
| `dof_strength`                  | float | 1.0     | 0.0 – 2.0        |
| `exposure_strength`             | float | 1.0     | 0.0 – 2.0        |
| `enable_lorentz_geometry`       | bool  | true    | —                |
| `enable_doppler_color`          | bool  | true    | —                |
| `enable_searchlight_effect`     | bool  | true    | —                |
| `enable_relativistic_dof`       | bool  | false   | —                |
| `enable_relativistic_exposure`  | bool  | false   | —                |
| `enable_octane_camera_tag`      | bool  | false   | —                |
| `debug_mode`                    | bool  | false   | —                |
| `debug_material_preview`        | bool  | false   | —                |
| `geometry_mode`                 | enum  | Off     | Off / Proxy Scale / Point Deform Approx |
| `velocity_axis_source`          | enum  | Camera Forward | Camera Forward / World Z / Custom Vector |
| `contraction_strength`          | float | 1.0     | 0.0 – 2.0        |
| `affect_selected_only`          | bool  | true    | —                |
| `velocity_custom_vector`        | vec3  | (0,0,1) | —                |
| `doppler_color_strength`        | float | 1.0     | 0.0 – 2.0        |
| `searchlight_strength`          | float | 1.0     | 0.0 – 2.0        |
| `searchlight_mode`              | enum  | Viewport Only | Viewport Only / Material Luminance / Octane Material Placeholder |
| `max_intensity_multiplier`      | float | 10.0    | 1.0 – 1000.0     |

The whole rig is built in a single undo step — one `Ctrl+Z` removes
everything the command inserted.

### Computed (read-only) outputs

These fields are written by `ls_evaluator.update_ls_camera_rig()` on every
scene evaluation. They are exposed as user-data so artists can read them
in the Attribute Manager, but they are overwritten every tick — treat
them as read-only:

| Output                       | Meaning                                                  |
|------------------------------|----------------------------------------------------------|
| `gamma`                      | Lorentz factor `1 / sqrt(1 - β²)`                        |
| `contraction_factor`         | `sqrt(1 - β²)` (length contraction along motion axis)    |
| `doppler_forward_factor`     | Doppler `D` for a head-on line of sight                  |
| `searchlight_multiplier`     | Relativistic-beaming intensity multiplier (`D^4·strength`) |
| `doppler_temperature_shift`  | Δ Kelvin from 6500 K rest temp (positive = bluer; artistic, no material edits) |

### Camera behavior

All camera-side effects are **artistic approximations** unless flagged
otherwise. Every driven value is reversible: the rig captures the
camera's rest FOV / focus distance / aperture at creation time, and
`reset_ls_camera_rig(doc, controller, camera)` restores them exactly.

* **FOV (`enable_lorentz_geometry`).** Multiplier applied to the rest
  FOV depends on `fov_mode`:

  | Mode             | Formula                                                                                      |
  |------------------|----------------------------------------------------------------------------------------------|
  | Subtle           | `1 + 0.3 · β · fov_strength`                                                                 |
  | Extreme          | `1 + 1.5 · β · fov_strength`                                                                 |
  | Scientific-ish   | `1 + (sqrt((1-β)/(1+β)) - 1) · fov_strength` — physically-motivated forward narrowing        |

  All three modes apply a uniform FOV multiplier; the real
  aberration formula skews different angles differently, so even
  "Scientific-ish" is a preview, not a true raytraced aberration pass.
* **Depth of field (`enable_relativistic_dof`).** If an Octane Camera
  Tag is present and the `aperture` / `depth_of_field` slots in
  `ls_octane_params` are mapped, those are driven from a per-slot
  baseline captured on first touch. Otherwise the C4D camera's
  `CAMERAOBJECT_APERTURE` is scaled from its rest baseline by
  `1 + 1.0 · β · dof_strength`. Wider aperture reads as a shallower
  focal plane — pure look choice, not a real relativistic effect.
* **Exposure / searchlight (`enable_relativistic_exposure`).** Imager
  exposure is scaled by `D^(4·exposure_strength)` from baseline when
  the Octane `imager_exposure` slot is mapped. Imager saturation is
  reduced and post-FX bloom/glare is increased for added beam-y
  glow. If Octane mapping is unavailable, the multiplier is computed
  but not written anywhere — the C4D standard camera has no unified
  exposure field, so we'd be poking renderer-specific knobs that are
  out of scope for this pass.
* **Color perception.** `doppler_temperature_shift` (in Kelvin) is
  computed every tick from the forward Doppler factor and exposed as
  a read-only output. **Materials are not modified** at this stage.
* **Motion-blur multiplier.** Computed every tick but not routed into
  any render engine's settings; visible in the debug log only.
* **Geometry.** Not deformed at the point level. The optional
  ``LS_Geometry_Proxy`` system (see below) wraps selected objects in a
  parent null and contracts their world transform along the velocity
  axis, leaving the original meshes untouched.

---

## Geometry proxy

The **LS_Geometry_Proxy** system gives you a non-destructive Lorentz
contraction without editing point data:

```
LS_Geometry_Proxy        (Null, oriented so local Z = velocity axis)
├── <your selected objects, world transforms preserved>
└── ...
```

### Workflow

1. Select the scene objects you want to contract.
2. Run **Extensions ▸ LS Cam: Add Relativistic Geometry Proxy**. The
   plugin reads `velocity_axis_source` / `velocity_custom_vector` /
   `affect_selected_only` from the controller, builds a null whose
   local Z axis is aligned with the chosen velocity, and reparents
   each target under it (world transforms preserved). An annotation
   tag named `LS_GeomProxyMember` is attached to each child so the
   remove command can recognise them later.
3. With `geometry_mode` set to **Proxy Scale**, the controller's
   evaluation tag drives the proxy's local Z scale to
   `1 + (sqrt(1 - β²) - 1) · contraction_strength` on every frame.
4. To unwrap, run **Extensions ▸ LS Cam: Remove Relativistic Geometry
   Proxy**. Children are placed back at the proxy's parent level
   (or the doc root) with their world transforms restored, and the
   proxy null is deleted. The whole add/remove cycle is undoable.

### Caveats

* **Animated or skinned objects.** The add command warns (console +
  dialog) when any target carries animated tracks, weight tags, or
  pose-morph tags. Wrapping still works, but a uniform-scale parent
  may interact badly with skin deformers — the contraction is applied
  *on top of* the rig's animation.
* **No Terrell rotation, no per-vertex transform.** This is a uniform
  scale along one axis. Real special-relativistic visual effects
  (Terrell-Penrose rotation, retarded-time sampling, per-pixel
  aberration) are out of scope for the proxy system; they require a
  ray-level pass and are flagged with TODO comments in
  `ls_geometry.py`.
* **Axis is captured at creation time.** Changing
  `velocity_axis_source` or the camera orientation after the proxy
  exists does *not* re-orient the proxy. Remove and re-add to pick
  up the new direction.
* The **Point Deform Approx** mode in the dropdown is reserved and
  currently a no-op with a TODO marker.

---

## Doppler material colour shift

The **Doppler material controller** lets you tint scene materials based
on the relativistic Doppler factor for the line of sight to the
objects that use them. Originals are never touched: every affected
material is cloned, and the clones are renamed `LS_Doppler_<original>`
and swapped into the texture tags.

### Workflow

1. In the Object Manager, select the objects whose materials should be
   shifted (their texture-tag materials get picked up automatically).
   You can additionally select materials in the Material Manager to
   include them explicitly.
2. Run **Extensions ▸ LS Cam: Add Doppler Material Controller**. For
   each selected material the plugin clones it, renames the clone with
   the `LS_Doppler_` prefix, stores the original name and baseline RGB
   in the clone's BaseContainer (private slots), and re-points every
   texture tag in the document that referenced the original at the
   clone. Wrapped in a single undo step.
3. With `enable_doppler_color` on, the controller's evaluation tag
   computes a per-clone Doppler factor each tick:
   - `forward = camera forward` (or whatever
     `velocity_axis_source` resolves to)
   - `look = (centroid_of_users − camera_pos).normalised()`
   - `cos_theta = forward · look`
   - `D = doppler_factor(beta, cos_theta)`
   - colour = `wavelength_shift_rgb_approx(baseline_rgb, D,
     doppler_color_strength · effect_strength)`

   Approaching objects (cos θ > 0) trend cooler/bluer; receding objects
   trend warmer/redder. The shift is bounded — `D` is floored,
   `wavelength_shift_rgb_approx` clamps the bleed and the output RGB,
   so colours always stay in `[0, 1]`.
4. To undo, run **Extensions ▸ LS Cam: Restore Original Materials**.
   Every texture tag pointing at an `LS_Doppler_*` clone is repointed
   at the original (looked up by stored name); every clone is then
   deleted. The whole operation is undoable.

### Caveats

* **Classic C4D materials only for live writes.** Octane / Redshift /
  Arnold node-graph materials store colour inside shader nodes, not on
  `MATERIAL_COLOR_COLOR`. The plugin still **clones** them so the
  add/restore lifecycle works identically, but the per-tick colour
  write is gated to `c4d.Mmaterial`. A single console warning is
  printed the first time a non-classic material is encountered. See
  `ls_doppler_materials.py` for the per-engine TODO list.
* **Texture / multi-shader chains** aren't re-tinted at the texture
  level — only the flat colour channel is shifted, and the material's
  textures multiply on top.
* **Duplicate detection** requires both the `LS_Doppler_` name prefix
  and a private marker in the clone's BaseContainer, so a user-named
  `LS_Doppler_MyShinyThing` material that wasn't created by this
  plugin will never be deleted by the restore command.
* **Original lookup is by name.** If you rename the original after
  duplication, restore will leave the affected texture tags
  unassigned and report which originals it couldn't find.

---

## Searchlight (relativistic beaming) effect

While `enable_searchlight_effect` is on, the controller's evaluation
tag drives a per-target intensity multiplier
``RM.searchlight_intensity_factor(beta, cos_theta, strength)`` for
each *controlled* object — clamped to `max_intensity_multiplier` to
prevent absurd blowouts at high β.

### Controlled-object set

The plugin never paints the whole scene. The "controlled" set is the
union of:

* the children of `LS_Geometry_Proxy`, if it exists, and
* every object whose texture tags reference an `LS_Doppler_<x>`
  material clone.

If neither system has been used, the searchlight effect is a no-op
and the evaluator logs a debug line saying so.

### Modes (`searchlight_mode`)

* **Viewport Only.** Per-object writes to `ID_BASEOBJECT_USECOLOR`
  (=2 / always) and `ID_BASEOBJECT_COLOR`. Cheap, always available,
  visible only in the viewport. Baseline `USECOLOR` + colour are
  stamped on the object in private BaseContainer slots before the
  first write so they can be restored 1:1.
* **Material Luminance.** Enables `MATERIAL_USE_LUMINANCE` and writes
  `MATERIAL_LUMINANCE_COLOR` on each `LS_Doppler_<x>` clone. The
  glow tints from the live `MATERIAL_COLOR_COLOR` of the clone, so
  the emission tracks the Doppler shift naturally. `cos_theta` is
  computed per-material from the centroid of the objects using it.
  Renders in production but only affects already-wrapped materials —
  run **LS Cam: Add Doppler Material Controller** first.
* **Octane Material Placeholder.** Reserved. Currently a one-shot
  logged no-op; node-material emission slots have to be mapped per
  Octane version (see TODO at the top of `ls_searchlight.py`).

### Restore

Switching modes (or disabling the effect) restores the previous
mode's baselines automatically. `reset_ls_camera_rig` calls
`ls_searchlight.restore_searchlight(doc)` to undo every stamped
baseline. Markers are cleared on restore so a subsequent re-enable
re-captures from the now-current state — you can edit baselines
while the effect is off and the plugin will respect your edits.

### Debugging

Set `debug_mode` on the controller to print per-target lines:

```
[searchlight][debug] viewport ObjectName: cos_theta=+0.7320 factor=2.31 color=Vector(...)
[searchlight][debug] luminance LS_Doppler_Skin: cos_theta=-0.4011 factor=0.42 glow=Vector(0,0,0)
```

---

## Presets (A Slower Speed of Light)

Run **Extensions ▸ LS Cam: Apply Relativity Preset** to open a small
modeless dialog with a preset dropdown plus *Apply* and *Reset*
buttons. Inspired by MIT Game Lab's *A Slower Speed of Light*, the
shipped presets are:

| Preset           | β     | effect | fov | dof | doppler | search | contraction |
|------------------|-------|--------|-----|-----|---------|--------|-------------|
| Human Speed      | 0.001 | 1.0    | 1.0 | 0.0 | 1.0     | 1.0    | 1.0         |
| Orb 25           | 0.25  | 1.0    | 1.0 | 0.5 | 1.0     | 1.0    | 1.0         |
| Orb 50           | 0.50  | 1.0    | 1.0 | 1.0 | 1.0     | 1.0    | 1.0         |
| Orb 75           | 0.75  | 1.0    | 1.0 | 1.0 | 1.2     | 1.2    | 1.0         |
| Near Light       | 0.95  | 1.5    | 1.5 | 1.5 | 1.5     | 1.5    | 1.0         |
| Absurd Artistic  | 0.99  | 2.0    | 2.0 | 2.0 | 2.0     | 2.0    | 1.0         |

* **Apply** writes only the seven strength/beta fields above. The
  per-effect `enable_*` toggles, the `geometry_mode` /
  `searchlight_mode` enums, and `debug_mode` are left alone — so a
  preset never accidentally enables an effect whose dependent system
  (e.g. the geometry proxy) hasn't been set up.
* **Reset** calls `ls_evaluator.reset_ls_camera_rig(doc, controller,
  camera)` on the active rig, snapping every camera baseline, every
  Doppler material clone, every searchlight baseline, and the proxy
  scale back to identity.

### Editing presets

`ls_presets.PRESETS_ORDERED` is the single source of truth — add or
edit `(name, dict)` tuples there and both the dialog dropdown and
`apply_preset` will pick them up. Unknown / typo'd UD keys are
ignored at apply time with a console warning, so a renamed constant
won't crash the preset system.

---

## Diagnostics

### HUD overlay

Run **Extensions ▸ LS Cam: Toggle Diagnostic Overlay** to add or
remove an `LS_Diagnostic_Overlay` null parented under the LS camera.
The null carries five `Osplinetext` children that the evaluator
refreshes every tick:

```
beta = …
gamma = …
contraction = …
doppler_fwd = …
searchlight = …
```

Per-row text is cached in a private BaseContainer slot, so the
relatively expensive `PRIM_TEXT_TEXT` write (which forces a spline
rebuild) only fires when the formatted value actually changed —
performance stays bounded in medium scenes. The overlay is parented
under the camera, so it follows the framing automatically.

The toggle command is symmetrical: hit it once to create, again to
remove. Removal is a single undoable step. The overlay is not part
of any Octane / render output by default — it is geometry, so it
will appear in renders if you frame it, but the scale/position offset
is set so it sits just inside the camera view as a viewport HUD.

### Debug material preview

Set the controller's `debug_material_preview` flag to **on** to
override every `LS_Doppler_<x>` clone's `MATERIAL_COLOR_COLOR` with a
cos(θ) heatmap:

* **blue** = approaching (cos θ → +1)
* **green** = perpendicular (cos θ → 0)
* **red** = receding (cos θ → −1)

The heatmap runs *after* the Doppler / searchlight passes, so it
wins for that tick. Toggling the flag off lets the next tick's
Doppler shift overwrite the heatmap automatically — no restore step
needed. Originals are never touched.

> Heads-up: this does affect production renders if you leave the flag
> on, because the heatmap is written to the same colour channel the
> renderer samples. Keep it off when you're not actively diagnosing.

### Display Color fallback

The existing **Searchlight Viewport Only** mode (`searchlight_mode =
Viewport Only`) writes `ID_BASEOBJECT_USECOLOR` + `ID_BASEOBJECT_COLOR`
on each controlled object — that's the display-color fallback path
for previewing the searchlight effect without a renderer. Doppler
material clones get their own colour shift on
`MATERIAL_COLOR_COLOR`, which similarly previews in the viewport
without requiring the renderer.

---

## Installation

1. **Locate your Cinema 4D plugin folder.**
   Either of these works (use the per-user folder if you don't have admin
   rights on the C4D install):
   - **Per user (recommended):**
     - Windows: `%APPDATA%\Maxon\<C4D version>\plugins\`
     - macOS: `~/Library/Preferences/Maxon/<C4D version>/plugins/`
     - Linux: `~/.config/Maxon/<C4D version>/plugins/`
   - **System-wide:** `<Cinema 4D install dir>/plugins/`

2. **Copy the `C4D_ls-cam/` folder** (the one that contains
   `c4d_ls_cam.pyp`) into that `plugins/` directory. The folder must be
   copied as a whole — the `.pyp` file relies on its sibling modules.

3. **Restart Cinema 4D.** On startup, the Python console should print:

   ```
   [C4D_ls-cam] Registered command plugin id=1000001.
   ```

4. **Run the command.** Open the **Extensions** menu and pick
   *Create LS Relativistic Camera Rig*. The new rig appears at the world
   origin and the camera is selected.

> **Plugin ID note:** `1000001` is a development-only placeholder in the
> Maxon-reserved test range. Before public distribution, register a real
> plugin ID at <https://plugincafe.maxon.net/c4dpluginid_cp> and replace
> `PLUGIN_ID` in `ls_constants.py`.

---

## Octane integration

The plugin tries to **discover** the Octane Camera Tag at runtime by
scanning registered tag plugins for one whose name contains both
`octane` and `camera` (`ls_octane.find_octane_camera_tag_id`). When
discovery succeeds, `ls_octane.add_octane_camera_tag(camera)` either
attaches a fresh tag or returns the existing one if the camera already
has one — never duplicates.

If discovery fails:

* Per-frame paths (the controller's evaluation tag, `build_rig`) stay
  silent and just skip the Octane step.
* Interactive paths (call with `show_dialog_on_failure=True`) raise the
  fixed dialog: *"Octane Camera Tag not found. Add it manually, then
  rerun Update LS Camera Rig."*

You can also override discovery by setting `OCTANE_CAMERA_TAG_ID` at the
top of `ls_octane.py` to a known integer plugin ID.

### How to map Octane parameter IDs

Octane's camera-tag parameter IDs are **not version-stable**, so we never
hardcode them blindly. Instead, `ls_octane_params.py` defines symbolic
slots (`depth_of_field`, `aperture`, `motion_blur`, `imager_exposure`,
`imager_saturation`, `postfx_bloom_glare`) with `param_id: None`
placeholders, and you fill them in once per Octane version:

1. **Install Octane for C4D** and open any scene.
2. **Add an Octane Camera Tag** to any camera, then select that tag in
   the Object Manager.
3. **Open the Python Console** (`Extensions ▸ Console`) and run:

   ```python
   from C4D_ls_cam import ls_octane
   ls_octane.dump_octane_tag_parameters(doc.GetActiveTag())
   ```

   The console prints one line per parameter:

   ```
   [C4D_ls-cam] === Octane tag parameter dump ===
   [C4D_ls-cam] tag name : Octane Camera Tag
   [C4D_ls-cam] tag type : 1029524
   [C4D_ls-cam]   DescID[(1001,19,1029524)] : Aperture = 0.2
   [C4D_ls-cam]   DescID[(1002,15,1029524)] : Depth Of Field = True
   ...
   [C4D_ls-cam] === end dump (N params) ===
   [C4D_ls-cam] Slots awaiting param_id mapping in
   ls_octane_params.OCTANE_CAMERA_PARAMS: ['depth_of_field', 'aperture', ...]
   ```

4. **Find the lines that match the symbolic slots** in
   `ls_octane_params.OCTANE_CAMERA_PARAMS` and copy each DescID into the
   matching slot, replacing `None`. The simplest form is just the integer
   from the first level of the DescID:

   ```python
   PARAM_APERTURE: {
       "label": "Aperture",
       "description": "Lens aperture size; drives bokeh diameter.",
       "param_id": 1001,   # <-- pasted from the dump
   },
   ```

   If you need a multi-level descriptor, paste a `c4d.DescID(...)`
   directly. Both forms are accepted by downstream code.

5. **Save the file and reload the plugin** (or restart C4D). Mapped
   slots will then be usable; unmapped slots remain skipped — never
   guessed.

> Do **not** commit guessed IDs. A wrong ID can silently misroute a
> value into an unrelated parameter.

---

## File layout

```
C4D_ls-cam/
├── c4d_ls_cam.pyp     # plugin entry point + CommandData registration
├── ls_constants.py    # IDs, names, user-data definitions
├── ls_rig.py          # rig builder (camera, null, tag, user data, undo)
├── ls_evaluator.py    # update_ls_camera_rig + reset_ls_camera_rig
├── ls_geometry.py     # LS_Geometry_Proxy add/remove + live contraction
├── ls_doppler_materials.py  # LS_Doppler_<name> material clones + live colour shift
├── ls_searchlight.py  # per-target relativistic-beaming intensity (viewport / luminance / Octane)
├── ls_presets.py      # A Slower Speed of Light preset table + apply_preset
├── ls_diagnostics.py  # HUD overlay + cos-theta debug material preview
├── ls_octane.py       # Octane discovery / attach / dump
├── ls_octane_params.py    # symbolic slot table for Octane camera-tag params
├── ls_relativity_math.py  # pure-Python relativistic helpers (no c4d import)
├── ls_ui.py           # status / dialog / console helpers
├── res/               # icons, .res / .str files (reserved)
├── README.md
└── CHANGELOG.md
```

---

## Development

- **Target:** Cinema 4D 2025+ (Python 3 SDK).
- **Reload during development:** `Extensions ▸ User Scripts ▸ Reload Python
  Plugins` (or restart C4D).
- **Console:** `Extensions ▸ Console` shows the registration message and any
  tracebacks emitted by `Execute()`.
- **Test the math module standalone:**

  ```
  cd C4D_ls-cam
  python3 ls_relativity_math.py
  ```

  Prints `ls_relativity_math: all self-tests passed.` on success. The
  module imports only the standard library, so it runs in any Python 3.
