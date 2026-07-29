"""Punto de entrada: `python3 -m scanqueue ...`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
