#!/usr/bin/env python3
"""Entry point: `python3 optimize.py [options]`.

The walk-forward machinery lives in `midas/optimizer/` — `space.py` holds the
search space, `objective.py` what "better" means, `walkforward.py` the folds.
"""

from midas.cli.optimize_cli import main

if __name__ == "__main__":
    main()
