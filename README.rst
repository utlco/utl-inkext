======
inkext
======

* Documentation: https://utlco.github.io/utl-inkext
* Repository: https://github.com/utlco/utl-inkext
* License: LGPL v3
* Python: 3.9+

Simple python extension biolerplate package for Inkscape 1.2+.

This is basically a rewrite of the original python extension framework that
shipped with Inkscape 0.91.
The original excuse for the rewrite was that the Inkscape
framework (at the time) was poorly documented,
was missing a lot of functionality that I needed,
had odd behavior with regards to document size/viewport/units,
was python2.7 only, and broke some extensions (mainly my own) when updating
from .91 to .92 and then again to 1.x.

There are no dependencies on any Inkscape packages so extensions
can be run from the command line without having Inkscape installed.

The current Inkscape Python package
`inkex <https://inkscape.gitlab.io/extensions/documentation/>`_
is much more complete now and probably should be used
instead of this for new extensions.

However, this package does include some extras:

* More boilerplate that makes writing extensions a bit easier.
* Allows extensions to run as command line tools without having to install
  Inkscape at all.
* An SVG library that does not require Inkscape.
* Includes an installer for Inkscape extensions that will create
  a virtualenv in the Inkscape extension folder and install
  package dependencies based on the extension metadata (pyproject.toml).
  This makes it possible for extensions to import arbitrary
  third party packages.
  The installer makes it very easy to deploy extensions, especially
  during development using editable packages.


Installation
------------

.. code::

    pip install utl-inkext

