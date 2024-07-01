"""A simple library for SVG output."""

from __future__ import annotations

import logging
import math
import random
import re
import string
import sys
from typing import TYPE_CHECKING, TextIO

# from xml.etree import ElementTree as etree
import geom2d
from geom2d import TPoint, arc, transform2d
from lxml import etree

from . import css

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from geom2d.transform2d import TMatrix
    from typing_extensions import Self, TypeAlias

# For debugging...
logger = logging.getLogger(__name__)

# : SVG Namespaces
SVG_NS = {
    '': 'http://www.w3.org/2000/svg',
    'svg': 'http://www.w3.org/2000/svg',
    'xlink': 'http://www.w3.org/1999/xlink',
    'xml': 'http://www.w3.org/XML/1998/namespace',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'cc': 'http://creativecommons.org/ns#',
    'dc': 'http://purl.org/dc/elements/1.1/',
}


PPI = 96.0  # Pixels per inch per https://www.w3.org/TR/css-values-3/#px

# A dictionary of supported css unit to px conversion factors
# See http://www.w3.org/TR/SVG/coords.html#Units
UNIT_CONV = {
    'cm': PPI / 2.54,
    'mm': PPI / (2.54 * 10),
    'Q': PPI / (2.54 * 40),
    'in': PPI,
    'pc': PPI / 6,
    'pt': PPI / 72,
    'px': 1,
    # These are relative to the current font size which is unknown
    # so just assume 12pt, and uniform square font (?)
    'em': 16,
    'ex': 16,
    'ch': 16,
    'rem': 16,
    # These are non-standard
    'm': PPI / 0.0254,
    'ft': PPI * 12,
    'yd': PPI * 36,
}

TDocument: TypeAlias = (
    etree._ElementTree  # noqa: SLF001 pylint: disable=protected-access
)
TElement: TypeAlias = (
    etree._Element  # noqa: SLF001 pylint: disable=protected-access
)


class SVGError(Exception):
    """SVG etree error."""


_RE_CSS_UNIT = re.compile(f'({"|".join(UNIT_CONV.keys())})$')
_RE_FLOAT = re.compile(
    r'(([-+]?[0-9]+(\.[0-9]*)?|[-+]?\.[0-9]+)([eE][-+]?[0-9]+)?)'
)


def add_ns(tag: str, ns_map: dict[str, str], ns: str) -> str:
    """Prepend a mapped namespace to `tag`."""
    uri = ns_map[ns]
    return f'{{{uri}}}{tag}'


def svg_ns(tag: str) -> str:
    """Shortcut to prepend SVG namespace to `tag`."""
    return add_ns(tag, SVG_NS, 'svg')


def xml_ns(tag: str) -> str:
    """Shortcut to prepend XML namespace to `tag`."""
    return add_ns(tag, SVG_NS, 'xml')


def xlink_ns(tag: str) -> str:
    """Shortcut to prepend xlink namespace to `tag`."""
    return add_ns(tag, SVG_NS, 'xlink')


def strip_ns(tag: str) -> str:
    """Strip the namespace part from the tag if any."""
    return tag.rpartition('}')[2]


class SVGContext:
    """SVG document context."""

    # Default floating point output precision.
    # Number of digits after the decimal point.
    # None means use repr(float)
    _DEFAULT_PRECISION = None

    # Pre-compiled RE for parsing SVG transform attribute value.
    _TRANSFORM_RE = re.compile(
        r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)\s*,?',
        re.IGNORECASE,
    )

    document: TDocument
    doc_units: str = 'px'
    docroot: TElement
    current_parent: TElement

    @classmethod
    def create_document(
        cls: type[Self],
        width: float,
        height: float,
        doc_id: str | None = None,
        doc_units: str = 'px',
    ) -> Self:
        """Create a minimal SVG document.

        Returns:
            An SVGContext
        """

        def floatystr(value: float) -> str:
            # Strip off trailing zeros from fixed point float string
            return f'{value:f}'.rstrip('0').rstrip('.')

        docroot = etree.Element(svg_ns('svg'), nsmap=SVG_NS)
        width_str = floatystr(width)
        height_str = floatystr(height)
        docroot.set('width', f'{width_str}{doc_units}')
        docroot.set('height', f'{height_str}{doc_units}')
        docroot.set('viewBox', f'0 0 {width_str} {height_str}')
        if doc_id is not None:
            docroot.set('id', doc_id)
        document = etree.ElementTree(docroot)
        return cls(document)

    @classmethod
    def parse(
        cls: type[Self], stream: TextIO | None = None, huge_tree: bool = True
    ) -> Self:
        """Parse an SVG file (or stdin) and return an SVGContext.

        Args:
            stream: The input stream to parse. If this is None
                stdin will be read by default.
            huge_tree: Disable security restrictions and
                support very deep trees.

        Returns:
            An SVGContext
        """
        parser = etree.XMLParser(huge_tree=huge_tree)
        if stream is None:
            stream = sys.stdin
        document = etree.parse(stream, parser=parser)
        return cls(document)

    def __init__(self, document: TDocument) -> None:
        """New SVG context.

        Args:
            document: An SVG ElementTree. The svg 'width' and 'height'
                attributes MUST be specified.
            doc_units: ViewBox width/height units
        """
        self.document = document
        self.docroot = document.getroot()
        # if hasattr(document, 'getroot'):
        #    # Assume ElementTree
        #    self.docroot = document.getroot()
        # else:
        #    # Assume Element
        #    self.docroot = document
        self.current_parent = self.docroot
        self.set_precision(self._DEFAULT_PRECISION)

        # For some background on SVG coordinate systems
        # and how Inkscape deals with units:
        # http://www.w3.org/TR/SVG/coords.html
        # http://wiki.inkscape.org/wiki/index.php/Units_In_Inkscape

        # Get viewport width and height in user units
        svg_width = self.docroot.get('width')
        svg_height = self.docroot.get('height')
        self.doc_units = scalar_unit(svg_width, default=scalar_unit(svg_height))
        viewport_width = self.unit_convert(svg_width, to_unit=self.doc_units)
        viewport_height = self.unit_convert(svg_height, to_unit=self.doc_units)

        # Get the viewBox to determine user units and root scale factor
        viewboxattr = self.docroot.get('viewBox')
        if viewboxattr is not None:
            p = re.compile(r'[,\s\t]+')
            viewbox = [float(value) for value in p.split(viewboxattr)]
        else:
            viewbox = [0, 0, viewport_width, viewport_height]
        viewbox_width = viewbox[2] - viewbox[0]
        viewbox_height = viewbox[3] - viewbox[1]

        # The viewBox can have a different size than the viewport
        # which causes the user agent to scale the SVG.
        # http://www.w3.org/TR/SVG/coords.html#ViewBoxAttribute
        # For this purpose we assume the aspect ratio is preserved
        # and that it's a degenerate case if not since it would be
        # difficult, if not impossible, to make a general scaling rule
        # for a scalar GUI value to user unit conversion.
        scale_width = viewbox_width / viewport_width
        scale_height = viewbox_height / viewport_height
        if not geom2d.float_eq(scale_width, scale_height):
            raise ValueError('viewBox aspect ratio does not match viewport.')

        self.view_width = viewbox_width
        self.view_height = viewbox_height
        self.view_scale = scale_width
        self.viewbox = viewbox

    def get_document_size(self) -> tuple[float, float]:
        """Return width and height of document in user units as a tuple (W, H)."""
        return (self.view_width, self.view_height)

    def unit2uu(
        self,
        value: str | float,
        from_unit: str | None = None,
    ) -> float:
        """Convert value to user (document) units.

        Convert a string/float that specifies a value in some source unit
        (ie '3mm' or '5in') to a float value in user units.
        The result will be scaled using the viewBox/viewport ratio
        assuming they have the same aspect ratio.

        SVG/Inkscape units and SVG viewBoxes can be confusing...
        See http://www.w3.org/TR/SVG/coords.html#ViewBoxAttribute
        and http://www.w3.org/TR/SVG/coords.html#Units
        and http://wiki.inkscape.org/wiki/index.php/Units_In_Inkscape.

        Args:
            value: A float value or a numeric string value with an optional
                unit identifier suffix (ie '3mm', '10pt, '5in'), or
                a float value.
                If the value is a float or the string does not have a
                unit suffix then `from_unit` will be used.
            from_unit: Optional string specifying the source units for
                the conversion. Default is doc units.
            to_unit: Optional string specifying the destination units for
                the conversion. Default is doc units.

        Returns:
            A float value or 0.0 if the string can't be parsed.
        """
        if not from_unit:
            from_unit = self.doc_units
        return self.view_scale * unit_convert(
            value, from_unit=from_unit, to_unit=self.doc_units
        )

    def unit_convert(
        self,
        scalar: str | float | None,
        from_unit: str | None = None,
        to_unit: str | None = None,
    ) -> float:
        """Perform unit conversion on a scalar value.

        Convert a scalar value from a source unit
        (ie 2.3, '3', '3mm', '5in', etc) to a float value in a destination unit
        (user/document units by default).

        Args:
            scalar: A string scalar with an optional unit identifier suffix.
                (ie '3mm', '4.5', '10pt, '5.3in')
            from_unit: Optional default source unit.
                Default is document (user) units.
            to_unit: An SVG unit id of the destination unit conversion.
                Default is document (user) units.

        Returns:
            A float value or 0.0 if the string can't be parsed.
        """
        if not scalar:
            return 0.0
        if not to_unit:
            to_unit = self.doc_units
        if not from_unit:
            from_unit = self.doc_units
        return unit_convert(scalar, from_unit=from_unit, to_unit=to_unit)

    def write_document(
        self, stream: TextIO, pretty_print: bool = False
    ) -> None:
        """Write the SVG document to a stream output."""
        # Pretty print if in debug mode
        stream.write('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n')
        data = etree.tostring(
            self.document.getroot(),
            encoding='unicode',
            pretty_print=pretty_print,
        )
        stream.write(data)

    def set_precision(self, precision: int | None = None) -> None:
        """Set the output precision.

        Args:
            precision: The number of digits after the decimal point.
        """
        self._fmt_float = '{}' if precision is None else f'{{:.{precision}f}}'
        self._fmt_point = f'{self._fmt_float},{self._fmt_float}'
        self._fmt_move = f'M {self._fmt_point}'
        self._fmt_line = f'M {self._fmt_point} L {self._fmt_point}'
        self._fmt_arc = (
            f'A {self._fmt_point} {self._fmt_float}'
            f' {{:d}} {{:d}} {self._fmt_point}'
        )
        self._fmt_curve = (
            f'C {self._fmt_point} {self._fmt_point} {self._fmt_point}'
        )

    def set_default_parent(self, parent: TElement) -> None:
        """Set the current default parent (or layer)."""
        self.current_parent = parent

    def get_node_by_id(self, node_id: str) -> TElement | None:
        """Find a node in the current document by id attribute.

        Args:
            node_id: The node id attribute value.

        Returns:
            A node if found otherwise None.
        """
        return get_node_by_id(self.document, node_id)

    def get_element_transform(
        self, node: TElement, root: TElement | None = None
    ) -> TMatrix | None:
        """Get the combined transform of the element and its parents.

        Args:
            node: The element node.
            root: The root element to stop searching, or document root if None.

        Returns:
            The combined transform matrix or None.
        """
        if root is None:
            root = self.docroot
        parent_transform = self.get_parent_transform(node, root)
        transform_attr = node.get('transform')
        if transform_attr:
            node_transform = self.parse_transform_attr(transform_attr)
            if parent_transform and node_transform:
                return transform2d.compose_transform(
                    parent_transform, node_transform
                )
            return node_transform
        return parent_transform

    def get_parent_transform(
        self, node: TElement, root: TElement | None = None
    ) -> TMatrix | None:
        """Get the combined transform of the node's parents.

        Args:
            node: The child node.
            root: The root element to stop searching, or document root if None.

        Returns:
            The parent transform matrix or the identity matrix if none found.
        """
        if root is None:
            root = self.docroot
        # matrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        matrix: TMatrix | None = None
        parent = node.getparent()
        while parent is not None and parent is not root:
            parent_transform_attr = parent.get('transform')
            if parent_transform_attr is not None:
                parent_matrix = self.parse_transform_attr(parent_transform_attr)
                if parent_matrix and matrix:
                    matrix = transform2d.compose_transform(
                        parent_matrix, matrix
                    )
                else:
                    matrix = parent_matrix
            parent = parent.getparent()
        return matrix

    def node_is_visible(
        self, node: TElement, check_parent: bool = True, _recurs: bool = False
    ) -> bool:
        """Return True if the node is visible.

        CSS visibility trumps SVG visibility attribute.

        The node is not considered visible if the `visibility` style
        is `hidden` or `collapse` or if the `display` style is `none`.
        If the `visibility` style is `inherit` or `check_parent` is True
        then the visibility is determined by the parent node.

        Args:
            node: An etree.Element node
            check_parent: Recursively check parent nodes for visibility

        Returns:
            True if the node is visible otherwise False.
        """
        if node is None:
            return _recurs

        visibility: str | None = None
        style = node.get('style')
        if style:
            styles = css.inline_style_to_dict(style)
            if styles.get('display') == 'none':
                return False
            visibility = styles.get('visibility')
        if visibility is None:
            visibility = node.get('visibility')

        if visibility is not None:
            if visibility == 'inherit' and not check_parent:
                # Recursively determine parent visibility
                parent = node.getparent()
                if parent:
                    return self.node_is_visible(parent, _recurs=True)
            if visibility in {'hidden', 'collapse'}:
                return False

        if check_parent:
            parent = node.getparent()
            if parent is not None:
                return self.node_is_visible(parent, _recurs=True)

        return True

    def parse_transform_attr(self, stransform: str | None) -> TMatrix | None:
        """Parse an SVG transform attribute.

        Args:
            stransform: A string containing the SVG transform list.

        Returns:
            A single affine transform matrix or None.
        """
        if not stransform:
            return None
        if stransform:
            stransform = stransform.strip()
        transforms = self._TRANSFORM_RE.findall(stransform)
        matrices = []
        for transform, args in transforms:
            matrix = None
            values = [float(n) for n in args.replace(',', ' ').split()]
            num_values = len(values)
            if transform == 'translate':
                x = values[0]
                y = values[1] if num_values > 1 else 0.0
                matrix = transform2d.matrix_translate(x, y)
            if transform == 'scale':
                x = values[0]
                y = values[1] if num_values > 1 else x
                matrix = transform2d.matrix_scale(x, y)
            if transform == 'rotate':
                a = math.radians(values[0])
                cx = values[1] if num_values > 1 else 0.0
                cy = values[2] if num_values > 2 else 0.0
                matrix = transform2d.matrix_rotate(a, (cx, cy))
            if transform == 'skewX':
                a = math.radians(values[0])
                matrix = transform2d.matrix_skew_x(a)
            if transform == 'skewY':
                a = math.radians(values[0])
                matrix = transform2d.matrix_skew_y(a)
            if transform == 'matrix':
                matrix = (
                    (values[0], values[2], values[4]),
                    (values[1], values[3], values[5]),
                )
            if matrix is not None:
                matrices.append(matrix)

        if matrices:
            # Compose all the transforms into one matrix
            result_matrix = matrices[0]
            for matrix in matrices[1:]:
                result_matrix = transform2d.compose_transform(
                    result_matrix, matrix
                )
            return result_matrix

        return None

    def scale_inline_style(self, inline_style: str) -> str:
        """Rescale inline style quantities to user units.

        For any inline style attribute name that ends with
        'width', 'height', or 'size'
        scale the numeric value with an optional unit id suffix
        by converting it to user units with no unit id.
        """
        style_attrs = css.inline_style_to_dict(inline_style)
        for attr, value in style_attrs.items():
            if attr.endswith(('width', 'height', 'size')):
                # Automatically convert unit values
                style_attrs[attr] = self.unit2uu(value)
        return css.dict_to_inline_style(style_attrs)

    def styles_from_templates(
        self,
        style_templates: dict,
        default_map: dict,
        template_map: dict | None = None,
    ) -> dict[str, str]:
        """Create a map of named CSS styles from a template.

        Populates a dictionary of styles given a dictionary of templates and
        mappings.

        If a template key string ends with 'width', 'height', or 'size'
        it is assumed that the value is a numeric value with an optional
        unit id suffix and it will be automatically converted to user units
        with no unit id.

        Args:
            style_templates: A dictionary of style names to
                inline style template strings.
            default_map: A dictionary of template keys to
                default values. This must contain all template identifiers.
            template_map: A dictionary of template keys to
                values that override the defaults. Default is None.

        Returns:
            A dictionary of inline styles.
        """
        # Create a template mapping that fills in missing values
        # from the default map.
        mapping = {}
        for key in default_map:
            value = None
            if template_map is not None:
                value = template_map.get(key)
            if value is None:
                value = default_map[key]
            if value is not None:
                # If the value is a numeric type then it is assumed
                # to already be in user units...
                if key.endswith(('width', 'height', 'size')):
                    try:
                        value = float(value)
                    except ValueError:
                        value = self.unit2uu(value)
                mapping[key] = value

        styles = {}
        for name, template_str in style_templates.items():
            template = string.Template(template_str)
            styles[name] = template.substitute(mapping)
        return styles

    def node_is_group(self, node: TElement) -> bool:
        """Return True if the node is an SVG group."""
        return bool(node.tag == svg_ns('g') or node.tag == 'g')

    def remove_node(self, node: TElement) -> None:
        """Remove node from parent."""
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)

    def create_clip_path(self, path: TElement) -> TElement | None:
        """Create an SVG clipPath."""
        defs = self.docroot.find(f'.//{svg_ns("defs")}')
        if defs:
            node_id = self.generate_id('clipPath')
            attrs = {'id': node_id, 'clipPathUnits': 'userSpaceOnUse'}
            clip = etree.SubElement(defs, svg_ns('clipPath'), attrs)
            # path.getparent().remove(path)
            clip.append(path)
            return clip
        return None

    def set_clip_path(self, node: TElement, clip_path: TElement) -> None:
        """Set the clipping path to the specified node."""
        if clip_path.tag != svg_ns('clipPath'):
            path = self.create_clip_path(clip_path)
            if path is None:
                raise SVGError('Unable to create clip path.')
            clip_path = path
        elif clip_path.get('id') is None:
            clip_path.set('id', self.generate_id('clipPath'))
        node.set('clip-path', f'url(#{clip_path.get("id")})')

    def create_group(
        self,
        children: TElement | None = None,
        style: str | None = None,
        parent: TElement | None = None,
    ) -> TElement:
        """Create an SVG group."""
        if parent is None:
            parent = self.current_parent
        attrs = {}
        if style:
            attrs['style'] = style
        group = etree.SubElement(parent, svg_ns('g'), attrs)
        if children is not None:
            group.extend(children)
        return group

    def create_rect(
        self,
        position: TPoint,
        width: float,
        height: float,
        style: str | None = None,
        parent: TElement | None = None,
    ) -> TElement:
        """Create an SVG rect element."""
        if parent is None:
            parent = self.current_parent
        attrs = {
            'x': str(self._scale(position[0])),
            'y': str(self._scale(position[1])),
            'width': str(self._scale(width)),
            'height': str(self._scale(height)),
        }
        if style is not None and style:
            attrs['style'] = style
        return etree.SubElement(parent, svg_ns('rect'), attrs)

    def create_circle(
        self,
        center: TPoint,
        radius: float,
        style: str | None = None,
        parent: TElement | None = None,
    ) -> TElement:
        """Create an SVG circle element."""
        if parent is None:
            parent = self.current_parent
        attrs = {
            'r': str(self._scale(radius)),
            'cx': str(self._scale(center[0])),
            'cy': str(self._scale(center[1])),
        }
        if style is not None and style:
            attrs['style'] = style
        return etree.SubElement(parent, svg_ns('circle'), attrs)

    def create_ellipse(
        self,
        center: TPoint,
        rx: float,
        ry: float,
        phi: float = 0,
        start_angle: float = 0,
        sweep_angle: float = 0,
        style: str | None = None,
        parent: TElement | None = None,
    ) -> TElement:
        """Create an SVG ellipse using center parameterization."""
        # If phi, start_angle, sweep_angle are all 0 then assume
        # this is a simple <ellipse> element.
        is_ellipse = geom2d.is_zero(start_angle) and geom2d.is_zero(sweep_angle)
        # if geom2d.is_zero(phi) and not is_arc:
        if is_ellipse:
            attrs = {
                'rx': self._fmt_float.format(self._scale(rx)),
                'ry': self._fmt_float.format(self._scale(ry)),
                'cx': self._fmt_float.format(center[0]),
                'cy': self._fmt_float.format(center[1]),
            }
            if not geom2d.is_zero(phi):
                m = transform2d.matrix_rotate(phi, origin=center)
                attrs['transform'] = transform_attr(m)
            return self._create_svgelem(
                'ellipse', attrs, style=style, parent=parent
            )

        # Otherwise it's an elliptical arc and rendered as a path
        arc = geom2d.ellipse.EllipticalArc.from_center(
            center, rx, ry, phi, start_angle, sweep_angle
        )
        attrs = {'d': arc.to_svg_path(scale=self.view_scale, add_move=True)}
        return self._create_svgelem('path', attrs, style=style, parent=parent)

    def create_line(
        self,
        p1: TPoint,
        p2: TPoint,
        style: str | None = None,
        parent: TElement | None = None,
        attrs: dict[str, str] | None = None,
    ) -> TElement:
        """Create an SVG path consisting of one line segment."""
        line_path = self._fmt_line.format(
            self._scale(p1[0]),
            self._scale(p1[1]),
            self._scale(p2[0]),
            self._scale(p2[1]),
        )
        if attrs is None:
            attrs = {}
        attrs['d'] = line_path
        return self._create_svgelem('path', attrs, style, parent)

    def create_arc(
        self,
        arc: arc.Arc,
        style: str | None = None,
        parent: TElement | None = None,
        attrs: dict[str, str] | None = None,
    ) -> TElement:
        """Create an SVG circular arc."""
        if attrs is None:
            attrs = {}
        attrs['d'] = arc.to_svg_path(self.view_scale, add_move=True)
        return self._create_svgelem('path', attrs, style, parent)

    def create_circular_arc(
        self,
        startp: TPoint,
        endp: TPoint,
        radius: float,
        sweep_flag: int,
        style: str | None = None,
        parent: TElement | None = None,
        attrs: dict[str, str] | None = None,
    ) -> TElement:
        """Create an SVG circular arc."""
        m = self._fmt_move.format(
            self._scale(startp[0]), self._scale(startp[1])
        )
        a = self._fmt_arc.format(
            self._scale(radius),
            self._scale(radius),
            0,
            0,
            sweep_flag,
            self._scale(endp[0]),
            self._scale(endp[1]),
        )
        if attrs is None:
            attrs = {}
        attrs['d'] = m + ' ' + a
        return self._create_svgelem('path', attrs, style, parent)

    def create_curve(
        self,
        control_points: Sequence[TPoint],
        style: str | None = None,
        parent: TElement | None = None,
        attrs: dict[str, str] | None = None,
    ) -> TElement:
        """Create an SVG cubic bezier curve.

        Args:
            control_points: Tuple of four control points of a
                cubic bezier curve.
            style: A CSS style string.
            parent: The parent element (or Inkscape layer).
            attrs: Dictionary of SVG element attributes.

        Returns:
            An SVG path Element node.
        """
        p1, cp1, cp2, p2 = control_points
        if attrs is None:
            attrs = {}
        mpart = self._fmt_move.format(self._scale(p1[0]), self._scale(p1[1]))
        cpart = self._format_curve(cp1, cp2, p2)
        attrs['d'] = f'{mpart} {cpart}'
        return self._create_svgelem('path', attrs, style, parent)

    def _format_curve(
        self,
        cp1: TPoint,
        cp2: TPoint,
        p2: TPoint,
    ) -> str:
        return self._fmt_curve.format(
            self._scale(cp1[0]),
            self._scale(cp1[1]),
            self._scale(cp2[0]),
            self._scale(cp2[1]),
            self._scale(p2[0]),
            self._scale(p2[1]),
        )

    def create_polygon(
        self,
        vertices: Sequence[TPoint],
        close_polygon: bool = True,
        close_path: bool = False,
        style: str | None = None,
        parent: TElement | None = None,
        attrs: dict[str, str] | None = None,
    ) -> TElement | None:
        """Create an SVG path describing a polygon.

        Args:
            vertices: A sequence of 2D polygon vertices.
                A vertice being a tuple containing x,y coordicates.
            close_polygon: Close the polygon if it isn't already.
                Default is True.
            close_path: Close and join the the path ends by
                appending 'Z' to the end of the path ('d') attribute.
                Default is False.
            style: A CSS style string.
            parent: The parent element (or Inkscape layer).
            attrs: Dictionary of SVG element attributes.

        Returns:
            An SVG path Element node, or None if the list of vertices is empty.
        """
        if not vertices:
            return None
        d = [
            'M',
            self._fmt_point.format(
                self._scale(vertices[0][0]), self._scale(vertices[0][1])
            ),
            'L',
        ]
        d.extend(
            [
                self._fmt_point.format(self._scale(p[0]), self._scale(p[1]))
                for p in vertices[1:]
            ]
        )
        # for p in vertices[1:]:
        #    d.append(
        #        self._fmt_point.format(self._scale(p[0]), self._scale(p[1]))
        #    )
        if close_polygon and vertices[0] != vertices[-1]:
            d.append(
                self._fmt_point.format(
                    self._scale(vertices[0][0]), self._scale(vertices[0][1])
                )
            )
        if close_path:
            d.append('Z')
        if attrs is None:
            attrs = {}
        attrs['d'] = ' '.join(d)
        return self._create_svgelem('path', attrs, style, parent)

    def create_polygons(
        self,
        polygons: Iterable[Sequence[TPoint]],
        close_polygon: bool = True,
        close_path: bool = False,
        style: str | None = None,
        parent: TElement | None = None,
        attrs: dict[str, str] | None = None,
    ) -> TElement | None:
        """Create an SVG path describing a polygon.

        Args:
            polygons: A collection of polygons,
            each a sequence of 2D polygon vertices.
                A vertice being a tuple containing x,y coordicates.
            close_polygon: Close the polygon if it isn't already.
                Default is True.
            close_path: Close and join the the path ends by
                appending 'Z' to the end of the path ('d') attribute.
                Default is False.
            style: A CSS style string.
            parent: The parent element (or Inkscape layer).
            attrs: Dictionary of SVG element attributes.

        Returns:
            An SVG path Element node, or None if the list of vertices is empty.
        """
        if not polygons:
            return None
        d = []
        for vertices in polygons:
            d += [
                'M',
                self._fmt_point.format(
                    self._scale(vertices[0][0]), self._scale(vertices[0][1])
                ),
                'L',
            ]
            d.extend(
                [
                    self._fmt_point.format(self._scale(p[0]), self._scale(p[1]))
                    for p in vertices[1:]
                ]
            )
            if geom2d.P(vertices[0]) != vertices[-1]:
                if close_polygon:
                    if close_path:
                        d.append('Z')
                    else:
                        d.append(
                            self._fmt_point.format(
                                self._scale(vertices[0][0]),
                                self._scale(vertices[0][1]),
                            )
                        )
            elif close_path:
                del d[-1]
                d.append('Z')

        if attrs is None:
            attrs = {}
        attrs['d'] = ' '.join(d)
        return self._create_svgelem('path', attrs, style, parent)

    def create_polypath(
        self,
        path: Sequence[
            geom2d.Line | geom2d.Arc | geom2d.CubicBezier | Sequence[TPoint]
        ],
        close_path: bool = False,
        style: str | None = None,
        parent: TElement | None = None,
        attrs: dict[str, str] | None = None,
    ) -> TElement | None:
        """Create an SVG path from a sequence of curve segments.

        Args:
            path: A sequence of line, circular arc, or cubic
                Bezier curve  segments.
                A line segment is a 2-tuple containing the endpoints.
                An arc segment is a 5-tuple containing the start point,
                end point, radius, angle, and center, respectively. The
                arc center is ignored.
                A cubic bezier segment is a 4-tuple containing the first
                endpoint, the first control point, the second control point,
                and the second endpoint.
            close_path: Close and join the the path ends by
                appending 'Z' to the end of the path ('d') attribute.
                Default is False.
            style: A CSS style string.
            parent: The parent element (i.e. Inkscape layer).
            attrs: Dictionary of SVG element attributes.

        Returns:
            An SVG path Element node, or None if the path is empty.
        """
        if not path:
            return None
        p1 = path[0][0]
        d = [
            'M',
            self._fmt_point.format(self._scale(p1[0]), self._scale(p1[1])),
        ]
        for segment in path:
            if isinstance(segment, geom2d.Line) or len(segment) == 2:
                # Assume this is a line segment with two endpoints:
                # ((x1, y1), (x2, y2))
                p2 = segment[1]
                d.extend(
                    (
                        'L',
                        self._fmt_point.format(
                            self._scale(p2[0]), self._scale(p2[1])
                        ),
                    )
                )
            elif isinstance(segment, geom2d.CubicBezier) or len(segment) == 4:
                # Assume this is a cubic Bezier:
                # ((x1, y1), (cx1, cx1), (cx2, cx2), (x2, y2))
                cp1 = segment[1]
                cp2 = segment[2]
                p2 = segment[3]
                d.append(self._format_curve(cp1, cp2, p2))
            # elif isinstance(segment, geom2d.Line) or len(segment) == 5:
            elif isinstance(segment, geom2d.Arc) or len(segment) == 5:
                # Assume this is an arc segment:
                # ((x1, y1), (x2, y2), radius, angle, center)
                p2 = segment[1]
                if not isinstance(segment[2], float) or not isinstance(
                    segment[3], float
                ):
                    raise TypeError('Invalid arc segment.')
                radius = segment[2]
                angle = segment[3]
                sweep_flag = 0 if angle < 0 else 1
                arc = self._fmt_arc.format(
                    self._scale(radius),
                    self._scale(radius),
                    0,
                    0,
                    sweep_flag,
                    self._scale(p2[0]),
                    self._scale(p2[1]),
                )
                d.append(arc)
        if close_path:
            d.append('Z')
        if attrs is None:
            attrs = {}
        attrs['d'] = ' '.join(d)
        return self._create_svgelem('path', attrs, style, parent)

    def create_simple_marker(
        self,
        marker_id: str,
        d: str,
        style: str,
        transform: str,
        replace: bool = False,
    ) -> TElement:
        """Create an SVG line end marker glyph.

        The glyph Element is placed under the document root.
        """
        defs = self.docroot.find(f'.//{svg_ns("defs")}')
        if defs is None:
            defs = etree.SubElement(self.docroot, svg_ns('defs'))
        elif replace:
            # If a marker with the same id already exists
            # then remove it first.
            node = defs.find(f'.//*[@id="{marker_id}"]')
            if node is not None:
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
        marker = etree.SubElement(
            defs,
            svg_ns('marker'),
            {
                'id': marker_id,
                'orient': 'auto',
                'refX': '0.0',
                'refY': '0.0',
                'style': 'overflow:visible',
            },
        )
        etree.SubElement(
            marker,
            svg_ns('path'),
            {
                'd': d,
                'style': style,
                'transform': transform,
            },
        )
        return marker

    def _create_svgelem(
        self,
        tag: str,
        attrs: dict[str, str],
        style: str | None = None,
        parent: TElement | None = None,
    ) -> TElement:
        """Create an SVG element."""
        if parent is None:
            parent = self.current_parent
        if style:
            attrs['style'] = style
        return etree.SubElement(parent, svg_ns(tag), attrs)

    def create_text(
        self,
        text: str,
        x: float,
        y: float,
        line_height: float | None = None,
        text_anchor: str | None = None,
        style: str | None = None,
        parent: TElement | None = None,
    ) -> TElement:
        """Create a text block."""
        if parent is None:
            parent = self.current_parent
        attrs: dict[str, str] = {
            'x': str(self._scale(x)),
            'y': str(self._scale(y)),
            xml_ns('space'): 'preserve',
        }
        if style:
            attrs['style'] = style
        if text_anchor is not None:
            attrs['text-anchor'] = text_anchor
        text_elem = etree.SubElement(parent, svg_ns('text'), attrs)
        # if isinstance(text, basestring):
        if isinstance(text, str):
            self._create_text_line(text, x, y, text_elem)
        else:
            for text_line in text:
                self._create_text_line(text_line, x, y, text_elem)
                y += line_height
        return text_elem

    def add_elem(self, node: TElement, parent: TElement | None = None) -> None:
        """Add the element to the parent.

        Uses the :current_parent: if parent is None.
        """
        if parent is None:
            parent = self.current_parent
        if parent is not None:
            parent.append(node)

    def generate_id(self, prefix: str = '_id') -> str:
        """Create a unique XML id attribute value.

        Args:
            prefix: The prefix prepended to a random number.
                Default prefix is '_id'.

        Returns:
            A random id string that has a fairly low chance of collision
            with previously generated ids.
        """
        return random_id(prefix=prefix, rootnode=self.docroot)

    def _create_text_line(
        self, text: str, x: float, y: float, parent: TElement
    ) -> TElement:
        attrs = {
            'x': str(self._scale(x)),
            'y': str(self._scale(y)),
        }
        tspan_elem = etree.SubElement(parent, svg_ns('tspan'), attrs)
        tspan_elem.text = text
        return tspan_elem

    def _scale(self, n: float) -> float:
        """Scale the scalar value to viewbox."""
        return n * self.view_scale

    def _scalep(self, p: TPoint) -> TPoint:
        """Scale the point value to viewbox."""
        return (p[0] * self.view_scale, p[1] * self.view_scale)


def geompath_to_svgpath(
    path: Iterable[
        geom2d.Line | geom2d.Arc | geom2d.EllipticalArc | geom2d.CubicBezier
    ],
    scale: float = 1,
    close_path: bool = False,
) -> str | None:
    """Create an SVG path from a sequence of geometry segments.

    Args:
        path: A sequence of Line, Arc, EllipticalArc, or CubicBezier segments.
        scale: SVG scaling factor. Default is 1.
        close_path: Close and join the the path ends by
            appending 'Z' to the end of the path ('d') attribute.
            Default is False.

    Returns:
        An SVG path attribute value (the 'd' part).
    """
    if not path:
        return None

    it = iter(path)
    try:
        first_segment = next(it)
        first_point = first_segment.p1
        last_point = first_segment.p2
    except StopIteration:
        pass
    else:
        dparts = [f'M {first_point.to_svg(scale=scale)}']
        prev_type: type = geom2d.Line
        for segment in path:
            add_prefix = bool(prev_type != type(segment))
            dparts.append(
                segment.to_svg_path(scale=scale, add_prefix=add_prefix)
            )
            prev_type = type(segment)
            last_point = segment.p2

        if close_path and first_point != last_point:
            dparts.append('Z')

        return ' '.join(dparts)

    return ''  # empty path


DIGIT_EXP = '0123456789eE'
COMMA_WSP = ', \t\n\r\f\v'
DRAWTO_COMMAND = 'MmZzLlHhVvCcSsQqTtAa'
SIGN = '+-'
EXPONENT = 'eE'


def path_tokenizer(path_data: str) -> Iterator[tuple[str, bool]]:
    """Tokenize SVG path data.

    A generator that yields tokens from path data.
    This will yield a tuple containing a
    command token or a numeric parameter token
    followed by a boolean flag that is True if the token
    is a command and False if the token is a numeric parameter.

    Args:
        path_data: The 'd' attribute of an SVG path.

    Yields:
        A 2-tuple with token and token type hint.
    """
    # --------------------------------------------------------------------------
    # Thanks to Peter Stangl for this.
    # It is significantly faster than using regexp.
    # https://codereview.stackexchange.com/users/71285/peter-stangl
    #
    # See:
    #     https://codereview.stackexchange.com/questions/28502/svg-path-parsing
    #     https://www.w3.org/TR/SVG/paths.html#PathDataBNF
    # --------------------------------------------------------------------------
    in_float = False
    entity = ''
    for char in path_data:
        if char in DIGIT_EXP:
            entity += char
        elif char in COMMA_WSP and entity:
            yield (entity, False)  # Number parameter
            in_float = False
            entity = ''
        elif char in DRAWTO_COMMAND:
            if entity:
                yield (entity, False)  # Number parameter
                in_float = False
                entity = ''
            yield (char, True)  # Yield a command
        elif char == '.':
            if in_float:
                yield (entity, False)  # Number parameter
                entity = '.'
            else:
                entity += '.'
                in_float = True
        elif char in SIGN:
            if entity and entity[-1] not in EXPONENT:
                yield (entity, False)  # Number parameter
                in_float = False
                entity = char
            else:
                entity += char
    if entity:
        yield (entity, False)  # Number parameter


def _radians(a: str) -> float:
    return math.radians(float(a))


# This parser metadata structure is shamelessly borrowed from
# Aaron Spike's simplepath parser with minor modifications.
#
# {path-command:
# [
# output-command, # Canonical command
# num-params, # Expected number of parameters
# [casts, ...], # float, int
# [coord-axis, ...] # 0 == x, 1 == y, -1 == not a coordinate param
# ]}
# fmt: off
PathdefType = dict[str, tuple[str, int, tuple, tuple]]
_PATHDEFS: PathdefType = {
    'M': ('M', 2, (float, float), (0, 1)),
    'L': ('L', 2, (float, float), (0, 1)),
    'H': ('L', 1, (float,), (0,)),
    'V': ('L', 1, (float,), (1,)),
    'C': ('C', 6, (float, float, float, float, float, float),
             (0, 1, 0, 1, 0, 1)),
    'S': ('C', 4, (float, float, float, float), (0, 1, 0, 1)),
    'Q': ('Q', 4, (float, float, float, float), (0, 1, 0, 1)),
    'T': ('Q', 2, (float, float), (0, 1)),
    'A': (
        'A', 7,
        (float, float, _radians, int, int, float, float),
        (-1, -1, -1, -1, -1, 0, 1)
    ),
    'Z': ('L', 0, (), ()),
}
# fmt: on


# pylint: disable=too-many-statements
def parse_path(path_data: str) -> Iterator[tuple]:  # noqa: PLR0912 PLR0915
    """Parse an SVG path definition string.

    Converts relative values to absolute and
    shorthand commands to canonical (ie. H to L, S to C, etc.)
    Terminating Z (or z) converts to L.

    If path syntax errors are encountered, parsing will simply stop.
    No exceptions are raised. This is by design so that parsing
    is relatively forgiving of input.

    Implemented as a generator so that memory usage can be minimized
    for very long paths.

    Args:
        path_data: The 'd' attribute value of a SVG path element.

    Yields:
        A path component 2-tuple of the form (cmd, params).
    """
    # Current command context
    current_cmd = None
    # Current path command definition
    pathdef = _PATHDEFS['M']
    # Start of sub-path
    moveto = (0.0, 0.0)
    # Current drawing position
    pen = (0.0, 0.0)
    # Last control point for curves
    last_control = pen
    # True if the command is relative
    cmd_is_relative = False
    # True if the parser expects a command
    expecting_command = True
    # Current accumulated parameters
    params: list = []

    tokenizer = path_tokenizer(path_data)
    pushed_token = None

    while True:
        if pushed_token:
            (  # pylint: disable=unpacking-non-sequence
                token,
                is_command,
            ) = pushed_token
            pushed_token = None
        else:
            try:
                token, is_command = next(tokenizer)
            except StopIteration:
                break
        if expecting_command:
            if current_cmd is None and token.upper() != 'M':
                break
            if is_command:
                cmd_is_relative = token.islower()
                cmd = token.upper()
                pathdef = _PATHDEFS[cmd]
                current_cmd = cmd
                if current_cmd == 'Z':
                    # Push back an empty token since this has no parameters
                    pushed_token = ('', False)
            else:
                # In implicit command
                if current_cmd == 'M':
                    # Any subsequent parameters are for an implicit LineTo
                    current_cmd = 'L'
                    pathdef = _PATHDEFS[current_cmd]
                # Push back token for parameter accumulation on next pass
                pushed_token = (token, is_command)
            expecting_command = False
        else:
            if is_command:
                # Bail if number of parameters doesn't match command
                break

            # Accumulate parameters for the current command
            param_index = len(params)
            if param_index < pathdef[1]:
                cast = pathdef[2][param_index]
                value = cast(token)
                if cmd_is_relative:
                    # Get the axis this shorthand is referring to
                    # 0 = X, 1 = Y, -1 = none
                    axis = pathdef[3][param_index]
                    if axis >= 0:
                        # Make relative value absolute
                        value += pen[axis]
                params.append(value)
                param_index += 1

            if param_index == pathdef[1]:
                # All parameters have been accumulated now process command
                if current_cmd == 'M':
                    moveto = (params[0], params[1])
                elif current_cmd == 'Z':
                    params.extend(moveto)
                    pushed_token = None
                elif current_cmd == 'H':
                    params.append(pen[1])
                elif current_cmd == 'V':
                    params.insert(0, pen[0])
                elif current_cmd in {'S', 'T'}:
                    params.insert(0, pen[1] + (pen[1] - last_control[1]))
                    params.insert(0, pen[0] + (pen[0] - last_control[0]))
                if current_cmd in {'C', 'Q'}:
                    last_control = (params[-4], params[-3])
                else:
                    last_control = pen
                output_cmd = pathdef[0]
                yield (output_cmd, params)
                # Update the drawing position to the last end point.
                pen = (params[-2], params[-1])
                params = []
                expecting_command = True


# pylint: enable=too-many-statements


def explode_path(path_data: str) -> list:
    """Break the path at node points into component segments.

    Args:
        path_data: The 'd' attribute value of a SVG path element.

    Returns:
        A list of path 'd' attribute values.
    """
    dlist = []
    p1 = None
    for cmd, params in parse_path(path_data):
        if cmd == 'M':
            p1 = (params[-2], params[-1])
            continue
        p2 = (params[-2], params[-1])
        if p1 is not None:
            paramstr = ' '.join([str(param) for param in params])
            d = f'M {p1[0]:f} {p1[1]:f} {cmd} {paramstr}'
            dlist.append(d)
        p1 = p2
    return dlist


def create_svg_document(
    width: str | float,
    height: str | float,
    doc_units: str = 'px',
    doc_id: str | None = None,
    nsmap: dict | None = None,
) -> TDocument:
    """Create a minimal SVG document tree.

    The svg element `viewbox` attribute will maintain the size and
    attribute ratio as specified by width and height.

    Args:
        width: The width of the document in user units.
        height: The height of the document in user units.
        doc_units: The user unit type (i.e. 'in', 'mm', 'pt', 'em', etc.)
            By default this will be 'px'.
        doc_id: The id attribute of the enclosing svg element.
            If None (default) then a random id will be generated.
        nsmap: Namespace mapping.

    Returns:
        An lxml.etree.ElementTree
    """
    if nsmap is None:
        nsmap = SVG_NS

    def floatystr(value: str | float) -> str:
        # Strip off trailing zeros from fixed point float string
        # This is similar to the 'g' format but wont display scientific
        # notation for big numbers.
        return f'{float(value):f}'.rstrip('0').rstrip('.')

    if isinstance(width, str):
        doc_units = scalar_unit(width, default=doc_units)
        width_str = floatystr(scalar_value(width))
    else:
        width_str = floatystr(width)
    if isinstance(height, str):
        doc_units = scalar_unit(height, default=doc_units)
        height_str = floatystr(scalar_value(height))
    else:
        height_str = floatystr(height)

    docroot = etree.Element(svg_ns('svg'), nsmap=nsmap)
    docroot.set('width', f'{width_str}{doc_units}')
    docroot.set('height', f'{height_str}{doc_units}')
    docroot.set('viewBox', f'0 0 {width_str} {height_str}')
    if doc_id is None:
        doc_id = random_id(prefix='svg')
    docroot.set('id', doc_id)
    return etree.ElementTree(docroot)


def random_id(prefix: str = '_svg', rootnode: TElement | None = None) -> str:
    """Create a random XML id attribute value.

    Args:
        prefix: The prefix prepended to a random number.
            Default is '_svg'.
        rootnode: The root element to search for id name collisions.
            Default is None in which case no search will be performed.

    Returns:
        A random id string that has a fairly low chance of collision
        with previously generated ids.
    """
    id_attr = f'{prefix}{random.randint(1, 2 ** 31):d}'
    if rootnode is not None:
        while get_node_by_id(rootnode, id_attr) is not None:
            id_attr = f'{prefix}{random.randint(1, 2 ** 31):d}'
    return id_attr


def get_node_by_id(root: TElement | TDocument, node_id: str) -> TElement | None:
    """Find an element in the specified element tree by id attribute.

    Args:
        root: The root element to search.
        node_id: The element id attribute value.

    Returns:
        An element if found otherwise None.
    """
    return root.find(f'.//*[@id="{node_id}"]')


def get_node_by_tag(root: TElement, tag: str) -> TElement | None:
    """Find first element having specified tag name."""
    return root.find(f'.//{tag}')


def transform_attr(matrix: TMatrix) -> str:
    """Create a SVG transform attribute value from matrix."""
    return (
        f'matrix({matrix[0][0]:f},{matrix[1][0]:f},'
        f'{matrix[0][1]:f},{matrix[1][1]:f},'
        f'{matrix[0][2]:f},{matrix[1][2]:f})'
    )


def scalar_unit(scalar: str | None, default: str = 'px') -> str:
    """Get the unit part of an SVG/CSS scalar size value.

    For example: 'in' from '15.3in', or 'px' from '101px'.
    """
    if scalar:
        m = _RE_CSS_UNIT.search(scalar)
        if m:
            return m.string[m.start() : m.end()]
    return default


def scalar_value(scalar: str | None) -> float:
    """Get the numeric part of an SVG/CSS scalar size value.

    For example: 15.3 from '15.3in'
    """
    if scalar:
        m = _RE_FLOAT.match(scalar)
        if m:
            return float(m.string[m.start() : m.end()])
    return 0.0


def unit_convert(
    value: str | float | None, from_unit: str = 'px', to_unit: str = 'px'
) -> float:
    """Convert a scalar value from one unit to another.

    See http://www.w3.org/TR/SVG/coords.html#ViewBoxAttribute
    and http://www.w3.org/TR/SVG/coords.html#Units
    and http://wiki.inkscape.org/wiki/index.php/Units_In_Inkscape

    Args:
        value: A string scalar with an optional unit identifier suffix
            (ie '3mm', '10pt, '5.3in'), or a float value.
        from_unit: Optional default source unit identifier.
            Used if the input value is a float or if the
            unit identifier could not be parsed from the string value.
        to_unit: Optional destination unit identifier of the unit conversion.
            Default is 'px'.

    Returns:
        A float value or 0.0 if the string can't be parsed.
    """
    if not value:
        return 0.0
    if isinstance(value, str):
        from_unit = scalar_unit(value, default=from_unit)
        value = scalar_value(value)

    return value * (UNIT_CONV.get(from_unit, 1) / UNIT_CONV.get(to_unit, 1))
