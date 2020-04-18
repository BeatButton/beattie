import re

from typing import MutableSequence, TypeVar, Optional, Callable

from .type_hints import Comparable

T = TypeVar("T")
U = TypeVar("U", bound=Comparable)

SPOILER_EXPR = re.compile(r"\|\|.*?\|\|")


def reverse_insort(
    seq: MutableSequence[U], val: U, lo: int = 0, hi: Optional[int] = None
) -> None:
    reverse_insort_by_key(seq, val, key=lambda x: x, lo=lo, hi=hi)


def reverse_insort_by_key(
    seq: MutableSequence[T],
    val: T,
    *,
    key: Callable[[T], U],
    lo: int = 0,
    hi: Optional[int] = None
) -> None:
    if hi is None:
        hi = len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if key(val) > key(seq[mid]):
            hi = mid
        else:
            lo = mid + 1
    seq.insert(lo, val)


def remove_spoilers(content: str) -> str:
    return SPOILER_EXPR.sub("", content)
