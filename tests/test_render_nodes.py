import render_nodes


def test_lowest_render_node_first_and_ignores_others(tmp_path):
    for name in ("renderD129", "renderD128", "card0", "renderDx", "renderD130"):
        (tmp_path / name).write_text("")
    assert [p.rsplit("/", 1)[1] for p in render_nodes.render_nodes(str(tmp_path))] == [
        "renderD128", "renderD129", "renderD130"]


def test_only_secondary_node_is_used(tmp_path):
    (tmp_path / "renderD129").write_text("")
    assert render_nodes.preferred(str(tmp_path)).endswith("renderD129")


def test_missing_directory_keeps_the_historical_default(tmp_path):
    assert render_nodes.preferred(str(tmp_path / "none")) == render_nodes.FALLBACK
