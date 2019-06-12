class ResponseError(Exception):
    """For throwing in case of a non-200 response status."""

    def __init__(self, code=None, url=None, *args):
        self.code = code
        self.url = url
        super().__init__(code, *args)
