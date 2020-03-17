def reverse_insort(seq, val, lo=0, hi=None):
    reverse_insort_by_key(seq, val, key=lambda x: x, lo=lo, hi=hi)


def reverse_insort_by_key(seq, val, *, key, lo=0, hi=None):
    if hi is None:
        hi = len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if key(val) > key(seq[mid]):
            hi = mid
        else:
            lo = mid + 1
    seq.insert(lo, val)
