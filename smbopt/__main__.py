"""``python -m smbopt`` runs the command-line interface (see ``smbopt.cli``)."""

import sys

from smbopt.cli import main

if __name__ == "__main__":
    sys.exit(main())
