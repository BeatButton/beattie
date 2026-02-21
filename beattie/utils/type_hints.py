from typing import TYPE_CHECKING, NotRequired, TypedDict

from discord import TextChannel, Thread, VoiceChannel

GuildMessageable = TextChannel | VoiceChannel | Thread

if TYPE_CHECKING:

    class BotConfig(TypedDict):
        token: str
        prefixes: list[str]
        test_token: str
        test_prefixes: list[str]
        loglevel: NotRequired[str]
        config_password: NotRequired[str]
        debug: NotRequired[bool]
