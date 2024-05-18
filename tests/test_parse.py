"""Test SVG parsing and arc/ellipse calculations."""
from __future__ import annotations

import itertools
import math
import pathlib

import geom2d
import geom2d.arc
from geom2d import const, polyline, transform2d
from inkext import geomsvg, inksvg, svg

# ruff: noqa: T201

TESTDIR = pathlib.Path(__file__).parent
ARC_FILE = TESTDIR / 'files/ellipse-path.svg'

POLY1 = """
M 2.86579 7.19138
L 2.60321 5.60556
L 2.66237 5.80965
L 2.66237 5.6006
L 2.75099 5.96077
L 2.89142 5.55078
L 2.85855 6.4492
L 3.43943 6.91374
L 4.4335 6.14409
L 3.50829 7.40838
L 4.81146 7.12855
L 3.43943 8.18852
L 3.43943 8.42778
L 3.25346 8.03314
L 2.82143 7.93781
L 3.22212 7.68965
L 1.74289 7.45716
L 2.95283 7.5525
Z
"""
POLY1_LEN = 18

# Same polyline but reversed using Inkscape.
# Inkscape oddly starts the path from last point when
# reversing a path, which inserts a zero-length segment
# on closed polylines.
# The zero-length segment will be skipped during parsing.
POLY1_REVERSED = """
m 2.86579,7.19138
v 0
L 2.95283,7.5525 1.74289,7.45716 3.22212,7.68965 2.82143,7.93781
3.25346,8.03314 3.43943,8.42778
V 8.18852
L 4.81146,7.12855 3.50829,7.40838 4.4335,6.14409 3.43943,6.91374
2.85855,6.4492 2.89142,5.55078 2.75099,5.96077 2.66237,5.6006
V 5.80965
L 2.60321,5.60556 2.86579,7.19138
"""

ARC_1_PATH = """
M -47.255922,-6.9329234
A 47.76178,47.76178 0 0 1 -6.8672278,-47.265514
  47.76178,47.76178 0 0 1 43.329158,-20.094071
L 0,0
Z
"""

ARC_2_PATH = """
M 0.104166666667 3.28125
L 1.145833333333 2.239583333333
A 0.375 0.625 0 0 1 1.569895833333 1.773854166667
L 1.797395833333 1.588020833333
A 0.31341035,0.52235058 -45 0 1 2.240625,1.1447917
L 3.28125 0.104166666667
"""

# 2nd arc is pathological
ARC_3_PATH = """
M 1.038748,4.8874693 2.0804146,3.8458027
A 0.4,0.4 0 0 1 2.5044771,3.3800735
l 0.2275,-0.1858333
A 0.35,0.35 0 1 0 3.1752063,2.751011
l 1.040625,-1.040625
"""

# Slightly too small radii - tests W3C fix
ARC_4_PATH = """
M 1.038748,4.8874693 2.0804146,3.8458027
A 0.4,0.4 0 0 1 2.5044771,3.3800735
l 0.2275,-0.1858333
A 0.3,0.3 0 1 0 3.1752063,2.751011
l 1.040625,-1.040625
"""

ARC_5_PATH = """
M 1.276665,6.4936886 2.3183316,5.452022
A 0.4,0.4 0 0 1 2.7423941,4.9862928
l 0.2275,-0.1858333
A 0.31341037,0.31341037 0 1 0 3.4131233,4.3572303
l 1.040625,-1.040625
"""
ARC_5 = geom2d.arc.Arc(
    (2.96989410, 4.80045950),
    (3.41312330, 4.35723030),
    0.31341037, -3.14159265,
    (3.19150870, 4.57884490)
)

SUBPATH1 = """
M -6.5119484,4.1542968
A 1.5655915,0.67857802 0 0 1 -7.7395344,4.7252119
  1.5655915,0.67857802 0 0 1 -9.3946323,4.4179264
  1.5655915,0.67857802 0 0 1 -9.28809,3.6388783
  1.5655915,0.67857802 0 0 1 -7.560828,3.418493

m -3.033287,-0.5806776
a 1.7518641,0.74394315 9.41528 0 1 0.703789,-0.808342
  1.7518641,0.74394315 9.41528 0 1 2.1786133,0.417063
  1.7518641,0.74394315 9.41528 0 1 0.1508849,0.9719566
"""

S = """
  <path
     style="fill:none;fill-opacity:0.44315;stroke:#ff0d0d;stroke-width:0.0119366;stroke-dasharray:none;stroke-opacity:1"
     id="path3439"
     sodipodi:type="arc"
     sodipodi:cx="8.2670279"
     sodipodi:cy="5.1745839"
     sodipodi:rx="0.63392878"
     sodipodi:ry="1.5572873"
     sodipodi:start="6.2813733"
     sodipodi:end="5.2926958"
     sodipodi:arc-type="slice"
     d="M 8.9009556,5.1717621 A 0.63392878,1.5572873 0 0 1 8.4232386,6.6838506 0.63392878,1.5572873 0 0 1 7.7095373,5.9159212 0.63392878,1.5572873 0 0 1 7.8380254,4.0280688 0.63392878,1.5572873 0 0 1 8.6145987,3.8722331 L 8.2670279,5.1745839 Z"
     transform="matrix(0.6920136,0.72188446,-0.7961769,0.60506392,0,0)" />
"""

def test_parse_poly() -> None:
    """Test parsing a polyline and its reverse."""
    paths1 = geomsvg.parse_path_geom(POLY1)
    paths2 = geomsvg.parse_path_geom(POLY1_REVERSED)

    assert len(paths1) == 1  # no subpaths
    assert len(paths2) == 1
    assert len(paths1[0]) == POLY1_LEN
    assert len(paths1[0]) == len(paths2[0])

    poly1 = list(polyline.polypath_to_polyline(paths1[0]))
    poly2 = list(polyline.polypath_to_polyline(paths2[0]))
    poly2.reverse()
    # _prcmp(poly1, poly2)

    assert poly1 == poly2


def test_parse_arc() -> None:
    """Test paths with ellipses and arcs."""
    print('ARC_1')
    path = geomsvg.parse_path_geom(ARC_1_PATH)[0]
    assert isinstance(path[0], geom2d.arc.Arc)
    print(f'ARC_1 = {path[0]!r}')

    print('ARC_2')
    path = geomsvg.parse_path_geom(ARC_2_PATH)[0]
    assert isinstance(path[0], geom2d.line.Line)
    assert isinstance(path[1], geom2d.bezier.CubicBezier)
    assert isinstance(path[2], geom2d.line.Line)
    assert isinstance(path[3], geom2d.bezier.CubicBezier)
    assert isinstance(path[-1], geom2d.line.Line)

    print('ARC_2 no ellipse-bezier')
    path = geomsvg.parse_path_geom(ARC_2_PATH, ellipse_to_bezier=False)[0]
    assert isinstance(path[1], geom2d.ellipse.EllipticalArc)
    print(f'ARC_2_1 = {path[1]!r}')
    assert isinstance(path[3], geom2d.ellipse.EllipticalArc)
    print(f'ARC_2_2 = {path[3]!r}')

    # Test round trip.
    svgpath = svg.geompath_to_svgpath(path)
    path2 = geomsvg.parse_path_geom(svgpath, ellipse_to_bezier=False)[0]
    for seg1, seg2 in zip(path, path2):
        assert seg1 == seg2

    print('ARC_3')
    path = geomsvg.parse_path_geom(ARC_3_PATH)[0]
    assert isinstance(path[1], geom2d.arc.Arc)
    print(f'ARC_3_1 = {path[1]!r}')
    assert isinstance(path[3], geom2d.arc.Arc)
    print(f'ARC_3_2 = {path[3]!r}')

    print('ARC_4')
    path = geomsvg.parse_path_geom(ARC_4_PATH)[0]
    assert isinstance(path[1], geom2d.arc.Arc)
    print(f'ARC_4_1 = {path[1]!r}')
    assert isinstance(path[3], geom2d.arc.Arc)
    print(f'ARC_4_2 = {path[3]!r}')

    print('ARC_5')
    path = geomsvg.parse_path_geom(ARC_5_PATH)[0]
    # print(svg.geompath_to_svgpath(path))
    assert isinstance(path[1], geom2d.arc.Arc)
    print(f'ARC_5_1 = {path[1]!r}')
    assert isinstance(path[3], geom2d.arc.Arc)
    print(f'ARC_5_2 = {path[3]!r}')
    arc = path[3]
    # Regression test... make sure it looks like it did the last time.
    assert arc == ARC_5

    print('SUBPATH1')
    path = geomsvg.parse_path_geom(SUBPATH1)[0]
    # Test round trip.
    svgpath = svg.geompath_to_svgpath(path)
    path2 = geomsvg.parse_path_geom(svgpath, ellipse_to_bezier=False)[0]
    for seg1, seg2 in zip(path, path2):
        assert seg1 == seg2


def test_parse_file_arc() -> None:
    """Test parsing an Inkscape SVG document containing paths with arcs."""
    with ARC_FILE.open() as f:
        svg = inksvg.InkscapeSVGContext.parse(f)

    svg_elements = svg.get_shape_elements()
    assert svg_elements

    flip_transform = transform2d.matrix_scale_translate(
        1.0, -1.0, 0.0, svg.get_document_size()[1]
    )

    path_list = geomsvg.svg_to_geometry(svg_elements, flip_transform)
    assert path_list


def _prcmp(path1, path2) -> None:
    # Visually compare paths for debugging...
    for a, b in itertools.zip_longest(path1, path2):
        print(a, b)
