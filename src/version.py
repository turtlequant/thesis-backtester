"""Single source of truth for the application release identity.

For a normal release, edit only ``__version__`` below.  The desktop UI, API,
Python package metadata, BUILD_INFO.json, and Windows artifact names all derive
from this module.
"""

APP_NAME = "Thesis Backtester"
RELEASE_STAGE = "Beta"
__version__ = "0.1.0"

DISPLAY_VERSION = f"{RELEASE_STAGE} v{__version__}"


def app_info() -> dict[str, str]:
    """Return the public application identity used by API clients."""
    return {
        "name": APP_NAME,
        "version": __version__,
        "release_stage": RELEASE_STAGE,
        "display_version": DISPLAY_VERSION,
    }
