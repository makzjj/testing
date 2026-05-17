"""myconfig package initializer.

This fixes the incorrect filename that prevented `import myconfig.constants`.
Expose commonly used submodules for convenience.
"""

from . import constants  # re-export constants for direct import
from . import version

__all__ = ["constants", "version"]

