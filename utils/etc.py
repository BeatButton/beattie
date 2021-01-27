import re
from typing import Callable, MutableSequence, TypeVar

from .type_hints import Comparable

T = TypeVar("T")
U = TypeVar("U", bound=Comparable)

SPOILER_EXPR = re.compile(r"\|\|.*?\|\|")


def reverse_insort(
    seq: MutableSequence[U], val: U, lo: int = 0, hi: int = None
) -> None:
    reverse_insort_by_key(seq, val, key=lambda x: x, lo=lo, hi=hi)


def reverse_insort_by_key(
    seq: MutableSequence[T],
    val: T,
    *,
    key: Callable[[T], U],
    lo: int = 0,
    hi: int = None,
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


KB = 2 ** 10
MB = KB * KB
GB = MB * KB


def display_bytes(num_bytes: int) -> str:
    if num_bytes < KB:
        return f"{num_bytes} B"
    elif num_bytes < MB:
        return f"{num_bytes / KB:.2f} KiB"
    elif num_bytes < GB:
        return f"{num_bytes / MB:.2f} MiB"
    else:
        return f"{num_bytes / GB:.2f} GiB"
