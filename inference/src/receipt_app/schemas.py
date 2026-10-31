"""APIが返す結果JSONの型。"""

from typing import Literal

from pydantic import BaseModel

# confirmed: 信頼度が閾値以上 / uncertain: 閾値未満で候補から選ばせる / unknown: 判定不能
JudgeStatus = Literal["confirmed", "uncertain", "unknown"]


class StoreResult(BaseModel):
    """店名と店ジャンルの判定結果。"""

    name: str | None
    genre: str | None
    status: JudgeStatus
    candidates: list[str] = []


class ItemResult(BaseModel):
    """品目1行分の抽出・判定結果。"""

    name: str
    quantity: int
    unit_price: int | None
    amount: int
    # その品目に付いた割引の額（正の数）。amount は割引を引いた後の金額
    discount: int = 0
    # genre は品目ジャンルの小分類、category はその大分類
    genre: str | None
    category: str | None = None
    confidence: float | None
    status: JudgeStatus
    candidates: list[str] = []


class ConsistencyResult(BaseModel):
    """品目金額の合計と合計金額の整合性チェック結果。"""

    ok: bool | None
    items_sum: int
    total: int | None


class AnalyzeResult(BaseModel):
    """レシート1枚の解析結果。"""

    store: StoreResult
    granularity: Literal["whole", "per_item"]
    items: list[ItemResult]
    total: int | None
    consistency: ConsistencyResult
    # 品目ジャンルの小分類→大分類。画面で小分類を選び直したときに大分類を引くのに使う
    item_categories: dict[str, str] = {}
