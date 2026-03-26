from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class EAPItem:
    descricao: str
    unidade: str = ""
    quantidade: str = ""
    preco_unitario: float = 0.0
    preco_total: float = 0.0
    observacoes: str = ""
    filhos: list["EAPItem"] = field(default_factory=list)
    item: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["filhos"] = [child.to_dict() for child in self.filhos]
        return data


@dataclass
class MaterialItem:
    descricao: str
    unidade: str = ""
    quantidade: str = ""
    origem: str = ""
    confianca: float = 0.0
    categoria: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
