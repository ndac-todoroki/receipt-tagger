"""各段を組み立ててレシート1枚を解析する。"""

from PIL import Image

from receipt_app.schemas import (
    AnalyzeResult,
    ConsistencyResult,
    ItemResult,
    StoreResult,
)


def analyze(image: Image.Image) -> AnalyzeResult:
    """レシート画像を解析して結果を返す。

    骨組みの段階なので固定のダミー結果を返す。段を実装したら順に置き換える。
    """
    items = [
        ItemResult(
            name="おにぎり 鮭",
            quantity=1,
            unit_price=150,
            amount=150,
            genre="その他食品",
            confidence=0.92,
            status="confirmed",
        ),
        ItemResult(
            name="緑茶 500ml",
            quantity=1,
            unit_price=130,
            amount=130,
            genre=None,
            confidence=0.41,
            status="uncertain",
            candidates=["飲料", "その他食品"],
        ),
    ]
    items_sum = sum(item.amount for item in items)
    return AnalyzeResult(
        store=StoreResult(name="ダミーマート", genre="コンビニ", status="confirmed"),
        granularity="per_item",
        items=items,
        total=items_sum,
        consistency=ConsistencyResult(ok=True, items_sum=items_sum, total=items_sum),
    )
