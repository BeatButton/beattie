from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import namedtuple
from typing import TYPE_CHECKING, Mapping

from beattie.utils.exceptions import ResponseError

if TYPE_CHECKING:
    from .cog import Crosspost


Language = namedtuple("Language", ("code", "name"))
DONT = Language("xx", "Don't")
UNKNOWN = Language("zz", "Unknown")
ENGLISH = Language("en", "English (default)")


class Translator(ABC):
    cog: Crosspost
    api_url: str
    _languages: dict[str, Language]

    def __init__(self, cog: Crosspost, api_url: str, api_key: str):
        self.cog = cog
        self.api_url = api_url
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)
        self._languages = {}

    @abstractmethod
    async def languages(self) -> Mapping[str, Language]: ...

    @abstractmethod
    async def detect(self, text: str) -> Language: ...

    @abstractmethod
    async def translate(self, text: str, source: str, target: str) -> str: ...


class LibreTranslator(Translator):
    async def languages(self) -> Mapping[str, Language]:
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
        if source == "zz":
            source = "auto"
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


class DeeplTranslator(Translator):
    headers: dict[str, str]

    def __init__(self, cog: Crosspost, api_url: str, api_key: str):
        super().__init__(cog, api_url, api_key)
        self.headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}

    async def languages(self) -> Mapping[str, Language]:
        if not self._languages:
            self.logger.info("fetching language list")
            async with self.cog.session.get(
                f"{self.api_url}/languages",
                headers=self.headers,
                params={"type": "target"},
            ) as resp:
                data = await resp.json()

            self._languages = {
                (code := lang["language"].lower()): Language(code, lang["name"])
                for lang in data
            }
            for lang, pref, drop in [
                ("en", "us", "gb"),
                ("pt", "br", "pt"),
            ]:
                self._languages.pop(f"{lang}-{drop}")
                self._languages[lang] = self._languages.pop(f"{lang}-{pref}")
            self._languages["xx"] = DONT
            self._languages["zz"] = UNKNOWN

        return self._languages

    async def detect(self, text: str) -> Language:
        return UNKNOWN

    async def translate(self, text: str, source: str, target: str) -> str:
        data = {"text": [text], "target_lang": target.upper()}
        if source != "zz":
            data["source_lang"] = source.upper()

        try:
            async with self.cog.session.get(
                f"{self.api_url}/translate",
                headers={**self.headers, "'Content-Type": "application/json"},
                data=data,
            ) as resp:
                data = await resp.json()
        except ResponseError as e:
            if e.code == 456:
                self.logger.warning("deepl character limit reached")
                return text
            raise
        else:
            return data["translations"][0]["text"]
