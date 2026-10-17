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


def _work_dirs():
    root = Path(orca.host.plugin.storage()) / "edit_in_blender"
    return root / "in", root / "out", root / "session.blend", root / "blender_startup.py"


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


def _open_in_orca(paths):
    """Hand files to the running OrcaSlicer via the OS file-open mechanism."""
    system = platform.system()
    for p in paths:
        if system == "Darwin":
            subprocess.Popen(["open", "-a", "OrcaSlicer", str(p)])
        elif system == "Windows":
            os.startfile(str(p))  # noqa: S606 - uses the .stl file association
        else:
            subprocess.Popen(["xdg-open", str(p)])


class _Configurable:
    def get_default_config(self):
        return {"blender_path": DEFAULT_BLENDER.get(platform.system(), "blender")}

    def _blender_path(self):
        try:
            cfg = json.loads(self.get_config())
        except (TypeError, ValueError):
            cfg = {}
        return cfg.get("blender_path") or self.get_default_config()["blender_path"]


class EditInBlender(_Configurable, orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Edit in Blender"

    def execute(self):
        in_dir, out_dir, session, startup = _work_dirs()
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in (*in_dir.glob("*.stl"), *out_dir.glob("*.stl")):
            old.unlink()

        exported = 0
        for i, obj in enumerate(orca.host.model().objects()):
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
            name = f"{i:02d}_{_safe(getattr(obj, 'name', '') or 'object')}"
            _write_binary_stl(in_dir / f"{name}.stl", np.vstack(verts), np.vstack(tris))
            exported += 1

        if not exported:
            return orca.ExecutionResult.skipped("The plate has no objects to export.")

        startup.write_text(BLENDER_SCRIPT, encoding="utf-8")
        blender = self._blender_path()
        try:
            subprocess.Popen(
                [blender, "--python", str(startup), "--", str(in_dir), str(out_dir), str(session)]
            )
        except OSError as e:
            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                f"Could not launch Blender at '{blender}': {e}. Set blender_path in the plugin config.",
            )
        return orca.ExecutionResult.success(
            f"Exported {exported} object(s) to Blender. Save (Ctrl+S) in Blender, "
            "then run 'Load Blender Edits'."
        )


class LoadBlenderEdits(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Load Blender Edits"

    def execute(self):
        _, out_dir, _, _ = _work_dirs()
        files = sorted(out_dir.glob("*.stl"))
        if not files:
            return orca.ExecutionResult.skipped(
                "No edited meshes found. Save the session in Blender first."
            )
        _open_in_orca(files)
        return orca.ExecutionResult.success(
            f"Opened {len(files)} edited object(s) in OrcaSlicer. "
            "Delete the originals from the plate if you no longer need them."
        )


@orca.plugin
class EditInBlenderPlugin(orca.base):
    def register_capabilities(self):
        orca.register_capability(EditInBlender)
        orca.register_capability(LoadBlenderEdits)
