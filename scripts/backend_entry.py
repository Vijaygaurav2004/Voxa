"""
PyInstaller entry point for the bundled Voxa backend.

This is the standalone equivalent of `python -m voxa.main --server`. It is what
gets frozen into the distributable .app so a friend can double-click Voxa without
installing Python or any dependencies.
"""
import sys


def _run() -> None:
    # Ensure server mode regardless of how the frozen binary is invoked.
    if "--server" not in sys.argv:
        sys.argv.append("--server")
    from voxa.server import start_api_server
    start_api_server(background=False)


if __name__ == "__main__":
    _run()
