from abc import ABCMeta, abstractmethod
from typing import Any

from discord import TextChannel, VoiceChannel, Thread

GuildMessageable = TextChannel | VoiceChannel | Thread


class Comparable(metaclass=ABCMeta):
    @abstractmethod
    def __lt__(self, other: Any) -> bool:
        ...

    @abstractmethod
    def __gt__(self, other: Any) -> bool:
        ...
