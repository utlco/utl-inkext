"""Methods for converting SVG shape elements to geometry objects."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Union

import geom2d
from geom2d import transform2d

from . import svg

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from geom2d.transform2d import TMatrix
    from typing_extensions import TypeAlias

    from .svg import TElement

logger = logging.getLogger(__name__)

TGeom: TypeAlias = Union[
    geom2d.Line,
    geom2d.Arc,
    geom2d.Ellipse,
    geom2d.EllipticalArc,
    geom2d.CubicBezier,
]

TPathGeom: TypeAlias = Union[
    geom2d.Line,
    geom2d.Arc,
    geom2d.CubicBezier,
]


def path_to_polypath(path: Iterable[TPathGeom]) -> Iterator[geom2d.Line]:
    """Convert a path to a polypath (sequence of Lines).

    Arc and CubicBezier segments are converted to simple
    Line segments using the end points.

    Args:
        path: An iterable of path segments.

    Returns:
        A polypath as an iterable of Line segments.
    """
    for segment in path:
        if isinstance(segment, geom2d.Line):
            yield segment
        else:
            # TODO: Approximate Arc and CubicBeziers with Lines...
            yield geom2d.Line(segment.p1, segment.p2)


def path_to_polyline(path: Iterable[TPathGeom]) -> Iterator[geom2d.P]:
    """Convert a path to a polypath (sequence of Lines).

    Arc and CubicBezier segments are converted to simple
    Line segments using the end points.

    Args:
        path: An iterable of path segments.

    Returns:
        A polypath as an iterable of Line segments.
    """
    segment: TPathGeom
    for segment in path:
        yield segment.p1
    yield segment.p2


def svg_to_geometry(
    svg_elements: Iterable[tuple[TElement, TMatrix | None]],
    parent_transform: TMatrix | None = None,
) -> list[Sequence[TPathGeom]]:
    """Convert the SVG shape elements to geometry objects.

    Converts SVG shape elements to Line, Arc, and/or CubicBezier segments,
    and applies node/parent transforms.
    The coordinates of the segments will be absolute with
    respect to the parent container.

    Args:
        svg_elements: An iterable collection of 2-tuples consisting of
            SVG Element node and transform matrix.
        parent_transform: An optional parent transform to apply to all
            nodes. Default is None.

    Returns:
        A list of paths, where a path is a list of one or more
        segments made of Line, Arc, or CubicBezier objects.
    """
    return svg_to_geometry_el(  # type: ignore [return-value]
        svg_elements,
        parent_transform=parent_transform,
        ellipse_to_bezier=True,
    )
    # return typing.cast(
    #    list[Sequence[geom2d.Line | geom2d.Arc | geom2d.CubicBezier]], paths
    # )


def svg_to_geometry_el(
    svg_elements: Iterable[tuple[TElement, TMatrix | None]],
    parent_transform: TMatrix | None = None,
    ellipse_to_bezier: bool = True,
) -> list[Sequence[TGeom]]:
    """Convert the SVG shape elements to geometry objects.

    Converts SVG shape elements to Line, Arc, and/or CubicBezier segments,
    and applies node/parent transforms.
    The coordinates of the segments will be absolute with
    respect to the parent container.

    Args:
        svg_elements: An iterable collection of 2-tuples consisting of
            SVG Element node and transform matrix.
        parent_transform: An optional parent transform to apply to all
            nodes. Default is None.
        ellipse_to_bezier: Convert ellipses and elliptical arcs to bezier curves
            if True. Default is True.

    Returns:
        A list of paths, where a path is a list of one or more
        segments made of Line, Arc, or CubicBezier objects.
    """
    path_list: list[Sequence[TGeom]] = []
    for element, element_transform in svg_elements:
        # logger.debug('element: %s %s', element.get('id'), element_transform)
        transformed_paths = svg_element_to_geometry(
            element,
            element_transform=element_transform,
            parent_transform=parent_transform,
            ellipse_to_bezier=ellipse_to_bezier,
        )
        if transformed_paths:
            path_list.extend(transformed_paths)
    return path_list


def svg_element_to_geometry(  # noqa: PLR0912
    element: TElement,
    element_transform: TMatrix | None = None,
    parent_transform: TMatrix | None = None,
    ellipse_to_bezier: bool = True,
) -> Sequence[Sequence[TGeom]]:
    """Convert the SVG shape element to subpath.

    Creates a list of one or more sub-paths consisting of a list of
    Line, Arc, and/or CubicBezier segments, and applies node/parent transforms.
    The coordinates of the segments will be absolute with
    respect to the parent container.

    Args:
        element: An SVG Element shape node.
        element_transform: An optional transform to apply to the element.
            Default is None.
        parent_transform: An optional parent transform to apply to the element.
            Default is None.
        ellipse_to_bezier: Convert ellipses and elliptical arcs to bezier curves
            if True. Default is True.

    Returns:
        A list of zero or more sub-paths.
        A sub-path being a list of zero or more Line, Arc, Ellipse,
        EllipticalArc, or CubicBezier objects.
    """
    # Convert the element to a list of subpaths
    subpath_list: list[Sequence[TGeom]] = []
    tag = svg.strip_ns(element.tag)  # tag stripped of namespace part
    if tag == 'path':
        d = element.get('d')
        if d is not None and d:
            subpath_list = parse_path_geom(
                d, ellipse_to_bezier=ellipse_to_bezier
            )
    else:
        subpath: Sequence[TGeom]
        if tag == 'line':
            subpath = convert_line(element)
        elif tag == 'ellipse':
            ellipse = convert_ellipse(element)
            if ellipse_to_bezier:
                subpath = geom2d.bezier.bezier_ellipse(ellipse)
            else:
                subpath = [
                    ellipse,
                ]
        elif tag == 'rect':
            subpath = convert_rect(element)
        elif tag == 'circle':
            subpath = convert_circle(element)
        elif tag == 'polyline':
            subpath = convert_polyline(element)
        elif tag == 'polygon':
            subpath = convert_polygon(element)
        else:
            raise TypeError('Unrecognized SVG element.')
        if subpath:
            subpath_list = [
                subpath,
            ]

    if subpath_list:
        # Create a transform matrix that is composed of the
        # parent transform and the element transform
        # so that control points are in absolute coordinates.
        if not element_transform:
            element_transform = parent_transform
        elif parent_transform:
            element_transform = transform2d.compose_transform(
                parent_transform, element_transform
            )
        if element_transform:
            x_subpath_list = []
            for subpath in subpath_list:
                x_subpath = [
                    segment.transform(element_transform)
                    for segment in subpath
                    if segment.p1 != segment.p2
                ]
                # x_subpath = []
                # for segment in subpath:
                #    # Skip zero-length segments.
                #    if segment.p1 != segment.p2:
                #        x_subpath.append(segment.transform(element_transform))
                x_subpath_list.append(x_subpath)
            return x_subpath_list
    return subpath_list


def parse_path_geom(  # noqa: PLR0912
    path_data: str, ellipse_to_bezier: bool = True
) -> list[Sequence[TGeom]]:
    """Parse SVG path data and convert to geometry objects.

    Args:
        path_data: The `d` attribute value of an SVG path element.
        ellipse_to_bezier: Convert elliptical arcs to bezier curves
            if True. Default is False.

    Returns:
        A list of zero or more subpaths.
        A subpath being a list of zero or more Line, Arc, EllipticalArc,
        or CubicBezier objects.
    """
    subpath: list[TGeom] = []
    subpath_list: list[Sequence[TGeom]] = []
    p1 = geom2d.P(0.0, 0.0)
    for cmd, params in svg.parse_path(path_data):
        p2 = geom2d.P(params[-2], params[-1])
        if p1 == p2:
            # Ignore zero-length segments (coincindent points)
            continue
        if cmd == 'M':
            # Start of path or sub-path
            if subpath:
                subpath_list.append(subpath)
                subpath = []
        elif cmd == 'L':
            subpath.append(geom2d.Line(p1, p2))
        elif cmd == 'A':
            rx = params[0]
            ry = params[1]
            phi = params[2]
            large_arc = params[3]
            sweep_flag = params[4]
            if geom2d.is_zero(rx) or geom2d.is_zero(ry):
                subpath.append(geom2d.Line(p1, p2))
                continue
            elliptical_arc = geom2d.ellipse.EllipticalArc.from_endpoints(
                p1, p2, rx, ry, phi, large_arc, sweep_flag
            )
            if not elliptical_arc:
                # Parameters must be degenerate...
                # Try just making a line
                logger.debug('Degenerate arc: %s', path_data)
                subpath.append(geom2d.Line(p1, p2))
            elif elliptical_arc.is_circle():
                # If it's a circular arc then create an Arc using
                # the previously computed ellipse parameters.
                arc = geom2d.Arc(
                    p1,
                    p2,
                    elliptical_arc.rx,
                    elliptical_arc.sweep_angle,
                    center=elliptical_arc.center,
                )
                subpath.append(arc)
            elif ellipse_to_bezier:
                # Convert the elliptical arc to cubic Beziers
                subpath.extend(geom2d.bezier.bezier_ellipse(elliptical_arc))
            else:
                subpath.append(elliptical_arc)
        elif cmd == 'C':
            c1 = (params[0], params[1])
            c2 = (params[2], params[3])
            subpath.append(geom2d.bezier.CubicBezier(p1, c1, c2, p2))
        elif cmd == 'Q':
            c1 = (params[0], params[1])
            subpath.append(geom2d.bezier.CubicBezier.from_quadratic(p1, c1, p2))
        p1 = p2

    if subpath:
        subpath_list.append(subpath)

    return subpath_list


def convert_rect(
    element: TElement,
) -> list[geom2d.Line]:
    """Convert an SVG rect shape element to four geom2d.Line segments.

    Args:
        element: An SVG 'rect' element of the form
            <rect x='X' y='Y' width='W' height='H'/>

    Returns:
        A clockwise wound polygon as a list of four geom2d.Line segments.
    """
    # Convert to a clockwise wound polygon
    x1 = float(element.get('x', 0))
    y1 = float(element.get('y', 0))
    x2 = x1 + float(element.get('width', 0))
    y2 = y1 + float(element.get('height', 0))
    p1 = (x1, y1)
    p2 = (x1, y2)
    p3 = (x2, y2)
    p4 = (x2, y1)
    return [
        geom2d.Line(p1, p2),
        geom2d.Line(p2, p3),
        geom2d.Line(p3, p4),
        geom2d.Line(p4, p1),
    ]


def convert_line(element: TElement) -> list[geom2d.Line]:
    """Convert an SVG line shape element to a geom2d.Line.

    Args:
        element: An SVG 'line' element of the form:
           <line x1='X1' y1='Y1' x2='X2' y2='Y2/>

    Returns:
       A line segment: geom2d.Line((x1, y1), (x2, y2))
    """
    x1 = float(element.get('x1', 0))
    y1 = float(element.get('y1', 0))
    x2 = float(element.get('x2', 0))
    y2 = float(element.get('y2', 0))
    return [
        geom2d.Line((x1, y1), (x2, y2)),
    ]


def convert_circle(
    element: TElement,
) -> tuple[geom2d.Arc, geom2d.Arc, geom2d.Arc, geom2d.Arc]:
    """Convert an SVG circle shape element to four circular arc segments.

    Args:
        element: An SVG 'circle' element of the form:
           <circle r='RX' cx='X' cy='Y'/>
    Returns:
       A counter-clockwise wound list of four circular geom2d.Arc segments.
    """
    # Convert to four arcs. CCW winding.
    r = abs(float(element.get('r', 0)))
    cx = float(element.get('cx', 0))
    cy = float(element.get('cy', 0))
    center = (cx, cy)
    p1 = (cx + r, cy)
    p2 = (cx, cy + r)
    p3 = (cx - r, cy)
    p4 = (cx, cy - r)
    a1 = geom2d.Arc(p1, p2, r, math.pi / 2, center)
    a2 = geom2d.Arc(p2, p3, r, math.pi / 2, center)
    a3 = geom2d.Arc(p3, p4, r, math.pi / 2, center)
    a4 = geom2d.Arc(p4, p1, r, math.pi / 2, center)
    return (a1, a2, a3, a4)


def convert_ellipse(element: TElement) -> geom2d.Ellipse:
    """Convert an SVG ellipse shape element to a geom2d.Ellipse.

    Args:
        element: An SVG 'ellipse' element of the form:
            <ellipse rx='RX' ry='RY' cx='X' cy='Y'/>

    Returns:
       A geom2d.Ellipse.
    """
    rx = float(element.get('rx', 0))
    ry = float(element.get('ry', 0))
    cx = float(element.get('cx', 0))
    cy = float(element.get('cy', 0))
    return geom2d.ellipse.Ellipse((cx, cy), rx, ry)


def convert_polyline(element: TElement) -> list[geom2d.Line]:
    """Convert an SVG `polyline` shape element to a list of line segments.

    Args:
        element: An SVG 'polyline' element of the form:
            <polyline points='x1,y1 x2,y2 x3,y3 [...]'/>

    Returns:
       A list of geom2d.Line segments.
    """
    segments = []
    points = element.get('points', '').split()
    sx, sy = points[0].split(',')
    start_p = geom2d.P(float(sx), float(sy))
    prev_p = start_p
    for point in points[1:]:
        sx, sy = point.split(',')
        p = geom2d.P(float(sx), float(sy))
        segments.append(geom2d.Line(prev_p, p))
        prev_p = p
    return segments


def convert_polygon(element: TElement) -> list[geom2d.Line]:
    """Convert an SVG `polygon` shape element to a list line segments.

    Args:
        element: An SVG 'polygon' element of the form:
            <polygon points='x1,y1 x2,y2 x3,y3 [...]'/>

    Returns:
       A list of geom2d.Line segments. The polygon will be closed.
    """
    segments = convert_polyline(element)
    # Close the polygon if not already so
    if len(segments) > 1 and segments[-1] != segments[0]:
        segments.append(geom2d.Line(segments[-1].p2, segments[0].p1))
    return segments


# def polypath_to_svg_path(polypath: Sequence[TGeom]) -> str:
#    """Convert a polypath to an SVG 'D' path.
#
#    Converts a list of connected Lines, Arcs, CubicBeziers
#    to an SVG 'd' path string.
#    """
#    pathparts: list[str] = []
#    for segment in polypath:
#        if isinstance(segment, geom2d.Ellipse):
#            raise TypeError('Ellipse in polypath.')
#        if not pathparts:
#            pathparts.append(f'M {segment.p1.x} {segment.p1.y}')
#        pathparts.append(segment.to_svg_path(mpart=False))
#    return ' '.join(pathparts)
