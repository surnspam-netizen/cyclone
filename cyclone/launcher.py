#!/usr/bin/env python3
"""Cyclone - an arctic-minimal Minecraft client/launcher.

Run:  python launcher.py
Needs: Python 3.9+, Java is auto-downloaded, and `pip install minecraft-launcher-lib`.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if getattr(sys, "frozen", False):  # running as the packaged .exe
    ROOT = Path(sys.executable).resolve().parent          # mods/ and data live next to the exe
    UI_DIR = Path(getattr(sys, "_MEIPASS", ROOT)) / "ui"  # UI is bundled inside the exe
else:
    ROOT = Path(__file__).resolve().parent
    UI_DIR = ROOT / "ui"
DATA = ROOT / "cyclone_data"
MC_DIR = DATA / "minecraft"
USER_MODS = ROOT / "mods"            # drop your own .jar mods here
BUILTIN_CACHE = DATA / "builtin-mods"  # inbuilt FPS mods land here
SETTINGS_FILE = DATA / "settings.json"
PORT = 8765
UA = "Cyclone-Client/1.0 (local launcher)"

# Inbuilt mods (Modrinth slugs). fabric-api is required by most of them.
BUILTIN_MODS = [
    {"slug": "fabric-api", "name": "Fabric API", "desc": "Required base library", "locked": True},
    {"slug": "sodium", "name": "Sodium", "desc": "Modern rendering engine, big FPS gains"},
    {"slug": "lithium", "name": "Lithium", "desc": "Faster game logic and ticks"},
    {"slug": "ferrite-core", "name": "FerriteCore", "desc": "Lower memory usage"},
    {"slug": "entityculling", "name": "Entity Culling", "desc": "Skips drawing hidden entities"},
    {"slug": "immediatelyfast", "name": "ImmediatelyFast", "desc": "Faster HUD and GUI drawing"},
    {"slug": "modernfix", "name": "ModernFix", "desc": "Faster startup, fewer stutters"},
    {"slug": "krypton", "name": "Krypton", "desc": "Network stack optimisations"},
    {"slug": "dynamic-fps", "name": "Dynamic FPS", "desc": "Throttles when the window is idle"},
    {"slug": "sodium-extra", "name": "Sodium Extra", "desc": "FPS / coordinates overlay and extra video options"},
    {"slug": "modmenu", "name": "Mod Menu", "desc": "In-game mod list and configs"},
]

DEFAULTS = {
    "username": "Player",
    "version": "1.21.4",
    "ram_mb": 4096,
    "offline": True,
    "mods": {m["slug"]: True for m in BUILTIN_MODS},
}

state = {"status": "Ready", "progress": 0, "max": 0, "busy": False, "log": [], "running": False}
lock = threading.Lock()


def log(msg):
    with lock:
        state["log"].append(msg)
        state["log"] = state["log"][-60:]
        state["status"] = msg


def load_settings():
    DATA.mkdir(exist_ok=True)
    s = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            s.update(json.loads(SETTINGS_FILE.read_text()))
        except Exception:
            pass
    s["mods"] = {**DEFAULTS["mods"], **s.get("mods", {})}
    return s


def save_settings(s):
    DATA.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


def offline_uuid(name):
    """Same UUID vanilla Minecraft derives for offline players."""
    h = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode()).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_builtin(version, enabled):
    folder = BUILTIN_CACHE / version
    folder.mkdir(parents=True, exist_ok=True)
    for m in BUILTIN_MODS:
        slug = m["slug"]
        if not (m.get("locked") or enabled.get(slug)):
            continue
        if any(f.name.startswith(slug + "__") for f in folder.glob("*.jar")):
            continue
        log(f"Fetching {m['name']}...")
        try:
            q = urllib.parse.urlencode({
                "loaders": json.dumps(["fabric"]),
                "game_versions": json.dumps([version]),
            })
            versions = http_json(f"https://api.modrinth.com/v2/project/{slug}/version?{q}")
            if not versions:
                log(f"{m['name']} has no build for {version}, skipping")
                continue
            files = versions[0]["files"]
            f = next((x for x in files if x.get("primary")), files[0])
            dest = folder / f"{slug}__{f['filename']}"
            req = urllib.request.Request(f["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
                shutil.copyfileobj(r, out)
        except Exception as e:
            log(f"Could not fetch {m['name']}: {e}")


def sync_mods(version, enabled):
    """Game mods folder = enabled inbuilt mods + anything in ./mods."""
    game_mods = MC_DIR / "mods"
    game_mods.mkdir(parents=True, exist_ok=True)
    for old in game_mods.glob("*.jar"):
        old.unlink()
    USER_MODS.mkdir(exist_ok=True)
    folder = BUILTIN_CACHE / version
    for m in BUILTIN_MODS:
        if m.get("locked") or enabled.get(m["slug"]):
            for j in folder.glob(m["slug"] + "__*.jar"):
                shutil.copy(j, game_mods / j.name.split("__", 1)[1])
    for j in USER_MODS.glob("*.jar"):
        shutil.copy(j, game_mods / j.name)


def launch_worker(settings):
    try:
        import minecraft_launcher_lib as mll
    except ImportError:
        log("Missing dependency: run  pip install minecraft-launcher-lib")
        state["busy"] = False
        return
    try:
        ver = settings["version"]
        MC_DIR.mkdir(parents=True, exist_ok=True)

        def prog(v):
            state["progress"] = v

        def mx(v):
            state["max"] = v

        cb = {"setStatus": log, "setProgress": prog, "setMax": mx}

        log(f"Installing Minecraft {ver} + Fabric...")
        mll.fabric.install_fabric(ver, str(MC_DIR), callback=cb)
        loader = mll.fabric.get_latest_loader_version()
        version_id = f"fabric-loader-{loader}-{ver}"

        state["progress"], state["max"] = 0, 0
        fetch_builtin(ver, settings["mods"])
        sync_mods(ver, settings["mods"])

        options = {
            "username": settings["username"],
            "uuid": offline_uuid(settings["username"]),
            "token": "0",
            "jvmArguments": [
                f"-Xms{min(1024, settings['ram_mb'])}M",
                f"-Xmx{settings['ram_mb']}M",
                "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled",
                "-XX:MaxGCPauseMillis=100", "-XX:+UnlockExperimentalVMOptions",
                "-XX:+DisableExplicitGC", "-XX:G1NewSizePercent=30",
                "-XX:G1ReservePercent=20",
            ],
        }
        try:
            info = mll.runtime.get_version_runtime_information(ver, str(MC_DIR))
            if info:
                log("Preparing Java runtime...")
                mll.runtime.install_jvm_runtime(info["name"], str(MC_DIR), callback=cb)
                exe = mll.runtime.get_executable_path(info["name"], str(MC_DIR))
                if exe:
                    options["executablePath"] = exe
        except Exception as e:
            log(f"Using system Java ({e})")

        cmd = mll.command.get_minecraft_command(version_id, str(MC_DIR), options)
        log("Launching Cyclone...")
        proc = subprocess.Popen(cmd, cwd=str(MC_DIR))
        state["running"] = True
        state["busy"] = False
        proc.wait()
        state["running"] = False
        log("Game closed")
    except Exception as e:
        log(f"Launch failed: {e}")
    finally:
        state["busy"] = False
        state["running"] = False


def release_versions():
    try:
        import minecraft_launcher_lib as mll
        vs = [v["id"] for v in mll.utils.get_version_list() if v["type"] == "release"]
        return vs[:20]
    except Exception:
        try:
            m = http_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
            return [v["id"] for v in m["versions"] if v["type"] == "release"][:20]
        except Exception:
            return ["1.21.4", "1.21.1", "1.20.6", "1.20.4", "1.20.1", "1.19.4", "1.18.2", "1.16.5"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self._send(200, {**state, "settings": load_settings(), "mods": BUILTIN_MODS,
                                    "user_mods": sorted(p.name for p in USER_MODS.glob("*.jar"))})
        if self.path == "/api/versions":
            return self._send(200, release_versions())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/settings":
            s = load_settings()
            for k in ("username", "version", "ram_mb", "mods"):
                if k in body:
                    s[k] = body[k]
            s["username"] = "".join(c for c in str(s["username"]) if c.isalnum() or c == "_")[:16] or "Player"
            s["ram_mb"] = max(1024, min(int(s["ram_mb"]), 32768))
            save_settings(s)
            return self._send(200, s)
        if self.path == "/api/launch":
            if state["busy"] or state["running"]:
                return self._send(409, {"error": "already running"})
            state["busy"] = True
            threading.Thread(target=launch_worker, args=(load_settings(),), daemon=True).start()
            return self._send(200, {"ok": True})
        if self.path == "/api/open-mods":
            USER_MODS.mkdir(exist_ok=True)
            try:
                if sys.platform == "win32":
                    os.startfile(USER_MODS)  # noqa
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(USER_MODS)])
                else:
                    subprocess.Popen(["xdg-open", str(USER_MODS)])
            except Exception:
                pass
            return self._send(200, {"path": str(USER_MODS)})
        self._send(404, {"error": "not found"})


def main():
    USER_MODS.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Cyclone is running at {url}  (Ctrl+C to quit)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
