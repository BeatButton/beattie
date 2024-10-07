from __future__ import annotations

import logging
from collections import namedtuple
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cog import Crosspost


Language = namedtuple("Language", ("code", "name"))
DONT = Language("xx", "Don't")
ENGLISH = Language("en", "English (default)")


class Translator:
    cog: Crosspost
    api_url: str
    _languages: dict[str, Language]

    def __init__(self, cog: Crosspost, api_url: str, api_key: str):
        self.cog = cog
        self.api_url = api_url
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)
        self._languages = {}

    async def languages(self):
        if not self._languages:
            self.logger.info("fetching language list")
            body = {
                "api_key": self.api_key,
            }
            async with self.cog.session.get(
                f"{self.api_url}/languages", data=body
            ) as resp:
                data = await resp.json()

            self._languages = {
                lang["code"]: Language(lang["code"], lang["name"]) for lang in data
            }
            self._languages["xx"] = DONT

        return self._languages

    async def detect(self, text: str) -> Language:
        self.logger.debug(f"detecting language for: {text}")
        body = {
            "api_key": self.api_key,
            "q": text,
        }
        async with self.cog.session.post(f"{self.api_url}/detect", data=body) as resp:
            data = await resp.json()

        for lang in data:
            if lang["language"] in ("ja", "zh"):
                lang["confidence"] += 20

        lang = max(data, key=lambda el: el["confidence"])

        if lang["confidence"] < 60:
            return DONT

        langs = await self.languages()
        return langs[lang["language"]]

    async def translate(self, text: str, source: str, target: str) -> str:
        self.logger.debug(f"translating from {source} to {target}: {text}")
        body = {
            "api_key": self.api_key,
            "source": source,
            "target": target,
            "q": text,
        }

        async with self.cog.session.post(
            f"{self.api_url}/translate", data=body
        ) as resp:
            data = await resp.json()

        return data["translatedText"]
