from typing import Any, Optional


class ResponseError(Exception):
    """For throwing in case of a non-200 response status."""

    def __init__(
        self, code: Optional[int] = None, url: Optional[str] = None, *args: Any
    ):
        self.code = code
        self.url = url
        super().__init__(code, *args)
