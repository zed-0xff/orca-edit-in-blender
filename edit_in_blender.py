# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
#
# [tool.orcaslicer.plugin]
# name = "Edit in Blender"
# description = "Export plate objects to Blender, edit them, and load the result back into OrcaSlicer."
# author = "Andrey Zaikin"
# version = "0.1.0"
# ///
import json
import os
import platform
import subprocess
from pathlib import Path

import numpy as np
import orca

# Runs inside Blender (blender --python). Imports the exported STLs, saves a
# session .blend so Ctrl+S works, and re-exports every mesh object to OUT_DIR
# on each save.
BLENDER_SCRIPT = '''
import bpy, sys
from pathlib import Path

argv = sys.argv[sys.argv.index("--") + 1:]
IN_DIR, OUT_DIR, SESSION = Path(argv[0]), Path(argv[1]), argv[2]
OUT_DIR.mkdir(parents=True, exist_ok=True)

def import_stl(path):
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(path))
    else:
        bpy.ops.import_mesh.stl(filepath=str(path))

def export_stl(path):
    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=True)
    else:
        bpy.ops.export_mesh.stl(filepath=str(path), use_selection=True)

def export_all(*_):
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        export_stl(OUT_DIR / (obj.name + ".stl"))
    print("Edit in Blender: exported to", OUT_DIR)

def setup():
    # Runs from a timer: during --python startup the UI context isn't ready,
    # so import operators fail their poll().
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for stl in sorted(IN_DIR.glob("*.stl")):
        import_stl(stl)
    bpy.ops.wm.save_as_mainfile(filepath=SESSION)
    bpy.app.handlers.save_post.append(export_all)
    return None

bpy.app.timers.register(setup, first_interval=1.0)
'''

DEFAULT_BLENDER = {
    "Darwin": "/Applications/Blender.app/Contents/MacOS/Blender",
    "Windows": r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    "Linux": "blender",
}

PANEL_HTML = """
<style>
  body { font-family: var(--orca-font, sans-serif); color: var(--orca-fg); background: var(--orca-bg);
         margin: 0; padding: 10px; font-size: 13px; }
  button { background: var(--orca-accent); color: #fff; border: 0; border-radius: 4px;
           padding: 6px 10px; margin: 2px 2px 2px 0; cursor: pointer; }
  button:disabled { opacity: 0.4; cursor: default; }
  button.secondary { background: transparent; color: var(--orca-fg); border: 1px solid var(--orca-border); }
  h4 { margin: 12px 0 4px; }
  label { display: block; padding: 2px 0; }
  .muted { color: var(--orca-muted); font-size: 12px; word-break: break-all; }
  input[type=text] { width: 100%; box-sizing: border-box; background: transparent; color: var(--orca-fg);
                     border: 1px solid var(--orca-border); border-radius: 4px; padding: 4px; }
  #status { margin-top: 10px; min-height: 2em; }
  body.compact .full-only { display: none; }
</style>
<h4>Objects on plate</h4>
<div id="objects" class="muted">Loading...</div>
<button class="secondary" id="refresh">Refresh</button>
<button class="secondary" id="all">Select all</button>
<div id="actions">
  <h4 class="full-only">Send</h4>
  <button id="export">Edit selected</button>
  <h4 class="full-only">Receive</h4>
  <button id="load" disabled>Load edits</button>
</div>
<div class="full-only">
  <button class="secondary" id="reveal">Reveal edits folder</button>
  <button class="secondary" id="copy">Copy path</button>
  <div class="muted" id="outdir"></div>
  <h4>Blender path</h4>
  <input type="text" id="blender">
  <button class="secondary" id="save">Save path</button>
  <label><input type="checkbox" id="auto"> Open this panel at startup</label>
</div>
<div id="status" class="muted"></div>
<script>
  const $ = id => document.getElementById(id);
  const send = (type, extra) => orca.postMessage(Object.assign({type}, extra || {}));
  let outDir = "";
  const updateExport = () => {
    $("export").disabled = !document.querySelector("#objects input:checked");
  };
  $("objects").addEventListener("change", updateExport);
  $("refresh").onclick = () => send("refresh");
  $("all").onclick = () => {
    document.querySelectorAll("#objects input").forEach(c => c.checked = true);
    updateExport();
  };
  $("export").onclick = () => send("export", {indices:
      [...document.querySelectorAll("#objects input:checked")].map(c => Number(c.value))});
  $("load").onclick = () => send("load");
  $("reveal").onclick = () => send("reveal");
  $("auto").onchange = () => send("set_auto_open", {value: $("auto").checked});
  $("save").onclick = () => send("set_blender", {path: $("blender").value});
  $("copy").onclick = () => {
    navigator.clipboard.writeText(outDir).then(
      () => $("status").textContent = "Path copied.",
      () => $("status").textContent = "Copy failed; select the path above manually.");
  };
  orca.onMessage(m => {
    if (m.type === "state") {
      document.body.classList.toggle("compact", m.compact_mode);
      outDir = m.out_dir;
      $("outdir").textContent = m.out_dir;
      $("blender").value = m.blender;
      $("auto").checked = m.auto_open;
      $("load").disabled = !m.has_edits;
      const box = $("objects");
      box.textContent = "";
      if (!m.objects.length) box.textContent = "The plate is empty.";
      m.objects.forEach(o => {
        const l = document.createElement("label");
        const c = document.createElement("input");
        c.type = "checkbox"; c.value = o.index; c.checked = true;
        l.append(c, " " + o.name + " (" + o.triangles + " tris)");
        box.append(l);
      });
      updateExport();
    } else if (m.type === "edits") {
      $("load").disabled = !m.has;
    } else if (m.type === "status") {
      $("status").textContent = m.message;
    }
  });
  updateExport();
  send("refresh");
  setInterval(() => send("poll_edits"), 2000);
</script>
"""


_storage = None


def _init_storage():
    """storage() only works inside a capability callback (execute/on_load), not panel messages."""
    global _storage
    _storage = Path(orca.host.plugin.storage()) / "edit_in_blender"


def _dirs():
    root = _storage
    return root / "in", root / "out", root / "session.blend", root / "blender_startup.py", root / "settings.json"


_settings = {}
_config_owner = None


def _default_settings():
    return {"blender_path": DEFAULT_BLENDER.get(platform.system(), "blender"),
            "auto_open": True, "compact_mode": False}


def _load_settings(owner):
    """Read the capability's native config. Needs a plugin callback (on_load/execute)."""
    global _settings, _config_owner
    _config_owner = owner
    try:
        stored = json.loads(owner.get_config())
    except (TypeError, ValueError):
        stored = {}
    _settings = {**_default_settings(), **stored}
    if _settings != stored:
        # Write missing keys back so the config the user sees lists every option.
        try:
            owner.save_config(json.dumps(_settings))
        except Exception:
            pass
    legacy = _dirs()[4]  # settings.json from before the native config
    if legacy.exists():
        try:
            _settings.update(json.loads(legacy.read_text()))
            if owner.save_config(json.dumps(_settings)):
                legacy.unlink()
        except (OSError, ValueError):
            pass


def _update_settings(**changes):
    """Apply changes in memory and persist them; returns False if persisting failed."""
    _settings.update(changes)
    try:
        return bool(_config_owner.save_config(json.dumps(_settings)))
    except Exception:
        return False


def _blender_path():
    return _settings.get("blender_path") or _default_settings()["blender_path"]


def _has_edits():
    return any(_dirs()[1].glob("*.stl"))


def _auto_open():
    return _settings.get("auto_open", True)


def _write_binary_stl(path, vertices, triangles):
    tris = vertices[triangles].astype(np.float32)
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 0)
    record = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    data = np.zeros(len(tris), dtype=record)
    data["n"], data["v"] = normals, tris
    with open(path, "wb") as f:
        f.write(b"Edit in Blender".ljust(80, b"\0"))
        f.write(np.uint32(len(tris)).tobytes())
        f.write(data.tobytes())


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "object"


def _object_name(obj, i):
    return getattr(obj, "name", "") or f"object {i}"


def _list_objects():
    items = []
    for i, obj in enumerate(orca.host.model().objects()):
        tris = sum(v.mesh().triangle_count() for v in obj.volumes())
        items.append({"index": i, "name": _object_name(obj, i), "triangles": tris})
    return items


def _open_path(path, reveal_app=None):
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", *(["-a", reveal_app] if reveal_app else []), str(path)])
    elif system == "Windows":
        os.startfile(str(path))  # noqa: S606 - uses the file association
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _export_and_launch(indices=None):
    """Export objects (all if indices is None) to STL and launch Blender.

    Returns an ExecutionResult.
    """
    in_dir, out_dir, session, startup, _ = _dirs()
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in (*in_dir.glob("*.stl"), *out_dir.glob("*.stl")):
        old.unlink()

    exported = 0
    for i, obj in enumerate(orca.host.model().objects()):
        if indices is not None and i not in indices:
            continue
        verts, tris = [], []
        offset = 0
        for vol in obj.volumes():
            mesh = vol.mesh()
            if mesh.is_empty():
                continue
            v = mesh.vertices().astype(np.float64)
            m = vol.matrix()
            v = v @ m[:3, :3].T + m[:3, 3]
            verts.append(v)
            tris.append(mesh.triangles().astype(np.int64) + offset)
            offset += len(v)
        if not verts:
            continue
        name = f"{i:02d}_{_safe(_object_name(obj, i))}"
        _write_binary_stl(in_dir / f"{name}.stl", np.vstack(verts), np.vstack(tris))
        exported += 1

    if not exported:
        return orca.ExecutionResult.skipped("No objects to export.")

    startup.write_text(BLENDER_SCRIPT, encoding="utf-8")
    blender = _blender_path()
    try:
        subprocess.Popen(
            [blender, "--python", str(startup), "--", str(in_dir), str(out_dir), str(session)]
        )
    except OSError as e:
        return orca.ExecutionResult.failure(
            orca.PluginResult.RecoverableError,
            f"Could not launch Blender at '{blender}': {e}. Set the path in the Edit in Blender panel.",
        )
    return orca.ExecutionResult.success(
        f"Exported {exported} object(s) to Blender. Save (Ctrl+S) in Blender, then load the edits."
    )


def _load_edits():
    out_dir = _dirs()[1]
    files = sorted(out_dir.glob("*.stl"))
    if not files:
        return orca.ExecutionResult.skipped("No edited meshes found. Save the session in Blender first.")
    for f in files:
        _open_path(f, reveal_app="OrcaSlicer")
    return orca.ExecutionResult.success(
        f"Opened {len(files)} edited object(s) in OrcaSlicer. Delete the originals if no longer needed."
    )


class EditInBlenderPanel(orca.script.ScriptPluginCapabilityBase):
    """Docked Edit in Blender panel; opens on load, or via its Run action."""

    def __init__(self):
        super().__init__()
        self._panel = None

    def get_name(self):
        return "Show Edit in Blender Panel"

    def get_default_config(self):
        return _default_settings()

    def on_load(self):
        # Auto-open at startup. If the host isn't ready for UI yet, fall back to
        # running "Show Edit in Blender Panel" from the Plugins dialog.
        try:
            _init_storage()
            _load_settings(self)
            if _auto_open():
                self._open_panel()
        except Exception as e:
            print(f"Edit in Blender: could not auto-open panel from on_load: {e!r}")

    def execute(self):
        if self._panel is not None:
            return orca.ExecutionResult.skipped("The panel is already open.")
        self._open_panel()
        return orca.ExecutionResult.success("Edit in Blender panel opened.")

    def _open_panel(self):
        _init_storage()
        _load_settings(self)
        if self._panel is not None:
            return
        self._panel = orca.host.ui.create_dock_panel(
            html=PANEL_HTML,
            title="Edit in Blender",
            width=220 if _settings.get("compact_mode") else 320,
            height=300 if _settings.get("compact_mode") else 520,
            on_message=self.on_message,
            on_close=self.on_close,
            dock="right",
        )

    def on_close(self, *_):
        self._panel = None

    def _status(self, message):
        self._panel.post({"type": "status", "message": message})

    def on_message(self, data):
        if isinstance(data, str):
            data = json.loads(data)
        kind = data.get("type")
        try:
            if kind == "refresh":
                try:  # pick up edits made in the Plugins dialog's config tab
                    _settings.update(json.loads(self.get_config()))
                except Exception:
                    pass
                self._panel.post({
                    "type": "state",
                    "objects": _list_objects(),
                    "out_dir": str(_dirs()[1]),
                    "blender": _blender_path(),
                    "auto_open": _auto_open(),
                    "has_edits": _has_edits(),
                    "compact_mode": bool(_settings.get("compact_mode")),
                })
            elif kind == "poll_edits":
                self._panel.post({"type": "edits", "has": _has_edits()})
            elif kind == "export":
                indices = set(data.get("indices") or [])
                if not indices:
                    return self._status("Select at least one object.")
                result = _export_and_launch(indices)
                self._panel.post({"type": "edits", "has": _has_edits()})
                self._status(result.message)
            elif kind == "load":
                self._status(_load_edits().message)
            elif kind == "reveal":
                out_dir = _dirs()[1]
                out_dir.mkdir(parents=True, exist_ok=True)
                _open_path(out_dir)
            elif kind == "set_blender":
                ok = _update_settings(blender_path=data.get("path", "").strip())
                self._status("Blender path saved." if ok else
                             "Applied for this session, but saving to the plugin config failed.")
            elif kind == "set_auto_open":
                ok = _update_settings(auto_open=bool(data.get("value")))
                if not ok:
                    self._status("Applied for this session, but saving to the plugin config failed.")
                else:
                    self._status("Panel will open at startup." if data.get("value")
                                 else "Panel will not open at startup. Use 'Show Edit in Blender Panel'.")
        except Exception as e:  # keep the panel alive; show the error inline
            self._status(f"Error: {e}")


@orca.plugin
class EditInBlenderPlugin(orca.base):
    def register_capabilities(self):
        orca.register_capability(EditInBlenderPanel)
