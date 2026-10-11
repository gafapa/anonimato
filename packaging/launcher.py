"""Frozen entry point (PyInstaller)."""
import multiprocessing
import os
import sys

if __name__ == "__main__":
    # Windowed executables have no standard streams. Multiprocessing must still be able to report bootstrap errors
    # without raising a second exception and opening a blocking native error dialog.
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    multiprocessing.freeze_support()
    from app.main import main

    main()
