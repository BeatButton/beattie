import re
from datetime import timedelta
from typing import Callable, MutableSequence, TypeVar
from zoneinfo import ZoneInfo

from .type_hints import Comparable

T = TypeVar("T")
U = TypeVar("U", bound=Comparable)

SPOILER_EXPR = re.compile(r"\|\|.*?\|\|", flags=re.DOTALL)
LINK_EXPR = re.compile(
    r"(http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+)"
)
UTC = ZoneInfo("UTC")


def reverse_insort(seq: MutableSequence[U], val: U, lo: int = 0, hi: int = None):
    reverse_insort_by_key(seq, val, key=lambda x: x, lo=lo, hi=hi)


def reverse_insort_by_key(
    seq: MutableSequence[T],
    val: T,
    *,
    key: Callable[[T], U],
    lo: int = 0,
    hi: int = None,
):
    if hi is None:
        hi = len(seq)
    k = key(val)
    while lo < hi:
        mid = (lo + hi) // 2
        if k > key(seq[mid]):
            hi = mid
        else:
            lo = mid + 1
    seq.insert(lo, val)


def remove_spoilers(content: str) -> str:
    return SPOILER_EXPR.sub("", content)


# fmt: off
KB = 2 ** 10
MB = KB * KB
GB = MB * KB
# fmt: on


def display_bytes(num_bytes: int) -> str:
    if num_bytes < KB:
        return f"{num_bytes} B"
    elif num_bytes < MB:
        return f"{num_bytes / KB:.2f} KiB"
    elif num_bytes < GB:
        return f"{num_bytes / MB:.2f} MiB"
    else:
        return f"{num_bytes / GB:.2f} GiB"


SECOND = 1
MINUTE = SECOND * 60
HOUR = MINUTE * 60
DAY = HOUR * 24


def display_timedelta(delta: timedelta) -> str:
    remainder = int(delta.total_seconds())
    days, remainder = divmod(remainder, DAY)
    hours, remainder = divmod(remainder, HOUR)
    minutes, seconds = divmod(remainder, MINUTE)
    out = []
    if days:
        s = "s" if days != 1 else ""
        out.append(f"{days} day{s}")
    if hours:
        s = "s" if hours != 1 else ""
        out.append(f"{hours} hour{s}")
    if minutes:
        s = "s" if minutes != 1 else ""
        out.append(f"{minutes} minute{s}")
    if seconds or not out:
        s = "s" if seconds != 1 else ""
        out.append(f"{seconds} second{s}")

    return ", ".join(out)
