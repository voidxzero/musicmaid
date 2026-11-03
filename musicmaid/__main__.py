"""``python -m musicmaid`` → GUI;  ``python -m musicmaid tui`` → terminal UI;  ``python -m musicmaid cli …``."""
import sys


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("tui", "--tui"):
        from .tui.app import main as tui_main
        tui_main()
        return 0
    if args and args[0] in ("cli", "--cli"):
        from .cli import main as cli_main
        return cli_main(args[1:])
    try:
        from .gui.mainwindow import main as gui_main
    except ImportError as e:  # PySide6 missing (e.g. headless server)
        print(f"GUI unavailable ({e}). Use 'musicmaid-tui' or 'musicmaid-cli'.", file=sys.stderr)
        return 1
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
