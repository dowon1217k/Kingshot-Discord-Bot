"""Local operator controls. Disabled unless explicitly enabled; never store secrets here."""
import os
from urllib.parse import urlsplit


def live_redemption_enabled():
    return os.getenv("KINGSHOT_ENABLE_LIVE_REDEMPTION", "0") == "1"


def sharing_url():
    if os.getenv("KINGSHOT_ENABLE_CODE_SHARING", "0") != "1":
        return None
    url = os.getenv("KINGSHOT_CODE_SHARING_URL", "")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return url


def secure_service_url(url):
    """HTTPS for remote services; HTTP allowed only for local development servers."""
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return bool(parsed.hostname and not parsed.username and not parsed.password and (
        parsed.scheme == 'https' or (
            parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')
        )
    ))
