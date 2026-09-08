"""Viper Racing Mod Manager -- desktop app.

Wraps the local switcher web UI in a native window (pywebview). The HTTP server
runs in a background thread in THIS process, so the native folder picker can
point it at a Data folder directly (shared module state). Power users can still
drive everything through the `vrmod` CLI; this is just the GUI front door.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# This file lives in desktop/; the vrmod package sits at the repo root one level
# up. When run from source (python desktop/app.py) that root isn't on the path,
# so add it. When frozen by PyInstaller, vrmod is bundled and importable already.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webview

from vrmod import switcher_ui

APP_NAME = "Viper Racing Mod Manager"
WIN_SIZE = (1180, 800)
MIN_SIZE = (900, 600)


def _config_path() -> Path:
    """Per-user settings, e.g. the last-opened Data folder."""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "ViperModManager"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    try:
        _config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


class Api:
    """The bridge the page reaches as window.pywebview.api."""

    def pick_folder(self) -> dict:
        """Open the OS folder picker, validate, and point the server at it."""
        win = webview.active_window()
        result = win.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"ok": False}                      # user cancelled
        path = result[0] if isinstance(result, (list, tuple)) else result
        if not switcher_ui.is_data_folder(path):
            return {"ok": False,
                    "error": "That folder has no race.bin or .car files -- "
                             "pick the game's Data folder."}
        switcher_ui.set_data_dir(path)
        cfg = _load_config()
        cfg["last_folder"] = str(path)
        _save_config(cfg)
        return {"ok": True, "path": str(path)}

    def current_folder(self):
        d = switcher_ui.get_data_dir()
        return str(d) if d else None

    def save_into_folder(self, filename: str, b64: str) -> dict:
        """Native FOLDER picker for a file whose name is load-bearing.

        A forked car must keep `<prefix>.car` to match its own internal members
        (`jeep.car` holds `jeep0.mod`), so the user picks only the directory and
        we write `filename` into it -- a SAVE_DIALOG would let them rename it and
        quietly produce a car the game can't load. Refuses to clobber an existing
        file; the caller reports the message."""
        import base64
        win = webview.active_window()
        result = win.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"ok": False}                       # user cancelled
        folder = result[0] if isinstance(result, (list, tuple)) else result
        path = Path(folder) / filename
        if path.exists():
            return {"ok": False, "error": f"{filename} already exists in that folder."}
        try:
            path.write_bytes(base64.b64decode(b64))
        except (OSError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": str(path)}

    def save_file(self, filename: str, b64: str) -> dict:
        """Native Save-As for a file the page generated in the browser (Export
        TGA, an OBJ bundle, ...). The embedded webview can't honor an <a
        download> / blob download, so the page base64-encodes the bytes and
        hands them here; we pop the OS save dialog and write them where the user
        picks. (A plain browser keeps the <a download> path -- see viewer.py's
        downloadBytes.)"""
        import base64
        win = webview.active_window()
        result = win.create_file_dialog(webview.SAVE_DIALOG, save_filename=filename)
        if not result:
            return {"ok": False}                       # user cancelled
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            Path(path).write_bytes(base64.b64decode(b64))
        except (OSError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": str(path)}


def main() -> None:
    # Reopen the last folder if it still looks valid, so the app lands straight
    # in it; otherwise it opens on the landing screen.
    cfg = _load_config()
    last = cfg.get("last_folder")
    if last and switcher_ui.is_data_folder(last):
        switcher_ui.set_data_dir(last)

    _, port = switcher_ui.start_server(port=0)         # 0 -> a free localhost port
    webview.create_window(
        APP_NAME, f"http://127.0.0.1:{port}/",
        js_api=Api(), width=WIN_SIZE[0], height=WIN_SIZE[1], min_size=MIN_SIZE)
    webview.start()


if __name__ == "__main__":
    main()
