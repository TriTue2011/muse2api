"""python -m muse2api — start the OpenAI-compatible gateway."""
from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s: %(message)s")


def main() -> None:
    from .accounts import Pool
    from .config import load_settings
    from .server import create_app

    settings = load_settings()
    if not settings.accounts:
        print("No accounts: set MUSE_COOKIES or MUSE_COOKIES_FILE first.",
              file=sys.stderr)
        print("Export cookies from a logged-in muse.ai tab in your browser "
              "(e.g. with a cookie-export extension).", file=sys.stderr)
        sys.exit(2)
    pool = Pool([a for a in settings.accounts])
    app = create_app(settings, pool)

    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
