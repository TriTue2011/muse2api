"""muse2api — OpenAI-compatible gateway for Meta's official Model API.

Upstream: https://api.meta.ai/v1 (Muse Spark models).
Auth: static META_API_KEY/MODEL_API_KEY, or a key minted via Meta's
OAuth device flow (``python -m muse2api login``). No passwords,
no session cookies, no scraping.
"""

__version__ = "0.1.0"
