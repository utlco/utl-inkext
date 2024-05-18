"""A simple library for SVG output - but more Inkscape-centric."""

from __future__ import annotations

import logging
import re
import typing

# from xml.etree import ElementTree as etree
import geom2d
from geom2d import transform2d
from lxml import etree

from . import svg

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from .svg import TDocument, TElement

logger = logging.getLogger(__name__)

# Dictionary of XML namespaces used in Inkscape documents
INKSCAPE_NS = {
    'inkscape': 'http://www.inkscape.org/namespaces/inkscape',
    'sodipodi': 'http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd',
}
# Add the standard SVG namespaces
INKSCAPE_NS.update(svg.SVG_NS)

# Vendor specific namespace (in this case us)
UTLCO_NS = {
    'utlco': 'http://www.utlco.com/namespaces/utlco',
}
# INKSCAPE_NS.update(UTLCO_NS)


def inkscape_ns(tag: str) -> str:
    """Prepend the `inkscape` namespace to an element tag."""
    return svg.add_ns(tag, INKSCAPE_NS, 'inkscape')


def sodipodi_ns(tag: str) -> str:
    """Prepend the `sodipodi` namespace to an element tag."""
    return svg.add_ns(tag, INKSCAPE_NS, 'sodipodi')


def utlco_ns(tag: str) -> str:
    """Prepend the `utlco` namespace to an element tag."""
    return svg.add_ns(tag, UTLCO_NS, 'utlco')


class InkscapeSVGContext(svg.SVGContext):
    """SVG Context with Inkscape-specific methods."""

    _DEFAULT_SHAPES = (
        'path',
        'rect',
        'line',
        'circle',
        'ellipse',
        'polyline',
        'polygon',
    )
    _DEFAULT_DOC_UNITS = 'px'

    doc_name: str

    # Inkscape ruler units.
    # These should be same as SVG doc units, but for whatever reason
    # Inkscape can create documents that have different doc/ruler units.
    ruler_units: str

    _current_layer_id: str | None = None

    def __init__(self, document: TDocument) -> None:
        """Inkscape-specific SVG Context.

        Args:
            document: Root SVG document
        """
        super().__init__(document)

        self.doc_name = self.docroot.get('sodipodi:docname', 'untitled.svg')
        self.ruler_units = self.doc_units

        basedoc = self.find('.//sodipodi:namedview')
        if basedoc is not None:
            self.ruler_units = basedoc.get(
                inkscape_ns('document-units'),
                basedoc.get('units', self.doc_units),
            )
            # Current Inkscape layer
            layer_id = basedoc.get(inkscape_ns('current-layer'))
            if layer_id:
                layer = self.get_node_by_id(layer_id)
                if layer is not None:
                    self.current_parent = layer

        # Document clipping rectangle
        self.cliprect = geom2d.Box((0, 0), self.get_document_size())

    def margin_cliprect(self, mtop: float, *args: float) -> geom2d.Box:
        """Create a clipping rectangle for document margins.

        Margin argument order follows CSS margin property rules.

        Args:
            mtop: Top margin (user units)
            *args: Optional right, bottom, and left margins.
                By default right, bottom, and left margins
                will be set to top value. If right is specified
                then by default left is set to right value.

        Returns:
            A geom2d.Box clipping rectangle
        """
        doc_size = self.get_document_size()
        mright = mtop
        mbottom = mtop
        mleft = mtop
        if len(args) > 0:
            mright = args[0]
            mleft = args[0]
        if len(args) > 1:
            mbottom = args[1]
        if len(args) > 2:
            mleft = args[2]
        return geom2d.Box(
            (mleft, mbottom), (doc_size[0] - mright, doc_size[1] - mtop)
        )

    def get_document_name(self) -> str:
        """Return the name of this document. Default is 'untitled'."""
        return self.doc_name

    def set_document_background(self, color: str) -> None:
        """Set the document background color.

        Args:
            color (string): A CSS color (ie. '#ffffff')
        """
        basedoc = self.find('.//sodipodi:namedview')
        if basedoc:
            basedoc.set('pagecolor', color)

    #    def get_selected_layer(self) -> TElement | None:
    #        """Get the currently selected Inkscape layer element.
    #
    #        Returns:
    #            The currently selected layer element or None
    #            if no layers are selected.
    #        """
    #        if self._current_layer_id is not None:
    #            return self.get_node_by_id(self._current_layer_id)
    #        return None

    def find_layer(self, layer_name: str) -> TElement | None:
        """Find an Inkscape layer by Inkscape layer name.

        If there is more than one layer by that name then just the
        first one will be returned.

        :param layer_name: The Inkscape layer name to find.
        :return: The layer Element node or None.
        """
        return self.find(f'.//svg:g[@inkscape:label="{layer_name}"]')

    #    def clear_layer(self, layer_name):
    #        """Delete the contents of the specified layer.
    #        Does nothing if the layer doesn't exist.
    #        """
    #        layer = self.find_layer(layer_name)
    #        if layer is not None:
    #            del layer[:]

    def create_layer(
        self,
        layer_name: str,
        opacity: float | None = None,
        clear: bool = True,
        incr_suffix: bool = False,
        flipy: bool = False,
        tag: str | None = None,
        parent: TElement | None = None,
    ) -> TElement:
        """Create an Inkscape layer or return an existing layer.

        Args:
            layer_name: The name of the layer to create.
            opacity: Layer opacity (0.0 to 1.0).
            clear: If a layer of the same name already exists then
                erase it first if True otherwise just return it.
                Default is True.
            incr_suffix: If a layer of the same name already exists and
                it is non-empty then add an auto-incrementing numeric suffix
                to the name (overrides *clear*).
            flipy: Add transform to flip Y axis.
            tag: A layer tag added as an extended attribute.
                Uses `utlco` namespace. This can be used to tag layers
                with a custom label.
            parent: An optional parent element to append the new layer.

        Returns:
            A new layer or an existing layer of the same name.
        """
        if parent is None:
            parent = self.docroot

        layer = self.find_layer(layer_name)
        if incr_suffix:
            suffix_n = 1
            base_name = layer_name
            while layer is not None:
                layer_name = f'{base_name} {suffix_n:d}'
                suffix_n += 1
                layer = self.find_layer(layer_name)

        if layer is None:
            layer_attrs = {
                inkscape_ns('label'): layer_name,
                inkscape_ns('groupmode'): 'layer',
            }
            if tag is not None:
                layer_attrs[utlco_ns('tag')] = tag
            if opacity is not None:
                opacity = min(max(opacity, 0.0), 1.0)
                layer_attrs['style'] = f'opacity: {opacity:.2f};'
            if flipy:
                transfrm = f'translate(0, {self.view_height:g}) scale(1, -1)'
                layer_attrs['transform'] = transfrm
            layer = etree.SubElement(parent, svg.svg_ns('g'), layer_attrs)
            # layer = etree.SubElement(parent, 'g', layer_attrs)
        elif clear:
            # Remove subelements
            del layer[:]

        # if 'transform' in layer.attrib:
        #    del layer.attrib['transform']
        return layer

    def set_layer_name(self, layer: TElement, name: str) -> None:
        """Rename an Inkscape layer."""
        layer.set(inkscape_ns('label'), name)

    def get_layer_name(self, layer: TElement) -> str | None:
        """Return the name of the Inkscape layer."""
        return typing.cast(str, layer.get(inkscape_ns('label')))

    def get_parent_layer(self, node: TElement) -> TElement | None:
        """Get the layer that the node resides in.

        Returns:
            A layer, or None if the node is not in a layer.
        """
        # TODO: it's probably better/faster to recursively climb
        # the parent chain until docroot or layer is found.
        # This assumes that Inkscape still doesn't support sub-layers
        layers = self.document.findall(
            '//svg:g[@inkscape:groupmode="layer"]', namespaces=INKSCAPE_NS
        )
        for layer in layers:
            if node in layer.iter():
                return layer
        # layers = self.document.xpath(
        #    '//svg:g[@inkscape:groupmode="layer"]', namespaces=INKSCAPE_NS
        # )
        # if isinstance(layers, Iterable):
        #    for layer in layers:
        #        if isinstance(layer, TElement) and node in layer.iter():
        #            return layer
        return None

    def layer_is_locked(self, layer: TElement) -> bool:
        """Check if the layer is locked."""
        val = layer.get(sodipodi_ns('insensitive'))
        return val is not None and val.lower() == 'true'

    def find(self, path: str) -> TElement | None:
        """Find an element in the current document.

        Args:
            path: XPath path.

        Returns:
            The first matching element or None if not found.
        """
        return self.document.find(path, namespaces=INKSCAPE_NS)

        # with contextlib.suppress(IndexError):
        #        return self.document.xpath(path, namespaces=INKSCAPE_NS)[0]
        #    return None

    def get_visible_layers(self) -> list[TElement]:
        """Get a list of visible layers."""
        return [
            node
            for node in self.docroot
            if self.is_layer(node) and self.node_is_visible(node)
        ]

    def get_layer_elements(self, layer: TElement) -> list[TElement]:
        """Get document elements by layer.

        Returns all the visible child elements of the given layer.

        Args:
            layer: The layer root element.

        Returns:
            A (possibly empty) list of visible elements.
        """
        if self.node_is_visible(layer):
            return [
                node
                for node in layer
                if self.node_is_visible(node, check_parent=False)
            ]
        return []

    def is_layer(self, node: TElement) -> bool:
        """Determine if the element is an Inkscape layer node."""
        if self.node_is_group(node):
            layer_name = self.get_layer_name(node)
            return bool(layer_name is not None and layer_name)
        return False

    def get_shape_elements(
        self,
        elements: Iterable[TElement] | None = None,
        shapetags: Iterable[str] = _DEFAULT_SHAPES,
        parent_transform: tuple | None = None,
        skip_layers: list[str] | None = None,
        accumulate_transform: bool = True,
    ) -> list[tuple[TElement, geom2d.TMatrix | None]]:
        """Get all shape elements in an element tree.

        Traverse a tree of SVG nodes and flatten it to a list of
        tuples containing an SVG shape element and its accumulated transform.

        This does a depth-first traversal of <g> and <use> elements.

        Hidden elements are ignored.

        Args:
            elements: An iterable collection of element nodes.
                This will be all top level elements (docroot) by default.
            shapetags: List of shape element tags that can be fetched.
                Default is ('path', 'rect', 'line', 'circle',
                'ellipse', 'polyline', 'polygon').
                Anything else is ignored.
            parent_transform: Transform matrix to add to each node's transforms.
                If None the node's parent transform (if any) is used.
            skip_layers: A list of layer names (as regexes) to ignore
            accumulate_transform: Apply parent transform(s) to element node
                if True. Default is True.

        Returns:
            A possibly empty list of 2-tuples consisting of
            SVG element and accumulated transform.
        """
        if elements is None:
            elements = self.docroot.iterchildren()

        shapes = []
        for node in elements:
            shapes.extend(
                self._get_shape_nodes_recurs(
                    node,
                    shapetags,
                    parent_transform,
                    True,
                    skip_layers,
                    accumulate_transform,
                )
            )
        return shapes

    def _get_shape_nodes_recurs(  # noqa: PLR0912 too-many-branches
        self,
        node: TElement,
        shapetags: Iterable[str],
        parent_transform: tuple | None,
        check_parent: bool,
        skip_layers: list[str] | None,
        accumulate_transform: bool,
    ) -> list[tuple[TElement, geom2d.TMatrix | None]]:
        """Recursively get all shape elements in an element tree."""
        if not self.node_is_visible(node, check_parent=check_parent):
            return []

        # first apply the current transform matrix to this node's transform
        node_transform = self.parse_transform_attr(node.get('transform'))
        if accumulate_transform:
            if parent_transform is None:
                parent_transform = self.get_parent_transform(node)
            if not node_transform:
                node_transform = parent_transform
            elif parent_transform:
                node_transform = transform2d.compose_transform(
                    parent_transform, node_transform
                )

        shapes = []
        if self.node_is_group(node):
            if self.is_layer(node) and skip_layers:
                layer_name = self.get_layer_name(node)
                # logger.debug('layer: %s', layer_name)
                if layer_name:
                    for skip_layer in skip_layers:
                        if re.match(skip_layer, layer_name):
                            # logger.debug('skipping layer: %s', layer_name)
                            return []
            # Recursively traverse group children
            for child_node in node:
                subnodes = self._get_shape_nodes_recurs(
                    child_node,
                    shapetags,
                    node_transform,
                    False,
                    skip_layers,
                    accumulate_transform,
                )
                shapes.extend(subnodes)
        elif node.tag == svg.svg_ns('use') or node.tag == 'use':
            # A <use> element refers to another SVG element via an
            # xlink:href="#id" attribute.
            refid = node.get(svg.xlink_ns('href'))
            if refid:
                # [1:] to ignore leading '#' in reference
                refnode = self.get_node_by_id(refid[1:])
                # TODO: Can the referred node not be visible?
                if refnode is not None:  # and self.node_is_visible(refnode):
                    # Apply explicit x,y translation transform
                    x = float(node.get('x', '0'))
                    y = float(node.get('y', '0'))
                    if x != 0 or y != 0:
                        translation = transform2d.matrix_translate(x, y)
                        if node_transform:
                            node_transform = transform2d.compose_transform(
                                node_transform, translation
                            )
                        else:
                            node_transform = translation
                    subnodes = self._get_shape_nodes_recurs(
                        refnode,
                        shapetags,
                        node_transform,
                        False,
                        skip_layers,
                        accumulate_transform,
                    )
                    shapes.extend(subnodes)
        elif svg.strip_ns(node.tag) in shapetags:
            shapes.append((node, node_transform))
        return shapes


def create_inkscape_document(
    width: float,
    height: float,
    doc_units: str = 'px',
    doc_id: str | None = None,
    doc_name: str | None = None,
    layer_name: str | None = None,
    layer_id: str = 'defaultlayer',
) -> TDocument:
    """Create a minimal Inkscape-compatible SVG document.

    Args:
        width: The width of the document.
        height: The height of the document.
        doc_units: The document unit type (i.e. 'in', 'mm', 'pt', 'em', etc.)
            By default this will be 'px'.
        doc_id: The id attribute of the enclosing svg element.
            If None (default) then a random id will be generated.
        doc_name: The name of the document (i.e. 'MyDrawing.svg').
        layer_name: Display name of default layer.
            By default no default layer will be created.
        layer_id: Id attribute value of default layer.
            Default id is 'defaultlayer'.

    Returns:
        An lxml.etree.ElementTree
    """
    if isinstance(width, str):
        doc_units = svg.scalar_unit(width, doc_units)
    elif isinstance(height, str):
        doc_units = svg.scalar_unit(height, doc_units)

    document = svg.create_svg_document(
        width, height, doc_units, doc_id, nsmap=INKSCAPE_NS
    )
    docroot = document.getroot()

    # Add Inkscape-specific elements/attributes...
    docroot.set(sodipodi_ns('docname'), doc_name or 'untitled')
    namedview = etree.SubElement(docroot, sodipodi_ns('namedview'), id='base')
    namedview.set('units', doc_units)
    namedview.set(inkscape_ns('document-units'), doc_units)
    if layer_name:
        layer = etree.SubElement(docroot, svg.svg_ns('g'), id=layer_id)
        # layer = etree.SubElement(docroot, 'g', id=layer_id)
        layer.set(inkscape_ns('groupmode'), 'layer')
        layer.set(inkscape_ns('label'), layer_name)
        namedview.set(inkscape_ns('current-layer'), layer_id)

    return document
