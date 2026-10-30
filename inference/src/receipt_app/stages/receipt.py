"""読み取りの段（FR-03）が返す、レシート1枚の内容の型。

読み取りの方式（VLM・旧方式の OCR＋パーサ）によらず、後ろの段はこの型だけを見る。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedItem:
    """品目1つ。値引きは負の金額の品目として表す。"""

    name: str
    amount: int
    quantity: int = 1
    unit_price: int | None = None


@dataclass(frozen=True)
class ParsedReceipt:
    """レシート1枚から取り出した内容。store_candidates は確からしい順。"""

    store_candidates: list[str] = field(default_factory=list)
    items: list[ParsedItem] = field(default_factory=list)
    subtotal: int | None = None
    tax: int | None = None
    total: int | None = None
