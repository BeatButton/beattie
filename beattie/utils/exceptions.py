from typing import Any


class ResponseError(Exception):
    """For throwing in case of a non-200 response status."""

    def __init__(self, code: int = None, url: str = None, *args: Any):
        self.code = code
        self.url = url
        super().__init__(code, *args)
