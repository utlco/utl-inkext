"""Test SVG document unit scaling and conversion."""
from __future__ import annotations

import pathlib

from inkext import geomsvg, inksvg, svg

_TEST_DIR = pathlib.Path(__file__).parent

def test_units() -> None:
    with _TEST_DIR / 'units/4inx5in-v4x5.svg' as f:
        svg = inksvg.InkscapeSVGContext.parse(f)

    assert svg.doc_units == 'in'
    assert svg.view_width == 4
    assert svg.view_height == 5
    assert svg.view_scale == 1
    assert svg.viewbox == [0, 0, 4, 5]
    assert svg.get_document_size() == (4, 5)

    assert svg.unit2uu('1in') == 1
    assert svg.unit2uu('1px') ==  1 / 96
    assert svg.unit2uu('1') ==  1
    assert svg.unit2uu(2) ==  2

    rect_node = svg.get_node_by_id('rect1')
    assert rect_node is not None
    shapes = geomsvg.svg_element_to_geometry(rect_node)
    assert shapes
    poly = shapes[0]
    assert len(poly) == 4
    assert poly[0].length() == 2

    with _TEST_DIR / 'units/4inx5in-v8x10.svg' as f:
        svg = inksvg.InkscapeSVGContext.parse(f)

    assert svg.doc_units == 'in'
    assert svg.view_width == 4
    assert svg.view_height == 5
    assert svg.view_scale == 2
    assert svg.viewbox == [0, 0, 8, 10]
    assert svg.get_document_size() == (4, 5)

    assert svg.unit2uu('1in') == 1
    assert svg.unit2uu('1px') ==  1 / 96
    assert svg.unit2uu('1') ==  1
    assert svg.unit2uu(2) ==  2

    rect_node = svg.get_node_by_id('rect1')
    assert rect_node is not None
    shapes = geomsvg.svg_element_to_geometry(rect_node)
    assert shapes
    poly = shapes[0]
    assert len(poly) == 4
    assert poly[0].length() == 2

