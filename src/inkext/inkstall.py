#!/usr/bin/env python3
"""Install Inkscape extensions.

This pretty much only works on Linux or maybe MacOS.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import shutil
import subprocess
import sys
import urllib
import urllib.parse
import urllib.request
import zipfile
from typing import Any, NoReturn, TextIO

import packaging.requirements

try:
    import tomllib
except ImportError:
    import tomli as tomllib

PYTHON = 'python3'


# TODO: Support Windows and MacOS...
INKEXT_DIR = '~/.config/inkscape/extensions/utlco'

INX_DIR = 'inkscape'
VENV_DIR = 'venv'

SH_TEMPLATE = """#!/bin/sh
IS_DEV={is_dev}
EXTNAME={extname}
PYTHON="{venv_path}/bin/python"
INKEXT="{venv_path}/bin/$EXTNAME"

# Create a script with all CLI variables for debugging
if [ $IS_DEV = "True" ]
then
    export DEBUG=True
    DEBUG_SCRIPT="/tmp/$EXTNAME"

    echo "$PYTHON $INKEXT \\\\" > "$DEBUG_SCRIPT"

    # Put all args on separate lines for readability
    for i in "${{@}}"
    do
      printf "%s\\n" "$i" | \\
      sed -E 's/(\\ |\\"|\\(|\\))/\\\\\\1/g ; s/$/ \\\\/' >> "$DEBUG_SCRIPT"
    done
    echo >> "$DEBUG_SCRIPT"
    chmod +x "$DEBUG_SCRIPT"
fi

"$PYTHON" "$INKEXT" "$@"
"""

PYPI_JSON_URL = 'https://pypi.org/pypi/{package}/json'
UTLCO_REPO_URL = 'https://github.com/utlco/{repo}/archive/refs/heads/main.zip'


class Info:
    """Verbose terminal output."""

    is_verbose = False
    is_quiet = False

    def __call__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """For informational messages."""
        if not self.is_quiet:
            print(*args, **kwargs)  # noqa: T201

    def verbose(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """For more verbose terminal output."""
        if not self.is_quiet and self.is_verbose:
            print(*args, **kwargs)  # noqa: T201


_info = Info()


def main() -> None:
    """Inkscape extension installer."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'root',
        metavar='PATH',
        type=pathlib.Path,
        nargs='?',
        default='.',
        help='Extension name or project location. Default is current directory.',
    )
    parser.add_argument(
        '--uninstall',
        action='store_true',
        help='Uninstall an Inkscape extension and exit.',
    )
    parser.add_argument(
        '-q',
        '--quiet',
        action='store_true',
        help='Suppress terminal output.',
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='More informational output to stdout.',
    )
    parser.add_argument(
        '-d',
        '--dev',
        action='store_true',
        help='Install as dev/debug environment (editable packages)',
    )
    options = parser.parse_args()

    _info.is_verbose = options.verbose
    _info.is_quiet = options.quiet

    # Root can be a git repo or a source zip file/url
    # If it contains 'http://' or 'https://' then it's assumed to be
    # a url, otherwise a simple file.
    # The repo will be downloaded and extracted locally in order to
    # be able to read the pyproject.toml.
    # Note: pip install https://github.com/utlco/utl-geom2d/archive/refs/heads/main.zip
    if options.root.parts and options.root.parts[0] in {'http', 'https'}:
        root_path = _fetch_repo(options.root)
    else:
        root_path = options.root.expanduser().resolve()

    # Get project name and dependencies from pyproject.toml
    pyproj_path = _verify_path(root_path / 'pyproject.toml')
    with pyproj_path.open('rb') as fp:
        data = tomllib.load(fp)
        if 'project' not in data:
            exit_error(f'[project] section is missing in {pyproj_path}')
        proj_name = data['project'].get('name', root_path.name)
        dependencies = data['project'].get('dependencies', [])

    # Location of installed Inkscape extensions for this project root
    inkext_path = pathlib.Path(INKEXT_DIR, proj_name).expanduser().resolve()

    if options.uninstall:
        _uninstall(inkext_path)
        sys.exit()

    _info.verbose(f'Installing from {root_path}')

    if not inkext_path.exists():
        _info.verbose(f'Creating directory {inkext_path}')
        inkext_path.mkdir(parents=True)

    # Get a list of extension INX files to install
    inx_dir = _verify_path(root_path / INX_DIR, is_dir=True)
    inx_files = list(inx_dir.glob('*.inx'))
    if not inx_files:
        _info.verbose(f'No INX files found in {inx_dir}')
        _info('Nothing to install.')
        sys.exit()

    try:
        _install_all(
            root_path,
            inx_files,
            inkext_path,
            dependencies,
            options.dev,
        )
    except subprocess.CalledProcessError as e:
        if e.stdout:
            _info.verbose(e.stdout)
        exit_error(e.stderr)


def _install_all(
    root_path: pathlib.Path,
    inx_files: list[pathlib.Path],
    inkext_path: pathlib.Path,
    dependencies: list[str],
    is_dev: bool,
) -> None:
    """Install extensions and create virtualenv."""
    # Create a virtualenv and install dependencies
    venv_path = inkext_path / VENV_DIR
    _create_venv(venv_path)

    _install_dependencies(root_path, venv_path, dependencies, is_dev=is_dev)

    for inx_path in inx_files:
        _info.verbose(f'Installing {inx_path.stem} to {inkext_path}')
        _install_ext(inx_path, inkext_path, venv_path, is_dev=is_dev)


def _install_ext(
    inx_path: pathlib.Path,
    inkext_path: pathlib.Path,
    venv_path: pathlib.Path,
    is_dev: bool = False,
) -> None:
    """Install the extension."""
    dest_path = inkext_path / inx_path.name

    # Create a shell stub to execute the venv python stub.
    shtub_path = dest_path.with_suffix('.sh')
    _info.verbose(f'Creating extension shell script {shtub_path}')
    with shtub_path.open('w', encoding='utf-8') as f:
        f.write(
            SH_TEMPLATE.format(
                extname=inx_path.stem, venv_path=venv_path, is_dev=is_dev
            )
        )
    shtub_path.chmod(0o775)

    if dest_path.exists():
        _info.verbose(f'Removing existing shell script {dest_path}')
        dest_path.unlink()

    if is_dev:
        _info.verbose('Creating link to shell script.')
        _run('ln', '-s', str(inx_path), str(dest_path))
    else:
        _info.verbose(f'Copying shell script to {dest_path}')
        shutil.copyfile(inx_path, dest_path)


def _uninstall(inkext_path: pathlib.Path) -> None:
    if inkext_path.exists():
        _info(f'Removing {inkext_path}')
        shutil.rmtree(str(inkext_path), ignore_errors=True)
    else:
        _info.verbose(f'{inkext_path} does not exist.')
        _info('Nothing to uninstall.')


def _verify_path(path: pathlib.Path, is_dir: bool = False) -> pathlib.Path:
    """Create a path and verify that it exists and is of the correct type."""
    if not path.exists():
        exit_error(f'Unable to find {path}.')
    if path.is_dir() != is_dir:
        ftype = 'directory' if is_dir else 'file'
        exit_error(f'{path} is not a {ftype}.')
    return path


def exit_error(
    *args: Any,  # noqa: ANN401
    status: int = 1,
    file: TextIO = sys.stderr,
    **kwargs: Any,  # noqa: ANN401
) -> NoReturn:
    """Print an error message and exit."""
    if args:
        print(*args, file=file, **kwargs)
    sys.exit(status)


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run a shell command."""
    _info.verbose(*args)
    cp = subprocess.run(args, capture_output=True, check=True, encoding='utf-8')
    if cp.stdout:
        _info.verbose(cp.stdout)
    if cp.stderr:
        _info(cp.stderr)
    return cp


def _fetch_repo(path: pathlib.Path) -> pathlib.Path:
    """Fetch a repo and return a path to the extracted or cloned archive."""
    repo_path = pathlib.Path('.', path.stem)  # default path to repo
    _info.verbose(f'Fetching repo {path} to {repo_path}')
    if path.suffix == '.git':
        # Clone the repo in the current directory
        _run('git', 'clone', '--depth=1', str(path))
    elif path.suffix == '.zip':
        with (
            urllib.request.urlopen(str(path)) as resp,
            zipfile.ZipFile(io.BytesIO(resp.read())) as archive,
        ):
            # The root directory should be the first name in the archive.
            repo_path = pathlib.Path('.', archive.namelist()[0])
            _info.verbose(f'Extracting repo to {repo_path}')
            archive.extractall('.')
    else:
        exit_error('Unrecognized file extension.')

    return repo_path


def _create_venv(
    venv_path: pathlib.Path,
) -> None:
    """Create a virtualenv in extension location."""
    if not venv_path.exists():
        _info(f'Creating virtualenv {venv_path}')
        _run(PYTHON, '-m', 'venv', str(venv_path))
    else:
        _info.verbose(f'Virtualenv at {venv_path} already exists.')


def _install_dependencies(
    root_path: pathlib.Path,
    venv_path: pathlib.Path,
    dependencies: list[str],
    is_dev: bool = False,
) -> None:
    """Install dependencies/requirements."""
    venv_python = str(venv_path / 'bin' / 'python')
    pip_args = [venv_python, '-m', 'pip', 'install', '-q']
    _info.verbose('Installing dependencies...')

    # Install any local packages as editable if they
    # exist in the parent directory.
    if is_dev:
        _info.verbose('Installing dev dependencies...')
        # Install the main package as editable
        _run(*pip_args, '--no-dependencies', '-e', str(root_path))
        for dep in dependencies:
            proj_name = packaging.requirements.Requirement(dep).name
            _info.verbose('Requirement:', proj_name)
            if proj_name.startswith('utl-'):
                proj_path = root_path.parent / proj_name
                _info.verbose(f'Installing editable package from {proj_path}')
                # Install any utlco dependencies as editable.
                # This assumes the project paths are sibling.
                if not proj_path.exists():
                    exit_error(f'Cannot find project source path {proj_path}')
                _run(*pip_args, '-e', str(proj_path))
            else:
                _run(*pip_args, dep)
    else:
        _run(*pip_args, str(root_path))


if __name__ == '__main__':
    main()
