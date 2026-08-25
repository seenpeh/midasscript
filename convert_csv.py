#!/usr/bin/env python3
"""Entry point: `python3 convert_csv.py [source.csv] [dest.json]`.

The parsing, cleaning and serialising live in `midas/data/csv_import.py`.
"""

from midas.cli.convert_cli import main

if __name__ == "__main__":
    main()
