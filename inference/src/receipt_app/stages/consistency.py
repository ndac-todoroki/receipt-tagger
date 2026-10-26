"""整合性チェック（FR-06）。品目金額の合計とレシートの合計金額を突き合わせる。"""

from receipt_app.schemas import ConsistencyResult


def check_consistency(
    item_amounts: list[int],
    total: int | None,
    subtotal: int | None = None,
    tax: int | None = None,
) -> ConsistencyResult:
    """品目金額の合計が、小計・合計・品目合計＋外税のいずれかと一致するかを判定する。

    合計金額が読み取れていなければ判定せず ok=None とする。
    """
    items_sum = sum(item_amounts)
    if total is None:
        return ConsistencyResult(ok=None, items_sum=items_sum, total=None)
    # 外税のレシートは品目が税抜きで並ぶため、合計とは直接一致しない
    matches = {total}
    if subtotal is not None:
        matches.add(subtotal)
    if tax is not None:
        matches.add(total - tax)
    return ConsistencyResult(ok=items_sum in matches, items_sum=items_sum, total=total)
