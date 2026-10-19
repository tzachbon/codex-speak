"""harness-discussion: select text anywhere, press ▶ on the floating button, hear it read aloud."""
import sys

import truststore


def main():
    truststore.inject_into_ssl()  # the bundled CA list lacks corporate roots that TLS-inspecting networks re-sign with
    if sys.platform == "darwin":
        from .mac.main import main as run
    else:
        from .win.main import main as run
    run()


if __name__ == "__main__":
    main()
