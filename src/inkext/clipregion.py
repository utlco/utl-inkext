"""Simple rectangular or circular clip region."""

from __future__ import annotations

from typing import TYPE_CHECKING

import geom2d
from geom2d import box, ellipse

if TYPE_CHECKING:
    from geom2d.point import TPoint


class SimpleClipRegion:  # (NamedTuple):
    """Simple rectangular or circular clipping region."""

    # height: float
    # width: float
    # radius: float
    # center: float

    _clip_region: box.Box | ellipse.Ellipse

    def __init__(
        self,
        doc_size: tuple[float, float],
        margins: tuple[float, float, float, float] | None = None,
        clip_to_circle: bool = False,
    ) -> None:
        """Create a rectangular or circular clipping region.

        Args:
            doc_size: Document (width, height).
            margins: Clip margins in CSS clockwise order
                (top, right, bottom, left).
            clip_to_circle: Create a circular clip region
                with a radius of the min(w, h) of the clip rect.
        """
        if margins:
            m_top, m_right, m_bottom, m_left = margins
            clip_rect = geom2d.Box(
                geom2d.P(m_left, m_top),
                geom2d.P(doc_size) - geom2d.P(m_right, m_bottom),
            )
        else:
            clip_rect = geom2d.Box(geom2d.P(0, 0), doc_size)

        if clip_to_circle:
            radius = min(clip_rect.width, clip_rect.height) / 2
            self._clip_region = geom2d.Ellipse(clip_rect.center, radius, radius)

        self._clip_region = clip_rect

    def point_inside(self, p: TPoint) -> bool:
        """Return true of the point is inside the clip region."""
        return self._clip_region.point_inside(p)

    # def clip_polyline(
    #    self, polyline: Sequence[TPoint]
    # ) -> list[Sequence[TPoint]]:
    #    """Clip a polyline by this clip region."""
    #    for p1, p2 in itertools.pairwise(polyline):
    #        geom2d.Line(p1, p2)

    @property
    def height(self) -> float:
        """Clip region height."""
        if isinstance(self._clip_region, ellipse.Ellipse):
            return self._clip_region.ry * 2
        return self._clip_region.height

    @property
    def width(self) -> float:
        """Clip region width."""
        if isinstance(self._clip_region, ellipse.Ellipse):
            return self._clip_region.rx * 2
        return self._clip_region.width

    @property
    def radius(self) -> float:
        """The radius of a circle that fits within the clip region."""
        if isinstance(self._clip_region, ellipse.Ellipse):
            return min(self._clip_region.rx, self._clip_region.ry)
        return min(self._clip_region.width / 2, self._clip_region.height / 2)

    @property
    def center(self) -> geom2d.P:
        """Return center point of clip region."""
        return self._clip_region.center
