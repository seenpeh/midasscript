#!/usr/bin/env python3
"""Entry point: `python3 label_serve.py [--port N] [--db FILE]`.

The routes live in `midas/labels/api.py`; this script only starts the server.
"""

from midas.labels.serve import main

if __name__ == "__main__":
    main()
