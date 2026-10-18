"""harness-discussion: select text anywhere, press ▶ on the floating button, hear it read aloud."""
import sys


def main():
    if sys.platform == "darwin":
        from .mac.main import main as run
    else:
        from .win.main import main as run
    run()


if __name__ == "__main__":
    main()
