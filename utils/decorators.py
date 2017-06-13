from functools import wraps


def bot_only(coro):
    @wraps(coro)
    async def inner(self, *args, **kwargs):
        if not self.user.bot:
            return
        return await coro(self, *args, **kwargs)
    return inner
