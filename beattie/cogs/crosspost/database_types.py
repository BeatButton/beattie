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
        if other.__class__.__name__ == self.__class__.__name__:  # for hot reloading
            return (
                _VALMAP[self.value]
                > _VALMAP[other.value]  # pyright: ignore[reportAttributeAccessIssue]
            )
        return NotImplemented

    def __str__(self) -> str:
        return self.value


_VALMAP: dict[str, int] = {
    TextLength.LONG.value: 2,
    TextLength.SHORT.value: 1,
    TextLength.NONE.value: 0,
}
