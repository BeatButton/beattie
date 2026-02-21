from typing import TYPE_CHECKING, NotRequired, TypedDict

from discord import TextChannel, Thread, VoiceChannel

GuildMessageable = TextChannel | VoiceChannel | Thread

if TYPE_CHECKING:

    class BotConfig(TypedDict):
        token: str
        prefixes: list[str]
        test_token: NotRequired[str]
        test_prefixes: NotRequired[list[str]]
        loglevel: NotRequired[str]
        config_password: NotRequired[str]
        debug: NotRequired[bool]
        owner_ids: NotRequired[list[int]]
        api: NotRequired[str]
        gateway: NotRequired[str]
