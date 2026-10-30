"""視覚言語モデル（VLM）による読み取り（FR-03）のテスト。

確かめること: VLM の応答 JSON をレシートの内容に直す、壊れた応答を読み取り失敗にする。
確かめないこと: VLM が正しく読めるか（ml/scripts/eval_vlm.py で実レシートを使って測る）。
"""

import json

import pytest

from receipt_app.stages.receipt import ParsedItem, ReadError
from receipt_app.stages.vlm_reader import parse_receipt_json


def _content(**overrides: object) -> str:
    data: dict[str, object] = {
        "store_name": "サンプルマート",
        "items": [{"name": "ポテチ", "quantity": 1, "unit_price": None, "amount": 150}],
        "subtotal": None,
        "tax": None,
        "total": 150,
    }
    return json.dumps({**data, **overrides}, ensure_ascii=False)


def test_店名と品目と小計と税と合計を受け取る() -> None:
    content = _content(
        items=[
            {"name": "ポテチ", "quantity": 2, "unit_price": 150, "amount": 300},
            {"name": "値引", "quantity": None, "unit_price": None, "amount": -20},
        ],
        subtotal=280,
        tax=22,
        total=302,
    )

    receipt = parse_receipt_json(content)

    assert receipt.store_candidates == ["サンプルマート"]
    assert receipt.items == [
        ParsedItem(name="ポテチ", amount=300, quantity=2, unit_price=150),
        ParsedItem(name="値引", amount=-20),
    ]
    assert (receipt.subtotal, receipt.tax, receipt.total) == (280, 22, 302)


def test_店名は法人格を除いて検索用に整える() -> None:
    receipt = parse_receipt_json(_content(store_name="株式会社サンプルマート"))

    assert receipt.store_candidates == ["サンプルマート"]


@pytest.mark.parametrize("store_name", [None, "", "株式会社"])
def test_店名が読めなければ候補は空にする(store_name: str | None) -> None:
    receipt = parse_receipt_json(_content(store_name=store_name))

    assert receipt.store_candidates == []


@pytest.mark.parametrize("content", ["", "合計は150円です", "[]", '{"items": "x"}'])
def test_形の違う応答は読み取り失敗にする(content: str) -> None:
    with pytest.raises(ReadError):
        parse_receipt_json(content)


def test_金額が整数でない品目は捨てる() -> None:
    content = _content(
        items=[
            {"name": "ポテチ", "quantity": 1, "unit_price": None, "amount": 150},
            {"name": "読めない", "quantity": 1, "unit_price": None, "amount": None},
            {"name": "真偽値", "quantity": 1, "unit_price": None, "amount": True},
            "品目ではない",
        ]
    )

    receipt = parse_receipt_json(content)

    assert [i.name for i in receipt.items] == ["ポテチ"]


def test_小計と税と合計が整数でなければ無いものとする() -> None:
    receipt = parse_receipt_json(_content(subtotal="150", tax=1.5, total=False))

    assert (receipt.subtotal, receipt.tax, receipt.total) == (None, None, None)
