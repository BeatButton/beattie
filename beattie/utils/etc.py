import re
from collections.abc import MutableSequence
from datetime import timedelta
from typing import Callable, TypeVar
from zoneinfo import ZoneInfo

from discord.ext.commands import Context
from discord.utils import DEFAULT_FILE_SIZE_LIMIT_BYTES

from .type_hints import Comparable

T = TypeVar("T")
U = TypeVar("U", bound=Comparable)

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


def spoiler_spans(text: str) -> list[tuple[int, int]]:
    """Returns indices substrings in spoilers (inclusive left, exclusive right)"""
    spans = []
    start = 0
    while True:
        try:
            left = text.index("||", start) + 2
            right = text.index("||", left)
        except ValueError:
            break
        else:
            start = right + 2
            spans.append((left, right))

    return spans


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


MD_TRANS = [
    (re.compile(rf"</?{tag}>"), mkd)
    for tag, mkd in [("i", "*"), ("b", "**"), ("u", "__"), ("s", "~~")]
]

BB_TRANS = [
    (re.compile(rf"\[/?{tag}\]"), mkd)
    for tag, mkd in [("i", "*"), ("b", "**"), ("u", "__"), ("s", "~~")]
]

BB_NOOP = [
    re.compile(rf"\[/?{tag}[^\]]*\]")
    for tag in [
        "color",
        "center",
        "t",
        "section",
        "iconname",
    ]
]

BB_STRIP = [re.compile(rf"\[{tag}[^\]]*\].*\[/{tag}\]") for tag in ["hugethumb"]]

BB_URL = re.compile(r"\[url=(.+)\](.+)\[/url\]")

URL_EXPR = re.compile(r"https?://[\w.-]+(?:\.[\w\.-]+)+[\w\-\._~:/?#[@!$&'()*+,;=.\]]+")
INVITE_EXPR = re.compile(
    r"(`?)(?:https?://)?discord(?:(?:app)?\.com/invite|\.gg)/(\w+)\1",
    flags=re.IGNORECASE,
)


def translate_markdown(text: str) -> str:
    for expr, mkd in MD_TRANS:
        text = expr.sub(mkd, text)
    text = re.sub(r"<br ?/?>", "\n", text)
    return text


def translate_bbcode(text: str) -> str:
    for expr, mkd in BB_TRANS:
        text = expr.sub(mkd, text)
    for expr in [*BB_NOOP, *BB_STRIP]:
        text = expr.sub("", text)
    text = BB_URL.sub(r"[\2](\1)", text)
    return text


def get_size_limit(ctx: Context) -> int:
    if guild := ctx.guild:
        return guild.filesize_limit
    else:
        return DEFAULT_FILE_SIZE_LIMIT_BYTES


def replace_ext(name: str, ext: str) -> str:
    return f"{name.rpartition('.')[0]}.{ext}"
