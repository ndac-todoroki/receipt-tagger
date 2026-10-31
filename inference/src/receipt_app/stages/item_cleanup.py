"""読み取った品目の後処理。読み取りの方式によらず、後ろの段に渡す前にかける。

- 個数の検算: VLM は税区分の印（外8・軽8 など）を個数と読むことがある
- 割引のまとめ: レシートでは、品目の割引が次の行に負の金額で印字される
"""

import dataclasses

from receipt_app.stages.receipt import ParsedItem

# レシート全体への値引きを表す語。これを含む負の行は、直前の品目にまとめない
_WHOLE_RECEIPT_WORDS = ("小計", "合計")


def fix_quantities(items: list[ParsedItem]) -> list[ParsedItem]:
    """単価×個数が金額と合わない個数は、読み間違いとみなして1に戻す。"""
    # 実レシート89枚では、個数が2以上の138品のうち78品が単価×個数と金額が合わなかった
    return [
        dataclasses.replace(i, quantity=1, unit_price=None)
        if i.quantity > 1 and (i.unit_price is None or i.unit_price * i.quantity != i.amount)
        else i
        for i in items
    ]


def merge_discounts(items: list[ParsedItem]) -> list[ParsedItem]:
    """品目の直後にある負の金額の行を、割引として直前の品目にまとめる。"""
    merged: list[ParsedItem] = []
    for item in items:
        prev = merged[-1] if merged else None
        if (
            item.amount < 0
            and prev is not None
            and prev.amount + prev.discount > 0
            and not any(w in item.name for w in _WHOLE_RECEIPT_WORDS)
        ):
            merged[-1] = dataclasses.replace(
                prev, amount=prev.amount + item.amount, discount=prev.discount - item.amount
            )
        else:
            merged.append(item)
    return merged
