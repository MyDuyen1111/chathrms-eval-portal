"""Portal pages (handbook §4.1), one module per area. All routes sit on one blueprint, so endpoints stay portal.<view>."""
from . import account, admin, evalsets, review, runs  # noqa: F401  importing a module registers its routes
from .cli import register_cli  # noqa: F401
from .common import bp  # noqa: F401
