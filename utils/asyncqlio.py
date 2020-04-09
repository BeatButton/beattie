from typing import Any, Dict


def to_dict(row: Any) -> Dict[str, Any]:
    return {k.name: v for k, v in row.to_dict().items()}
