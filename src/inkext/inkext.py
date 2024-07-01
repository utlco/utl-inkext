"""Inkscape extension helper class."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import gettext
import logging
import math
import os
import pathlib
import re
import sys
import time
import traceback
from typing import TYPE_CHECKING, Any

import geom2d
import geom2d.debug

from . import css, geomsvg, inksvg

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .svg import TElement

_ = gettext.gettext
logger = logging.getLogger(__name__)


_RE_HEX_COLOR = re.compile(r'(#|0x)?([0-9a-fA-F]+)')


def inkbool(value: str | int | bool) -> bool:
    """Inkscape-argparse boolean type.

    Convert a string boolean (ie 'True' or 'False') to Python boolean.
    """
    boolstr = str(value).lower()
    if boolstr in {'true', 't', 'yes', 'y', '1'}:
        return True
    if boolstr in {'false', 'f', 'no', 'n', '0'}:
        return False
    raise argparse.ArgumentTypeError(f'Invalid inkbool value: {value}')


def csscolor(value: str | int) -> str:
    """Inkscape-argparse CSS color type.

    Convert an Inkscape color widget value or form text value
    to a CSS hex color value (ie '#ffffff' or 'none').
    """
    if value and value != 'none':
        rgba = _rgbacolor(value)
        if rgba:
            r, g, b, _a = (int(c * 255) for c in rgba)
            return f'#{r:02x}{g:02x}{b:02x}'
    return 'none'


def rgbacolor(value: str | int) -> tuple:
    """Inkscape-argparse type.

    Convert an Inkscape color widget value to a RGBA tuple (R, G, B, A).
    """
    rgba = _rgbacolor(value)
    if rgba:
        return rgba
    return (0, 0, 0, 0)


def _rgbacolor(value: str | int) -> tuple | None:
    """Convert a CSS-style hex string or Inkscape color picker value to RGBA."""
    r: float = 0
    g: float = 0
    b: float = 0
    a: float = 1

    # First try treating it as an integer (ie from Inkscape's color picker)
    with contextlib.suppress(ValueError):
        c1 = int(value)
        r = int((c1 >> 24) & 0xFF) / 255
        g = int((c1 >> 16) & 0xFF) / 255
        b = int((c1 >> 8) & 0xFF) / 255
        a = int(c1 & 0xFF) / 255
        return (r, g, b, a)

    # Otherwise see if it's a string of the form [#|0x]fff[fff][ff]
    with contextlib.suppress(ValueError):
        m = _RE_HEX_COLOR.match(str(value))
        if m:
            hexcolor = m.group(2)
            hlen = len(hexcolor)

            if 2 < hlen <= 4:
                # CSS short form hex (ie '#fff') with optional alpha channel
                r = int(hexcolor[0], 16) * 17 / 255
                g = int(hexcolor[1], 16) * 17 / 255
                b = int(hexcolor[2], 16) * 17 / 255
                if hlen == 4:
                    a = int(hexcolor[3], 16) * 17 / 255
                return (r, g, b, a)

            if 5 < hlen <= 8:
                r = int(hexcolor[0:2], 16) / 255
                g = int(hexcolor[2:4], 16) / 255
                b = int(hexcolor[4:6], 16) / 255
                if hlen > 6:
                    a = int(hexcolor[6:8], 16) / 255
                return (r, g, b, a)

    # Malformed color spec
    return None


def degrees(value: str | float) -> float:
    """Argparse type: Convert an angle specified in degrees to radians."""
    try:
        return math.radians(float(value))
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f'Invalid degree value: {value}'
        ) from e


def percent(value: str | float) -> float:
    """Argparse type: Convert a percentage specified as 0-100 to a float 0-1.0.

    Args:
        value: a number in the range 0-100
    """
    try:
        return float(value) / 100
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f'Invalid percent value: {value}'
        ) from e


class _DocUnits:
    value: str | float

    def __init__(self, value: str | float) -> None:
        self.value = value


def docunits(value: str | float) -> _DocUnits:
    """Inkscape-argparse document unit value type.

    Value will be converted to document units after the document
    has been parsed and the document units can be determined.
    The DocUnit type is just a memo so that the post processing step
    can find the cli options of type docunits.
    """
    try:
        return _DocUnits(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f'Invalid docunit value: {value}'
        ) from e


def errormsg(
    *args: Any,  # noqa: ANN401
    exit_status: int | None = None,
    **kwargs: Any,  # noqa: ANN401
) -> None:
    """Write an error msg to stderr.

    Intended for end-user-visible messages (usually error conditions).
    Inkscape displays stderr output in a dialog after the extension runs.
    """
    print(*args, file=sys.stderr, **kwargs)  # noqa: T201
    if exit_status is not None:
        sys.exit(exit_status)


class ExtensionError(Exception):
    """Exception thrown to abort extension."""


class InkscapeExtension:
    """Base class for Inkscape extensions.

    This does not depend on Inkscape being installed and can be
    invoked as a stand-alone application.
    If an input document is not
    specified a new blank SVG document will be created.

    This replaces inkex.Effect which ships with Inkscape.

    See Also:
        inkex.Effect
    """

    # : SVG context for this extension
    svg: inksvg.InkscapeSVGContext

    # : Parsed command line option values available to the extension
    options: argparse.Namespace

    # : Debug SVG context if a debug layer has been created
    debug_svg: inksvg.InkscapeSVGContext | None = None

    def main(self, flip_debug_layer: bool = False) -> None:
        """Main entry point for the extension.

        Args:
            flip_debug_layer: Flip the Y axis of the debug layer.
                This is useful if the GUI coordinate origin is at
                the bottom left. Default is False.
            debug_layer_name: Name of the debug layer.
        """
        # This just calls run() to be compatible with the new Inkex test harness
        self.run(flip_debug_layer=flip_debug_layer)

    def run(  # noqa: PLR0912 too-many-branches
        self,
        argv: list | None = None,
        output: str | os.PathLike | None = None,
        flip_debug_layer: bool = False,
    ) -> None:
        """Legacy Inkex entry point for the extension.

        Args:
            argv: Command line options, default is sys.argv[1:]
            output: Output file name. Default output is stdout.
            flip_debug_layer: Flip the Y axis of the debug layer.
                This is useful if the GUI coordinate origin is at
                the bottom left. Default is False.
        """
        # Parse command line options
        self.options = self._process_options(argv)
        if not self.options.output_file and output:
            self.options.output_file = pathlib.Path(output)

        # Create log file if specified.
        if self.options.log_create:
            self._create_log(self.options.log_filename, self.options.log_level)
            logger.info('Invocation: %s', ' '.join(argv or sys.argv))

        # The option to create a new document supersedes the
        # input file option.
        # The default input is stdin.
        if self.options.new_document:
            document = inksvg.create_inkscape_document(
                self.options.doc_width,
                self.options.doc_height,
                doc_units=self.options.doc_units,
            )
            self.svg = inksvg.InkscapeSVGContext(document)
        else:
            try:
                if self.options.input_file:
                    with self.options.input_file.open(encoding='utf8') as f:
                        self.svg = inksvg.InkscapeSVGContext.parse(f)
                else:
                    self.svg = inksvg.InkscapeSVGContext.parse(sys.stdin)
            except OSError as e:
                errormsg(f'Unable to parse SVG input: {e}', exit_status=1)

        # Convert display units to doc units once the document is parsed
        self.post_process_options()

        # Create debug layer and context if requested
        if self.options.create_debug_layer:
            self._create_debug_layer(flip_debug_layer)

        # Run the extension
        t_start = time.time()
        try:
            self.effect()
        except ExtensionError as ex:
            errormsg(str(ex), exit_status=1)
        except Exception:  # noqa: BLE001 pylint: disable=broad-exception-caught
            errormsg(traceback.format_exc(), exit_status=-1)
        t_run = time.time() - t_start
        logger.info('Extension effect time: %fs', t_run)

        try:
            if self.options.output_file:
                pp = logger.getEffectiveLevel() == logging.DEBUG
                with self.options.output_file.open('w', encoding='utf8') as f:
                    self.svg.write_document(f, pretty_print=pp)
            else:
                self.svg.write_document(sys.stdout)
        except OSError as e:
            errormsg(f'Unable to write SVG output: {e}', exit_status=1)

    def effect(self) -> None:
        """Extensions override this method to do the actual work.

        Raises:
            ExtensionError if the extension needs to abort for any reason.
        """
        raise ExtensionError('This extension is not implemented...')

    def selected_elements(
        self, selected_only: bool = False
    ) -> Iterator[TElement]:
        """Get selected document elements.

        Tries to get selected elements first.
        If nothing is selected and `selected_only` is False
        then <strike>either the currently selected layer or</strike>
        the document root is returned. The elements
        may or may not be visible.

        Args:
            selected_only: Get selected elements only.
                Default is False.

        Returns:
            A (possibly empty) iterable collection of etree.Elements.
        """
        if self.options.ids:
            for node_id in self.options.ids:
                node = self.svg.get_node_by_id(node_id)
                if node is not None:
                    yield node
        elif not selected_only:
            yield from self.svg.docroot.iterchildren()

    def selected_pathnodes(self) -> Iterator[tuple[TElement, int, int]]:
        """Get selected path nodes.

        Returns:
            An iterable of tuples of the form
            [(path-element, subpath-index, node-index), ...]
        """
        for node_desc in self.options.selected_nodes:
            # ignore malformed node descriptors
            with contextlib.suppress(ValueError):
                path_id, subpath_index, node_index = node_desc.split(':')
                # TODO: cache path nodes
                node = self.svg.get_node_by_id(path_id)
                if node is not None:
                    yield node, int(subpath_index), int(node_index)

    def selected_pathnode_points(self) -> Iterator[geom2d.P]:
        """Get selected path nodes as point coordinates.

        Returns:
            An iterable of (x,y) points.
        """
        for path_elem, subpath_index, node_index in self.selected_pathnodes():
            # TODO: cache subpaths
            xform = self.svg.get_element_transform(path_elem)
            subpaths = geomsvg.svg_element_to_geometry(path_elem, xform)
            path = subpaths[subpath_index]
            yield path[node_index].p1 if node_index < len(path) else path[-1].p2

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI option.

        Subclasses override this to add any option arguments
        that are specific to the extension.

        Args:
            parser: An instance of argparse.ArgumentParser
        """

    def _create_debug_layer(self, flipy: bool) -> None:
        """Create an SVG context and layer for debug output."""
        self.debug_svg = inksvg.InkscapeSVGContext(self.svg.document)
        debug_layer = self.debug_svg.create_layer(
            self.options.debug_layer_name, flipy=flipy
        )
        self.debug_svg.current_parent = debug_layer
        # Init debug drawing module with the debug SVG context
        geom2d.debug.set_svg_context(self.debug_svg)

    def _create_log(
        self,
        log_path: str | os.PathLike | None,
        log_level: str | None,
    ) -> None:
        """Create a log file for debug output.

        Args:
            log_path: Path to log file. If None or empty
                the log path name will be the
                command line invocation name (argv[0]) with
                a '.log' suffix in the user's home directory.
            log_level: Log level:
                'DEBUG', 'INFO', 'WARNING', 'ERROR', or 'CRITICAL'.
                Default is 'DEBUG'.
        """
        if not log_path:
            log_path = pathlib.Path(sys.argv[0]).name
        if not log_level:
            log_level = 'INFO'
        log_path = output_path(
            log_path, default_parent='~', default_suffix='.log'
        )
        logging.basicConfig(
            filename=log_path,
            filemode='w',
            level=log_level.upper(),
        )
        logger.info(
            'Log started %s, level=%s',
            datetime.datetime.now(tz=datetime.timezone.utc),
            logging.getLevelName(logger.getEffectiveLevel()),
        )
        logger.info('HOME = "%s"', os.environ.get('HOME', ''))
        logger.info('PWD = "%s"', os.environ.get('PWD', ''))
        logger.info('DEBUG = "%s"', os.environ.get('DEBUG', ''))
        logger.info('PYTHONPATH = "%s"\n', os.environ.get('PYTHONPATH', ''))

        logger.info('Python version: %s', sys.version)
        logger.info('Python executable: %s', sys.executable)
        logger.info('Python path: [\n%s\n]', ',\n'.join(sys.path))
        logger.info('Selected ids: %s', ', '.join(self.options.ids))
        logger.info(
            'Selected nodes: %s', ', '.join(self.options.selected_nodes)
        )

    def _process_options(self, argv: list | None) -> argparse.Namespace:
        """Set up option spec and parse command line options."""
        # Add the default options that are common to most extensions.
        parser = argparse.ArgumentParser()

        # Options for when the extension is invoked from the command line.
        parser.add_argument(
            '--new-document', action='store_true', help=_('Create new document')
        )
        parser.add_argument(
            '--doc-width', default='500px', help=_('Document width')
        )
        parser.add_argument(
            '--doc-height', default='500px', help=_('Document height')
        )
        parser.add_argument(
            '--doc-units',
            default='px',
            help=_('Document units (in, mm, px, etc)'),
        )
        # This option is used by Inkscape to pass the ids of selected
        # SVG elements
        parser.add_argument(
            '--id',
            action='append',
            dest='ids',
            default=[],
            help=_('Element id of selected object'),
        )
        # This option is used by Inkscape to pass a list of selected
        # Inkscape path nodes.
        # Each list element is a string of the form
        # '<path-id>:<subpath-index>:<node-index>'
        parser.add_argument(
            '--selected-nodes',
            # '--node', # shorter alias
            action='append',
            default=[],
            help=_('id:subpath:position of selected node'),
        )
        # Used by Inkscape extension dialog to keep track of current tab
        parser.add_argument(
            '--active-tab',
        )
        parser.add_argument(
            '--output-file', '-o', type=pathlib.Path, help=_('Output file.')
        )
        parser.add_argument(
            '--create-debug-layer',
            type=inkbool,
            default=False,
            help=_('Create debug layer'),
        )
        parser.add_argument(
            '--debug-layer-name',
            default=f'{self.__class__.__name__.lower()}: debug',
        )
        parser.add_argument(
            '--log-create', type=inkbool, default=False, help='Create log file'
        )
        parser.add_argument('--log-level', default='DEBUG', help=_('Log level'))
        parser.add_argument(
            '--log-filename',
            default=None,
            help=_('Full pathname of log file'),
        )

        # Path to input file if any
        parser.add_argument(
            'input_file',
            nargs='?',
            type=pathlib.Path,
            help='Path name of input file',
        )

        # Allow subclasses to add more options
        self.add_options(parser)

        return parser.parse_args(argv)

    def post_process_options(self) -> None:
        """Fix CLI option values after parsing SVG document.

        Options values that are of type 'docunits' will be converted
        to SVG user units.
        """
        # This needs to be done after the SVG document is parsed
        # so that the document unit can be determined.
        # If it's a new document then the unit type is hopefully
        # specified as a command line option. If not, a default
        # will be used.
        for name, value in vars(self.options).items():
            if isinstance(value, _DocUnits):
                uu_value: float = self.svg.unit2uu(
                    value.value, from_unit=self.svg.ruler_units
                )
                setattr(self.options, name, uu_value)

        logger.info('Inkscape ruler units: %s', self.svg.ruler_units)
        logger.info('svg doc units: %s', self.svg.doc_units)
        logger.info(
            'svg doc width: %s, height: %s',
            self.svg.docroot.get('width'),
            self.svg.docroot.get('height'),
        )
        logger.info(
            'svg view width: %.4f, height: %.4f',
            self.svg.view_width,
            self.svg.view_height,
        )
        logger.info('svg viewBox: %.4f, %.4f, %.4f, %.4f', *self.svg.viewbox)
        logger.info('svg view_scale: %.7f', self.svg.view_scale)


def output_path(
    path: str | os.PathLike,
    auto_incr: bool = False,
    ndigits: int = 4,
    default_parent: str | pathlib.Path | None = None,
    default_stem: str = 'output',
    default_suffix: str | None = None,
) -> pathlib.Path:
    """Generates an absolute file path name based on the specified path.

    The pathname can optionally have an auto-incrementing numeric suffix.

    Args:
        path: Name or path of output file.
        auto_incr: Append an auto-incrementing numeric suffix to the
            file name if True. Default is False.
        ndigits: Number of digits (zero padding) for auto-increment number.
        default_parent: Default parent directory if filepath does not have one.
            Default is none (current directory).
        default_stem: Default filename stem. Default is 'output'.
        default_suffix: Default file extension if filepath does not have one.
            Default is no extension.

    Returns:
        An absolute Path.
    """
    path = pathlib.Path(path)

    # Fix missing parts with defaults
    if not path.stem:
        path = path.with_stem(default_stem)
    if not path.suffix and default_suffix:
        path = path.with_suffix(default_suffix)
    if not path.parent.parts and default_parent:
        path = pathlib.Path(default_parent, path)

    path = resolve_path(path)

    if auto_incr:
        pattern = re.compile(f'{path.stem}.([0-9]+){path.suffix}$')
        # Get the highest numeric suffix from existing files (if any).
        # This seems overly complicated but it takes care of the case
        # where the user deletes a file in the middle of the
        # sequence, which guarantees the newest file will always
        # have the highest numeric suffix.
        num = 0
        for file in path.parent.glob(f'{path.stem}*{path.suffix}'):
            m = pattern.match(file.name)
            if m:
                num = max(num, int(m.group(1)) + 1)
        path = path.with_stem(f'{path.stem}-{num:0{ndigits}d}')

    return path


def resolve_path(path: str | os.PathLike) -> pathlib.Path:
    """Perform HOME (~) expansion and path resolution.

    Creates absolute path and also removes the snap components
    from a path (if any) if it is relative to HOME. This only
    makes sense on Ubuntu.

    Resolves relative paths relative to the user's HOME, not
    to Inkscape's extension location. Inkscape's file picker
    always creates absolute paths, and if a user types in a
    relative path Inkscape assumes it is relative to the CWD
    which is the extension directory, which is aggravating.
    So this tries to deal with hand-typed file paths...
    """
    path = pathlib.Path(path)

    # Strip Inkscape extension CWD if present.
    # This breaks if the user actually specified a file path in the
    # Inkscape extension folder, but that would be silly.
    cwd = pathlib.Path.cwd()
    cre = re.compile(r'.*[\\/]inkscape[\\/].*[\\/]?extensions', re.IGNORECASE)
    if cre.search(str(cwd)) and path.is_relative_to(cwd):
        path = path.relative_to(cwd)

    home = pathlib.Path.home()
    # Strip the annoying snap home parts to get the actual home.
    # This breaks of course if the username is 'snap', in which case
    # it's the user's fault for choosing such a dumb username.
    if 'snap' in home.parts:
        home = pathlib.Path(*home.parts[: home.parts.index('snap')])

    # Insert/expand '~' for relative paths
    if path.is_relative_to('.'):
        if path.parts and path.parts[0] == '~':
            path = pathlib.Path(*path.parts[1:])
        path = home / path

    return path.resolve()  # make it absolute


def inkrgb_to_styles(
    fill: tuple[float, ...] | None = None,
    stroke: tuple[float, ...] | None = None,
    stroke_width: str | float | None = None,
) -> dict:
    """Convert Inkscape INX RGBA values to a style dictionary."""
    stylemap = {}
    if fill:
        color, opacity = css.rgba_to_cssa(fill)
        if opacity == 0:
            color = 'none'
        elif opacity < 1:
            stylemap['fill-opacity'] = f'{opacity:.3f}'
        stylemap['fill'] = color
    if stroke:
        color, opacity = css.rgba_to_cssa(stroke)
        if opacity == 0:
            color = 'none'
        elif opacity < 1:
            stylemap['stroke-opacity'] = f'{opacity:.3f}'
        stylemap['stroke'] = color
        if stroke_width is not None and opacity > 0:
            if isinstance(stroke_width, float):
                stroke_width = f'{stroke_width:.04f}'
            stylemap['stroke-width'] = stroke_width
    return stylemap
