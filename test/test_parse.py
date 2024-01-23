
import itertools

from geom2d import polyline
from inkext import geomsvg

TOLERANCE = 1e-6
POLY1 = (
    'M 2.86579 7.19138 '
    'L 2.60321 5.60556 '
    'L 2.66237 5.80965 '
    'L 2.66237 5.6006 '
    'L 2.75099 5.96077 '
    'L 2.89142 5.55078 '
    'L 2.85855 6.4492 '
    'L 3.43943 6.91374 '
    'L 4.4335 6.14409 '
    'L 3.50829 7.40838 '
    'L 4.81146 7.12855 '
    'L 3.43943 8.18852 '
    'L 3.43943 8.42778 '
    'L 3.25346 8.03314 '
    'L 2.82143 7.93781 '
    'L 3.22212 7.68965 '
    'L 1.74289 7.45716 '
    'L 2.95283 7.5525 '
    'Z'
)

# Inkscape oddly starts the path from last point when 
# reversing a path, which inserts a zero-length segment
# on closed polylines.
POLY1_REVERSED = (
    'm 2.86579,7.19138 '
    'v 0 '
    'L 2.95283,7.5525 1.74289,7.45716 3.22212,7.68965 2.82143,7.93781 '
    '3.25346,8.03314 3.43943,8.42778 '
    'V 8.18852 '
    'L 4.81146,7.12855 3.50829,7.40838 4.4335,6.14409 3.43943,6.91374 '
    '2.85855,6.4492 2.89142,5.55078 2.75099,5.96077 2.66237,5.6006 '
    'V 5.80965 '
    'L 2.60321,5.60556 2.86579,7.19138'
)

def test_parse_poly():
    paths1 = geomsvg.parse_path_geom(POLY1)
    paths2 = geomsvg.parse_path_geom(POLY1_REVERSED)

    assert len(paths1) == 1
    assert len(paths2) == 1
    assert len(paths1[0]) == len(paths2[0])

    poly1 = list(polyline.polypath_to_polyline(paths1[0]))
    poly2 = list(polyline.polypath_to_polyline(paths2[0]))
    poly2.reverse()
    #_prcmp(poly1, poly2)

    assert poly1 == poly2


def _prcmp(path1, path2):
    # Compare paths for debugging...
    for a, b in itertools.zip_longest(path1, path2):
        print(a, b)
