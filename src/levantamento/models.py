from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class EAPItem:
    code: str
    name: str
    description: str = ""
    unit: str = ""
    quantity: str = ""
    confidence: float = 0.0
    children: list["EAPItem"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["children"] = [child.to_dict() for child in self.children]
        return data


@dataclass
class MaterialItem:
    description: str
    unit: str = ""
    quantity: str = ""
    source: str = ""
    confidence: float = 0.0
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

