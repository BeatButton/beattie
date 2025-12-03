from enum import Enum
from functools import total_ordering


class SentMessages:
    __slots__ = ("author_id", "message_ids")
    author_id: int
    message_ids: list[int]

    def __init__(self, author_id: int, message_ids: list[int]):
        self.author_id = author_id
        self.message_ids = message_ids


@total_ordering
class TextLength(Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"

    def __gt__(self, other: object) -> bool:
        if isinstance(other, TextLength):
            return _VALMAP[self] > _VALMAP[other]
        return NotImplemented


_VALMAP = {
    TextLength.LONG: 2,
    TextLength.SHORT: 1,
    TextLength.NONE: 0,
}
