# Edit in Blender

An [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) 2.5.0+ plugin that sends objects from the plate to
[Blender](https://www.blender.org/), and brings the edited meshes back.

It adds a docked **Edit in Blender** panel:

- lists the objects on the plate and refreshes itself when objects are added, deleted or renamed;
- **Edit selected** exports the checked objects as STL and opens them in Blender;
- saving in Blender (<kbd>Ctrl</kbd>+<kbd>S</kbd>) writes the edited meshes back;
- **Load edits** opens the edited meshes in OrcaSlicer.

Further **Edit selected** clicks reuse the Blender window the plugin started. Blender windows you opened yourself
are never touched.

## Install

- **Orca Cloud:** subscribe to the plugin in the Plugins window (Menu > Plugins).
- **Manually:** put `edit_in_blender_any.py` in its own folder under `<OrcaSlicer data dir>/orca_plugins/`, or use
  *Menu > Plugins* to install it from your computer.

Dependencies (`numpy`) are installed by OrcaSlicer's bundled `uv`. OrcaSlicer asks for permission the first time the
plugin writes files or starts Blender.

Run **Show Edit in Blender Panel** from the Plugins window to open the panel. By default it opens at startup.

## Use

1. Tick the objects to edit and click **Edit selected**. Blender opens with the objects.
2. Edit them and press <kbd>Ctrl</kbd>+<kbd>S</kbd> in Blender.
3. Click **Load edits** in OrcaSlicer. The edited objects are added to the plate as new objects.

The panel's **Reveal edits folder** and **Copy path** buttons point at the folder with the edited STLs.

## Configuration

Edit the plugin's config in the Plugins window.

| Key | Default | Meaning |
| --- | --- | --- |
| `blender_path` | OS default | Blender executable |
| `auto_open` | `true` | Open the panel at startup |
| `compact_mode` | `true` | Hide the extra panel entries and show only the object list and the two buttons |
| `panel_width` | `320` | Panel width, updated when you resize it |
| `compact_panel_width` | `150` | Panel width in compact mode |

## Limitations

OrcaSlicer's plugin API is read-only for the model, which shapes how this plugin works:

- Edited meshes come back as **new objects**. Original objects are not replaced, and positions are not restored.
  Delete the originals yourself.
- The API cannot read or set the selection, so the panel has its own checkboxes.
- Instance transforms are not applied to the export; each object is exported in its own coordinate space.
- **Load edits** opens the files with the operating system, so OrcaSlicer must be the application that handles
  them. This is tested on macOS only; on Windows and Linux it uses the default `.stl` handler.
- The Blender window is not brought to the front automatically.

Working files live in the plugin data folder under `edit_in_blender/session_*`. The newest previous session is
kept for recovery; older ones are deleted when a new Blender session starts.

## Upstream status

Several limitations above come from the OrcaSlicer plugin API. Open OrcaSlicer issues and PRs that touch them
(checked 2026-10-17):

- [#16408](https://github.com/OrcaSlicer/OrcaSlicer/issues/16408): plugin API to add parts (volumes) to an object
  on the plate. This is the closest request to replacing an edited mesh in place.
- [#15720](https://github.com/OrcaSlicer/OrcaSlicer/issues/15720): expose read-only plate context and instance
  membership to plugins.
- [#15444](https://github.com/OrcaSlicer/OrcaSlicer/pull/15444): visualization plugin API. It gives plugins a
  copy of the plate's models and adds actions to object context menus; it does not write to the plate.

## Development

The plugin is a single file, `edit_in_blender_any.py`, using the PEP 723 metadata block and the `orca` module from the
[plugin API](https://www.orcaslicer.com/wiki/developer_reference/plugin_development/plugin_development).
The `_any` suffix in the file name is what the Orca Cloud upload form expects for a platform-independent plugin, so
the same file is used for GitHub installs and for the cloud upload.

## License

[MIT](LICENSE)
