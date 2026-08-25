#!/usr/bin/env python3
"""Entry point: `python3 timeframes.py [--data FILE] [--tf 1h]`.

Gap detection and resampling live in `midas/data/timeframes.py`.
"""

from midas.cli.timeframes_cli import main

if __name__ == "__main__":
    main()
