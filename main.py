#!/usr/bin/env python3
"""Entrypoint. See `python main.py --help`."""

import sys

from app.cli import main

if __name__ == "__main__":
    sys.exit(main())
