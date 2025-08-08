from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fragment import Fragment


class DownloadError(Exception):
    def __init__(self, source: Exception, fragment: Fragment):
        self.source = source
        self.fragment = fragment
