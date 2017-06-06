def to_dict(row):
    return {k.name: v for k, v in row.to_dict().items()}
