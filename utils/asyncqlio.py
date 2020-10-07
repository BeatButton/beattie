from typing import Any


def to_dict(row: Any) -> dict[str, Any]:
    return {k.name: v for k, v in row.to_dict().items()}
