import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pseudo_locale as pl


def test_accents_pads_and_brackets():
    out = pl.pseudo("Play on TV")
    assert out.startswith("[") and out.endswith("]") and "Plàÿ õñ TV" in out
    assert len(out) > len("Play on TV") * 1.4


def test_placeholders_survive_so_formatting_still_works():
    out = pl.pseudo("Casting %s to %(room)s: {count} left, 100%%")
    assert out.replace("~", "").count("%s") == 1 and "%(room)s" in out and "{count}" in out and "%%" in out
    assert (pl.pseudo("Hello %s") % "x").startswith("[Héllõ x")


def test_edge_cases_and_rtl():
    assert pl.pseudo("") == "" and pl.pseudo(None) == ""
    assert pl.rtl("abc") == "‫abc‬" and pl.rtl(5) == ""
