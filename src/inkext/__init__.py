"""Simple Inkscape extension biolerplate package.

This is basically a rewrite of the python extension framework that ships
with Inkscape. The original excuse for the rewrite is that the Inkscape
framework had odd behavior with document size/viewport/units and broke
some extensions when updating from .92 to 1.0.

This package also includes more boilerplate that makes it easier to
write extensions that do not depend on Inkscape to run, making them
useful for scripting without having to invoke Inkscape, which is expensive.
"""

import importlib.metadata

__version__ = importlib.metadata.version('utl-inkext')
