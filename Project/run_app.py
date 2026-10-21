"""
Start the FSAE quarter-car suspension design tool.

    python run_app.py
"""

import multiprocessing
import sys
from pathlib import Path


if __name__ == "__main__":

    # Needed for the sweep's worker processes on Windows (and frozen builds)
    multiprocessing.freeze_support()

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from quartercar.gui import main

    main()
