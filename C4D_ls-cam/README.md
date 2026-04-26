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

`enable_octane_camera_tag` is wired up in the user data, but the actual tag
attachment is gated behind a **verified** Octane Camera Tag plugin ID. Octane
ships different IDs across versions, so we refuse to guess.

To finish the wiring:

1. Install Octane for Cinema 4D and load any scene.
2. Add an Octane Camera Tag to a camera, then select that tag.
3. In the C4D Python console run:

   ```python
   import c4d
   print(doc.GetActiveTag().GetType())
   ```

4. Paste the printed integer into `OCTANE_CAMERA_TAG_ID` in
   `ls_octane.py` (replacing the `None` placeholder).

Until then, `add_octane_camera_tag()` is a safe no-op that prints a notice
to the console.

---

## File layout

```
C4D_ls-cam/
├── c4d_ls_cam.pyp     # plugin entry point + CommandData registration
├── ls_constants.py    # IDs, names, user-data definitions
├── ls_rig.py          # rig builder (camera, null, tag, user data, undo)
├── ls_octane.py       # Octane integration placeholder
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
