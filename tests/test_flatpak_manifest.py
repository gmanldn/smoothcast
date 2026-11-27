"""Offline Flatpak package shape/security checks; not a native build qualification."""
from __future__ import annotations

from configparser import ConfigParser
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = "io.github.gmanldn.SmoothCast"
MANIFEST = ROOT / "packaging/flatpak" / f"{APP}.json"
DESKTOP = ROOT / "packaging/flatpak" / f"{APP}.desktop"


class FlatpakManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def app_module(self) -> dict:
        return next(m for m in self.manifest["modules"]
                    if isinstance(m, dict) and m["name"] == "smoothcast")

    def test_gnome_runtime_and_real_installed_command(self):
        m = self.manifest
        self.assertEqual(m["id"], APP)
        self.assertEqual(m["runtime"], "org.gnome.Platform")
        self.assertEqual(m["sdk"], "org.gnome.Sdk")
        self.assertEqual(m["command"], "smoothcast")
        self.assertEqual(m["runtime-version"], "51")  # Current supported GNOME release
        build = "\n".join(self.app_module()["build-commands"])
        self.assertIn("--no-index", build)
        self.assertIn("--no-build-isolation", build)
        self.assertIn("--prefix=${FLATPAK_DEST}", build)
        self.assertIn("command -v ffmpeg", build)
        self.assertIn("command -v ffprobe", build)
        self.assertIn("command -v ffplay", build)
        self.assertIn("libx264", build)
        self.assertIn("gi.require_version", build)

    def test_permissions_are_lan_focused_without_broad_host_control(self):
        args = self.manifest["finish-args"]
        self.assertEqual(len(args), len(set(args)))
        for required in ("--share=network", "--share=ipc", "--socket=wayland",
                         "--socket=fallback-x11", "--socket=pulseaudio",
                         "--device=dri", "--filesystem=home:ro"):
            self.assertIn(required, args)
        for prohibited in ("--filesystem=host", "--filesystem=home",
                           "--socket=system-bus", "--device=all",
                           "--talk-name=org.freedesktop.Flatpak"):
            self.assertNotIn(prohibited, args)
        self.assertFalse(any("home:rw" in arg for arg in args))

    def test_app_comes_from_this_checkout_and_cannot_download_during_build(self):
        modules = self.manifest["modules"]
        self.assertEqual(modules[0], "python3-deps.json")  # Pinned wheels first
        self.assertEqual(self.app_module()["sources"], [{"type": "dir", "path": "../.."}])
        deps = json.loads((MANIFEST.parent / "python3-deps.json").read_text(encoding="utf-8"))
        everything = [m for m in modules if isinstance(m, dict)] + [deps]
        for module in everything:
            commands = "\n".join(module.get("build-commands", []))
            for fetch in ("curl ", "wget ", "pip install -U", "pip3 install -U"):
                self.assertNotIn(fetch, commands, module["name"])
            if "pip3 install" in commands:
                self.assertIn("--no-index", commands, module["name"])
            for source in module["sources"]:
                if source["type"] == "file":
                    self.assertRegex(source.get("sha256", ""), r"^[0-9a-f]{64}$", source)
                elif source["type"] == "git":
                    self.assertRegex(source.get("commit", ""), r"^[0-9a-f]{40}$", source)
                else:
                    self.assertEqual(source, {"type": "dir", "path": "../.."})

    def test_ffmpeg_is_built_with_the_encoders_smoothcast_uses(self):
        ffmpeg = next(m for m in self.manifest["modules"]
                      if isinstance(m, dict) and m["name"] == "ffmpeg")
        for flag in ("--enable-gpl", "--enable-libx264", "--enable-vaapi", "--enable-ffplay"):
            self.assertIn(flag, ffmpeg["config-opts"])

    def test_ci_builds_the_manifest(self):
        workflow = (ROOT / ".github/workflows/flatpak.yml").read_text(encoding="utf-8")
        self.assertIn(f"packaging/flatpak/{APP}.json", workflow)
        self.assertIn("--command=smoothcast", workflow)

    def test_desktop_identity_and_icon_are_included(self):
        config = ConfigParser(interpolation=None)
        config.read(DESKTOP, encoding="utf-8")
        desk = config["Desktop Entry"]
        self.assertEqual(desk["Exec"], "smoothcast")
        self.assertEqual(desk["Icon"], APP)
        self.assertEqual(desk["StartupWMClass"], "local.cast-control")
        self.assertEqual(desk["Terminal"], "false")
        commands = "\n".join(self.app_module()["build-commands"])
        self.assertIn(f"/app/share/applications/{APP}.desktop", commands)
        self.assertIn(f"/app/share/icons/hicolor/128x128/apps/{APP}.png", commands)


if __name__ == "__main__":
    unittest.main()
