from functools import wraps


def bot_only(func):
    @wraps(func)
    def inner(self, *args, **kwargs):
        if not self.user.bot:
            return
        return func(self, *args, **kwargs)
    return inner
