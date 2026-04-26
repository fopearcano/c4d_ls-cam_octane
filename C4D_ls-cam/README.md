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

| Parameter                  | Type  | Default | Range          |
|----------------------------|-------|---------|----------------|
| `beta_velocity`            | float | 0.0     | 0.0 – 0.999    |
| `speed_of_light_scale`     | float | 1.0     | 0.0001 – 1000  |
| `effect_strength`          | float | 1.0     | 0.0 – 2.0      |
| `enable_lorentz_geometry`  | bool  | true    | —              |
| `enable_doppler_color`     | bool  | true    | —              |
| `enable_searchlight_effect`| bool  | true    | —              |
| `enable_octane_camera_tag` | bool  | false   | —              |
| `debug_mode`               | bool  | false   | —              |

The whole rig is built in a single undo step — one `Ctrl+Z` removes
everything the command inserted.

### Computed (read-only) outputs

These fields are written by `ls_evaluator.update_ls_camera_rig()` on every
scene evaluation. They are exposed as user-data so artists can read them
in the Attribute Manager, but they are overwritten every tick — treat
them as read-only:

| Output                    | Meaning                                                  |
|---------------------------|----------------------------------------------------------|
| `gamma`                   | Lorentz factor `1 / sqrt(1 - β²)`                        |
| `contraction_factor`      | `sqrt(1 - β²)` (length contraction along motion axis)    |
| `doppler_forward_factor`  | Doppler `D` for a head-on line of sight                  |
| `searchlight_multiplier`  | Relativistic-beaming intensity multiplier (`D^4·strength`) |

### Camera behavior

* **FOV.** The camera's rest FOV is captured at rig creation and stored
  on the controller. While `enable_lorentz_geometry` is on, the live FOV
  is `rest_fov · (1 + 0.5 · β · effect_strength)`. Disabling the flag (or
  setting beta to 0) restores the rest FOV exactly — the effect is
  non-destructive.
* **Motion-blur multiplier.** Computed every tick but not yet routed into
  any render engine's settings; visible in the debug log only.
* **Geometry / materials.** Not deformed or modified at this stage.
* **Octane.** Not required at this stage.

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
├── ls_evaluator.py    # update_ls_camera_rig: drives camera + UD outputs
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
