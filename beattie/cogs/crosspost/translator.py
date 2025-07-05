from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import namedtuple
from typing import TYPE_CHECKING

import Levenshtein
import lingua

from beattie.utils.exceptions import ResponseError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .cog import Crosspost


Language = namedtuple("Language", ("code", "name"))
DONT = Language("xx", "Don't")
UNKNOWN = Language("zz", "Unknown")
ENGLISH = Language("en", "English (default)")


class Translator(ABC):
    cog: Crosspost
    api_url: str
    _lang_task = asyncio.Task[dict[str, Language]] | None

    def __init__(self, cog: Crosspost, api_url: str, api_key: str):
        self.cog = cog
        self.api_url = api_url
        self.api_key = api_key
        self.logger = logging.getLogger(f"{__name__}.{type(self).__name__}")
        self._lang_task = None

    @abstractmethod
    async def languages(self) -> Mapping[str, Language]: ...

    @abstractmethod
    async def detect(self, text: str) -> Language: ...

    @abstractmethod
    async def translate(self, text: str, source: str, target: str) -> str: ...


class HybridTranslator(Translator):
    libre: LibreTranslator
    deepl: DeeplTranslator
    detector: lingua.LanguageDetector

    def __init__(self, cog: Crosspost, libre: LibreTranslator, deepl: DeeplTranslator):
        super().__init__(cog, "", "")
        self.libre = libre
        self.deepl = deepl

    async def _languages(self) -> Mapping[str, Language]:

        deepl_langs = await self.deepl.languages()
        libre_langs = await self.libre.languages()
        shared = set(deepl_langs) & set(libre_langs) - {"xx", "zz"}

        self.detector = lingua.LanguageDetectorBuilder.from_iso_codes_639_1(
            *(getattr(lingua.IsoCode639_1, code.upper()) for code in shared)
        ).build()

        return {
            "xx": DONT,
            "zz": UNKNOWN,
            **{code: libre_langs[code] for code in shared},
        }

    def languages(self) -> asyncio.Task[Mapping[str, Language]]:
        if self._lang_task is None:
            self._lang_task = asyncio.Task(self._languages())
        return self._lang_task

    async def detect(self, text: str) -> Language:
        langs = await self.languages()

        if lang := await asyncio.to_thread(self.detector.detect_language_of, text):
            return langs[lang.iso_code_639_1.name.lower()]
        else:
            return DONT

    async def translate(self, text: str, source: str, target: str) -> str:
        langs = await self.languages()
        if source == "zz":
            source = (await self.detect(text)).code
        if source == DONT or source not in langs:
            return text
        if source in ("ja", "zh", "ko"):
            trans = await self.deepl.translate(text, source, target)
            if Levenshtein.ratio(trans, text) < 0.75:
                return trans

        trans = await self.libre.translate(text, source, target)

        if Levenshtein.ratio(trans, text) < 0.75:
            return trans

        return text


class LibreTranslator(Translator):

    async def _languages(self) -> Mapping[str, Language]:
        self.logger.info("fetching language list")
        body = {
            "api_key": self.api_key,
        }

        resp = await self.cog.session.request(
            "GET", f"{self.api_url}/languages", data=body
        )
        data = resp.json()

        return {
            "xx": DONT,
            "zz": UNKNOWN,
            **{lang["code"]: Language(lang["code"], lang["name"]) for lang in data},
        }

    def languages(self) -> asyncio.Task[Mapping[str, Language]]:
        if self._lang_task is None:
            self._lang_task = asyncio.Task(self._languages())
        return self._lang_task

    async def detect(self, text: str) -> Language:
        self.logger.debug(f"detecting language for: {text}")
        body = {
            "api_key": self.api_key,
            "q": text,
        }
        resp = await self.cog.session.post(f"{self.api_url}/detect", data=body)
        data = resp.json()

        for lang in data:
            if lang["language"] in ("ja", "zh"):
                lang["confidence"] += 20

        lang = max(data, key=lambda el: el["confidence"])

        langs = await self.languages()
        out = langs[lang["language"]]
        conf = lang["confidence"]
        self.logger.debug(f"detected language as {out} {conf}%")
        if conf < 60:
            return DONT
        return out

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

        resp = await self.cog.session.post(f"{self.api_url}/translate", data=body)
        data = resp.json()

        return data["translatedText"]


class DeeplTranslator(Translator):
    headers: dict[str, str]

    def __init__(self, cog: Crosspost, api_url: str, api_key: str):
        super().__init__(cog, api_url, api_key)
        self.headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}

    async def _languages(self) -> Mapping[str, Language]:
        self.logger.info("fetching language list")
        resp = await self.cog.session.get(
            f"{self.api_url}/languages",
            headers=self.headers,
            params={"type": "target"},
        )
        data = resp.json()

        langs = {
            (code := lang["language"].lower()): Language(code, lang["name"])
            for lang in data
        }
        for code, pref, drop in [
            ("en", "us", "gb"),
            ("pt", "br", "pt"),
        ]:
            langs.pop(f"{code}-{drop}")
            lang = langs.pop(f"{code}-{pref}")
            langs[code] = Language(code, lang.name)
        langs["xx"] = DONT
        langs["zz"] = UNKNOWN

        return langs

    def languages(self) -> asyncio.Task[Mapping[str, Language]]:
        if self._lang_task is None:
            self._lang_task = asyncio.Task(self._languages())
        return self._lang_task

    async def detect(self, text: str) -> Language:
        return UNKNOWN

    async def translate(self, text: str, source: str, target: str) -> str:
        self.logger.debug(
            f"{type(self).__name__}: translating from {source} to {target}: {text}"
        )
        data = {
            "text": [text],
            "target_lang": target.upper(),
            "model_type": "prefer_quality_optimized",
        }
        if source != "zz":
            data["source_lang"] = source.upper()

        data = json.dumps(data).encode("utf-8")

        try:
            resp = await self.cog.session.post(
                f"{self.api_url}/translate",
                headers={**self.headers, "Content-Type": "application/json"},
                content=data,
            )
        except ResponseError as e:
            if e.code == 456:
                self.logger.warning("deepl character limit reached")
                return text
            raise
        else:
            return resp.json()["translations"][0]["text"]
