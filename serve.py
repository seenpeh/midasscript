#!/usr/bin/env python3
"""Entry point: `python3 serve.py [--port N] [--data FILE]`.

The endpoints live in `midas/server/api.py`; this script only starts the server.
"""

from midas.cli.serve_cli import main

if __name__ == "__main__":
    main()
