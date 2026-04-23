# Locus Photo - a photo viewer with GPS metadata editing and map integration.
# Copyright (C) 2026 Kyrylo Protsenko
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import atexit
import multiprocessing as mp
from viewer.metadata.exiftool_wrapper import ExifToolWrapper, ExifToolWrapperRegistry
from viewer.app import MainApp


exiftool_registry = ExifToolWrapperRegistry()
exiftool = ExifToolWrapper()
exiftool_registry.add_wrapper(exiftool)


def cleanup():
    exiftool_registry.terminate()


atexit.register(cleanup)


if __name__ == '__main__':

    # Pyinstaller fix
    mp.freeze_support()

    app = MainApp(exiftool_registry, exiftool)
    app.run()
