"""読み取った品目の後処理（個数の検算、割引のまとめ）のテスト。

確かめること: 単価×個数が金額と合わない個数を1に戻す、品目の直後の割引を直前の品目にまとめる、
            レシート全体への値引きはまとめない。
確かめないこと: 読み取りそのもの（読み取りの段のテストで扱う）。
"""

from receipt_app.stages.item_cleanup import fix_quantities, merge_discounts
from receipt_app.stages.receipt import ParsedItem


def test_単価と個数の積が金額と合えば個数をそのまま使う() -> None:
    items = [ParsedItem(name="ポテチ", amount=300, quantity=2, unit_price=150)]

    assert fix_quantities(items) == items


def test_単価と個数の積が金額と合わなければ個数を1に戻す() -> None:
    # 税区分の「外8」を個数と読んだ場合
    items = [ParsedItem(name="ポテチ", amount=150, quantity=8, unit_price=150)]

    assert fix_quantities(items) == [ParsedItem(name="ポテチ", amount=150)]


def test_単価が無いのに個数が2以上なら個数を1に戻す() -> None:
    items = [ParsedItem(name="ポテチ", amount=160, quantity=8)]

    assert fix_quantities(items) == [ParsedItem(name="ポテチ", amount=160)]


def test_品目の直後の割引は直前の品目にまとめる() -> None:
    items = [
        ParsedItem(name="牛乳", amount=200),
        ParsedItem(name="割引", amount=-50),
        ParsedItem(name="パン", amount=150),
    ]

    assert merge_discounts(items) == [
        ParsedItem(name="牛乳", amount=150, discount=50),
        ParsedItem(name="パン", amount=150),
    ]


def test_割引が続けば同じ品目にまとめて足し合わせる() -> None:
    items = [
        ParsedItem(name="牛乳", amount=200),
        ParsedItem(name="値引", amount=-50),
        ParsedItem(name="クーポン", amount=-30),
    ]

    assert merge_discounts(items) == [ParsedItem(name="牛乳", amount=120, discount=80)]


def test_先頭にある割引は品目にまとめない() -> None:
    items = [ParsedItem(name="割引", amount=-50), ParsedItem(name="牛乳", amount=200)]

    assert merge_discounts(items) == items


def test_小計や合計への値引きは品目にまとめない() -> None:
    items = [
        ParsedItem(name="牛乳", amount=200),
        ParsedItem(name="小計値引", amount=-20),
        ParsedItem(name="合計から5%引", amount=-9),
    ]

    assert merge_discounts(items) == items
