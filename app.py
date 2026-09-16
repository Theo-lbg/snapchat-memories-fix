#!/usr/bin/env python3
"""Point d'entrée. Sans argument, lance l'interface graphique. Avec
`--source`/`--output` (ou tout autre argument CLI), lance en ligne de
commande -- voir `python app.py --help`."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from snapfixer.cli import main
    else:
        from snapfixer.gui import main
    raise SystemExit(main())
