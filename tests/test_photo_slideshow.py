import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import photo_slideshow as ps


def exif(orient=1, gps=False, end="<"):
    e = end
    ifd = struct.pack(e + "H", 2 if gps else 1) + struct.pack(e + "HHII", 0x0112, 3, 1, orient) .replace(struct.pack(e + "I", orient), struct.pack(e + "H", orient) + b"\0\0")
    if gps:
        ifd += struct.pack(e + "HHII", 0x8825, 4, 1, 0)
    ifd += b"\0\0\0\0"
    tiff = (b"II" if e == "<" else b"MM") + struct.pack(e + "H", 42) + struct.pack(e + "I", 8) + ifd
    body = b"Exif\0\0" + tiff + (b"GPSLatitude 51.5N" if gps else b"")
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def jpeg(**kw):
    com = b"\xff\xfe" + struct.pack(">H", 6) + b"hi!!"
    dqt = b"\xff\xdb" + struct.pack(">H", 4) + b"\x00\x01"
    return b"\xff\xd8" + exif(**kw) + com + dqt + b"\xff\xda\x00\x02" + b"IMAGEDATA" + b"\xff\xd9"


def test_orientation_all_eight_both_endians_and_filters():
    for v in range(1, 9):
        for end in "<>":
            assert ps.orientation(jpeg(orient=v, end=end)) == v
    assert set(ps.ORIENT_FILTER) == set(range(1, 9)) and ps.ORIENT_FILTER[1] == "" and ps.ORIENT_FILTER[6] == "transpose=1"
    assert ps.orientation(b"notjpeg") == 1 and ps.orientation(b"\xff\xd8\xff\xe1\x00") == 1 and ps.orientation(jpeg(orient=9)) == 1


def test_gps_and_exif_removed_image_data_preserved():
    src = jpeg(orient=6, gps=True)
    assert b"GPS" in src and ps.contains_gps(src)
    out = ps.strip_metadata(src)
    assert b"GPS" not in out and b"Exif" not in out and b"hi!!" not in out and not ps.contains_gps(out)
    assert out.startswith(b"\xff\xd8") and b"\xff\xdb" in out and out.endswith(b"IMAGEDATA\xff\xd9")
    assert ps.orientation(out) == 1                      # caller must read orientation BEFORE stripping
    assert ps.strip_metadata(b"\x89PNG....") == b"\x89PNG...." and ps.strip_metadata(b"\xff\xd8\xff") is not None


def test_plan_clamps_caps_shuffles_deterministically_and_counts_skips():
    names = [f"{i}.jpg" for i in range(310)] + ["doc.pdf", "x.heic"]
    p = ps.plan(names, 99); assert len(p["items"]) == 300 and p["seconds"] == 15 and p["skipped"] == 12 and p["total_s"] == 4500
    assert ps.plan(["a.jpg"], 1)["seconds"] == 3 and ps.plan(["a.jpg"], float("nan"))["seconds"] == 6
    assert ps.plan(["x.HEIC"], 6, decodable_heic=True)["items"] == ["x.HEIC"]
    a = ps.plan(names[:50], 6, True, 7); assert a == ps.plan(names[:50], 6, True, 7) and a["items"] != names[:50] and sorted(a["items"]) == sorted(names[:50])


def test_concat_list_repeats_last_and_escapes_quotes():
    s = ps.concat_list(["/t/a.jpg", "/t/it's.jpg"], 6)
    assert s.count("duration 6") == 2 and s.rstrip().endswith("file '/t/it'\\''s.jpg'") and ps.concat_list([], 6) == "\n"


def test_ephemeral_end_keep_startup_crash_cleanup(tmp_path):
    e = ps.Ephemeral(tmp_path)
    p = e.save("s1", "a.jpg", jpeg(gps=True)); assert p and b"GPS" not in p.read_bytes()
    assert e.save("s1", "evil.sh", b"x") is None and e.save("../../x", "a.png", b"png").parent.parent == tmp_path
    e.save("s2", "b.jpg", jpeg()); e.keep("s2"); e.save("s3", "c.jpg", jpeg())
    assert e.end("s1") and not (tmp_path / "s1").exists() and not e.end("s2") and (tmp_path / "s2").exists()
    # crash: s3 and the traversal dir were never ended
    assert ps.Ephemeral(tmp_path).cleanup_startup(live=set()) >= 2 and not (tmp_path / "s3").exists() and (tmp_path / "s2").exists()
    assert "removed from this computer" in ps.PRIVACY_NOTE
