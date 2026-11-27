"""Portable frozen licence checks; no native executable or GUI required."""
from pathlib import Path
import importlib.util
import tempfile
import unittest


def load_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "verify_frozen_artifact.py"
    spec = importlib.util.spec_from_file_location("verify_frozen_artifact", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrozenLegalTests(unittest.TestCase):
    def test_complete_missing_and_modified_legal_files(self):
        verifier = load_verifier()
        for mac in (False, True):
            with self.subTest(mac=mac), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "packaging").mkdir()
                (root / "LICENSE").write_bytes(b"GPL fixture")
                (root / "packaging" / "SmoothCast-NOTICE.txt").write_bytes(b"Copyright fixture")
                if mac:
                    exe = root / "SmoothCast.app" / "Contents" / "MacOS" / "SmoothCastCLI"
                    legal = exe.parent.parent / "Resources" / "legal"
                else:
                    exe = root / "SmoothCast" / "SmoothCastCLI.exe"
                    legal = exe.parent / "_internal" / "legal"
                legal.mkdir(parents=True)
                (legal / "LICENSE").write_bytes(b"GPL fixture")
                (legal / "SmoothCast-NOTICE.txt").write_bytes(b"Copyright fixture")
                verifier.check_project_legal(exe, root)
                for name in ("LICENSE", "SmoothCast-NOTICE.txt"):
                    path = legal / name
                    original = path.read_bytes()
                    for changed in (None, b"wrong"):
                        with self.subTest(name=name, changed=changed):
                            if changed is None:
                                path.unlink()
                            else:
                                path.write_bytes(changed)
                            with self.assertRaisesRegex(RuntimeError, name):
                                verifier.check_project_legal(exe, root)
                            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
