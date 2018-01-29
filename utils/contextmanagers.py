import os

import aiofiles
from aiohttp import ServerDisconnectedError

from .exceptions import ResponseError


class null:
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc, tb):
        pass

    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc, tb):
        pass


class tmp_dl:
    """Downloads a file and returns an asynchronous handle to it,
    deleting it after the with block."""
    def __init__(self, session, url, encoding='utf8'):
        self.url = url
        self.session = session
        self.encoding = encoding
        self.path = f'tmp/{self.url.rpartition("/")[-1]}'
        self.file = None

    async def __aenter__(self):
        if not os.path.isdir('tmp'):
            os.mkdir('tmp')

        async with aiofiles.open(self.path, 'wb') as file:
            async with get(self.session, self.url) as resp:
                async for block in resp.content.iter_any():
                    await file.write(block)
        self.file = await aiofiles.open(self.path, encoding=self.encoding)
        return self.file

    async def __aexit__(self, exc_type, exc, tb):
        if self.file:
            await self.file.close()
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


class get:
    """Returns a response to a URL."""
    def __init__(self, session, url, **kwargs):
        self.session = session
        self.url = url
        headers = kwargs.get('headers', {})
        if 'Accept-Encoding' not in headers:
            headers['Accept-Encoding'] = 'gzip, deflate, sdch'
        if 'user-agent' not in headers:
            headers['user-agent'] = 'BeattieBot/1.0 (BeatButton)'
        kwargs['headers'] = headers
        if 'timeout' not in kwargs:
            kwargs['timeout'] = None
        self.kwargs = kwargs

    async def __aenter__(self):
        try:
            self.resp = await self.session.get(self.url, **self.kwargs)
        except ServerDisconnectedError:
            return await self.__aenter__()
        if self.resp.status != 200:
            self.resp.close()
            raise ResponseError(code=self.resp.status)
        return self.resp

    async def __aexit__(self, exc_type, exc, tb):
        self.resp.close()
