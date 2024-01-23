#!/usr/bin/env python3
"""Install Inkscape extensions.

This pretty much only works on Linux or maybe MacOS.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
from typing import Any, NoReturn, TextIO

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


def main() -> None:
    """Inkscape extension installer."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'root',
        metavar='extension-path',
        type=pathlib.Path,
        nargs='?',
        default='.',
        help='Extension project root path',
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
        '--dev',
        action='store_true',
        help='Install in dev environment (as editable packages)',
    )
    args = parser.parse_args()

    root_path = args.root.expanduser().resolve()

    # Get project info from pyproject.toml
    pyproj_path = verify_path(root_path / 'pyproject.toml')
    with pyproj_path.open('rb') as fp:
        data = tomllib.load(fp)
        proj_name = data['project'].get('name', root_path.name)
        dependencies = data['project'].get('dependencies', [])

    # Location of installed Inkscape extensions
    inkext_path = pathlib.Path(INKEXT_DIR, proj_name).expanduser().resolve()
    inkext_path.mkdir(parents=True, exist_ok=True)

    if args.uninstall:
        if not args.quiet:
            print(f'Removing {inkext_path}')
        shutil.rmtree(str(inkext_path), ignore_errors=True)
        sys.exit()

    # Get a list of extension INX files to install
    inx_dir = verify_path(root_path / INX_DIR, is_dir=True)
    inx_files = list(inx_dir.glob('*.inx'))
    if not inx_files:
        if not args.quiet:
            print('Nothing to install.')
        sys.exit()

    try:
        install_all(
            root_path,
            inx_files,
            inkext_path,
            dependencies,
            args.quiet,
            args.dev,
        )
    except subprocess.CalledProcessError as e:
        if e.stdout:
            print(e.stdout)
        exit_error(e.stderr)


def install_all(
    root_path: pathlib.Path,
    inx_files: list[pathlib.Path],
    inkext_path: pathlib.Path,
    dependencies: list[str],
    is_quiet: bool,
    is_dev: bool,
) -> None:
    """Install extensions and create virtualenv."""
    # Create a virtualenv and install dependencies
    venv_path = inkext_path / VENV_DIR
    if not venv_path.exists():
        if not is_quiet:
            print(f'Creating virtualenv: {venv_path}')
        create_venv(root_path, venv_path, dependencies, is_dev=is_dev)

    for inx_path in inx_files:
        if not is_quiet:
            print(f'Installing {inx_path.stem} to {inkext_path}')
        install_ext(inx_path, inkext_path, venv_path, is_dev=is_dev)


def install_ext(
    inx_path: pathlib.Path,
    inkext_path: pathlib.Path,
    venv_path: pathlib.Path,
    is_dev: bool = False,
) -> None:
    """Install the extension."""
    dest_path = inkext_path / inx_path.name

    # Create a shell stub to execute the venv python stub.
    shtub_path = dest_path.with_suffix('.sh')
    with shtub_path.open('w') as f:
        f.write(
            SH_TEMPLATE.format(
                extname=inx_path.stem, venv_path=venv_path, is_dev=is_dev
            )
        )
    shtub_path.chmod(0o775)

    if dest_path.exists():
        dest_path.unlink()

    if is_dev:
        run('ln', '-s', str(inx_path), str(dest_path))
    else:
        shutil.copyfile(inx_path, dest_path)


def verify_path(path: pathlib.Path, is_dir: bool = False) -> pathlib.Path:
    """Create a path and verify that it exists and is of the correct type."""
    if not path.exists():
        exit_error(f'Unable to find {path}.')
    if path.is_dir() != is_dir:
        ftype = 'directory' if is_dir else 'file'
        exit_error(f'{path} is not a {ftype}.')
    return path


def exit_error(
    *args: Any, status: int = 1, file: TextIO = sys.stderr, **kwargs: Any
) -> NoReturn:
    """Print an error message and exit."""
    if args:
        print(*args, file=file, **kwargs)
    sys.exit(status)


def run(*args: str) -> subprocess.CompletedProcess:
    """Run a shell command."""
    return subprocess.run(
        args, capture_output=True, check=True, encoding='utf-8'
    )


def create_venv(
    root_path: pathlib.Path,
    venv_path: pathlib.Path,
    dependencies: list[str],
    is_dev: bool = False,
) -> None:
    """Create a virtualenv and install dependencies."""
    if not venv_path.exists():
        run(PYTHON, '-m', 'venv', str(venv_path))

    venv_python = str(venv_path / 'bin' / 'python')
    pip_args = [venv_python, '-m', 'pip', 'install', '-q']
    if is_dev:
        run(*pip_args, '--no-dependencies', '-e', str(root_path))
        for dep in dependencies:
            if dep.startswith('utl-'):
                proj_path = root_path / '..' / dep
                if not proj_path.exists():
                    exit_error(f'Cannot find project path for {dep}.')
                run(*pip_args, '-e', str(proj_path))
            else:
                run(*pip_args, str(root_path / dep))
    else:
        run(*pip_args, str(root_path))


if __name__ == '__main__':
    main()
