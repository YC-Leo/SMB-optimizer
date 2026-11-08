#!/usr/bin/env python3
"""Launch the SMB Optimizer Suite web app in your browser (same as ``smb-optimizer gui``).

python run_suite.py            # opens http://127.0.0.1:8051
python run_suite.py --port 9001 --no-browser
"""

import sys

from smbopt.cli import main

if __name__ == "__main__":
    sys.exit(main(["gui", *sys.argv[1:]]))
