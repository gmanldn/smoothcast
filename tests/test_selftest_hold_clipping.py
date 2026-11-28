"""#449: clipped_labels flags single-line labels wider than allocated, and only those (GTK-free fakes)."""
from __future__ import annotations

import selftest_hold


class FakeGtk:
    class Label:  # noqa: D106 - stand-in type used by isinstance()
        pass


class Layout:
    def __init__(self, width):
        self.width = width

    def get_pixel_size(self):
        return (self.width, 10)


def label(text, text_px, alloc_px, *, mapped=True, wrap=False, ellipsize=0):
    node = FakeGtk.Label()
    node.get_text = lambda: text
    node.get_mapped = lambda: mapped
    node.get_wrap = lambda: wrap
    node.get_ellipsize = lambda: ellipsize
    node.get_layout = lambda: Layout(text_px)
    node.get_allocated_width = lambda: alloc_px
    node.get_first_child = lambda: None
    node.get_next_sibling = lambda: None
    return node


def root_with(*labels):
    root = type("Root", (), {})()
    kids = list(labels)
    root.get_first_child = lambda: kids[0] if kids else None
    for i, kid in enumerate(kids):
        kid.get_next_sibling = (lambda j=i: kids[j + 1] if j + 1 < len(kids) else None)
    return root


def test_wider_than_allocation_is_clipped_and_counted():
    checked = []
    window = root_with(label("Cast to living room", 300, 120), label("OK", 20, 40))
    assert selftest_hold.clipped_labels(window, FakeGtk, checked) == ["Cast to living room"]
    assert len(checked) == 2


def test_fitting_wrapping_ellipsized_and_hidden_labels_are_not_flagged():
    window = root_with(
        label("fits", 50, 60), label("within slack", 61, 60),
        label("wraps", 500, 60, wrap=True), label("ellipsizes", 500, 60, ellipsize=3),
        label("hidden", 500, 60, mapped=False))
    assert selftest_hold.clipped_labels(window, FakeGtk) == []
