def reverse_insort(seq, val, lo=0, hi=None):
    if hi is None:
        hi = len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if val > seq[mid]:
            hi = mid
        else:
            lo = mid + 1
    seq.insert(lo, val)


def default_channel(member):
    for channel in member.guild.text_channels:
        if channel.permissions_for(member).send_messages:
            return channel
    return None
