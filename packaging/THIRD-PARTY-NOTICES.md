# Packaged runtime notices

Cerberus project code is licensed under Apache 2.0. Bundled runtimes and dependencies retain
their own copyrights and licenses. This document is included in both downloads.

- **Python 3.14:** [source](https://github.com/python/cpython/tree/3.14),
  [license](licenses/Python-LICENSE.txt).
- **Tcl/Tk 8.6** (launcher): [Tcl source](https://github.com/tcltk/tcl),
  [Tk source](https://github.com/tcltk/tk),
  [Tcl terms](licenses/Tcl-license.txt), [Tk terms](licenses/Tk-license.txt).
- **PyInstaller bootloader:** [source](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3),
  [GPL with the bootloader distribution exception](licenses/PyInstaller-COPYING.txt).
- **Qt 6.11.2 and PySide6 6.11.2** (Linux app):
  [Qt source](https://download.qt.io/archive/qt/6.11/6.11.2/single/),
  [PySide source](https://code.qt.io/cgit/pyside/pyside-setup.git/?h=v6.11.2),
  [LGPL 3.0](licenses/LGPL-3.0-only.txt) and its incorporated
  [GPL 3.0 text](licenses/GPL-3.0-only.txt).
  The shared libraries are distributed separately in the application folder;
  they are not statically linked into Cerberus. Modified compatible library
  files may be substituted there. QtWebEngine also carries Chromium's bundled
  third-party notices in its runtime resources.

The `dependency-licenses/` directory contains available license files from the
Python distributions on the build machine. `runtime-info.json` records their
versions and the build's Python version. Frontend-library notices are included
inside the app's `static/vendor/` folder. Upstream source links and this file
must accompany redistributed test builds.
