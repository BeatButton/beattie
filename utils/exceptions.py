class ResponseError(Exception):
    """For throwing in case of a non-200 response status."""
    def __init__(self, *args, code=None, **kwargs):
        self.code = code
        super().__init__(*args, **kwargs)
