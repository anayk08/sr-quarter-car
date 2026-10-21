"""Allows `python -m quartercar` to start the app."""

import multiprocessing


if __name__ == "__main__":

    multiprocessing.freeze_support()

    from quartercar.gui import main

    main()
