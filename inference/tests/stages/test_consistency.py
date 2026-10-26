"""整合性チェック（FR-06）のテスト。

確かめること: 品目金額の合計が、レシートの合計（または小計、外税込みの合計）と合うか。
確かめないこと: 金額の読み取り（品目抽出の段で扱う）。
"""

from receipt_app.stages.consistency import check_consistency


def test_品目の合計が合計金額と一致すればok() -> None:
    result = check_consistency([150, 130], total=280)

    assert result.ok is True
    assert result.items_sum == 280
    assert result.total == 280


def test_品目の合計が合計金額と一致しなければng() -> None:
    assert check_consistency([150, 130], total=300).ok is False


def test_値引きの負の金額も合計に含める() -> None:
    assert check_consistency([300, -30], total=270).ok is True


def test_外税のレシートは小計と一致すればok() -> None:
    assert check_consistency([100, 200], total=324, subtotal=300).ok is True


def test_外税のレシートは品目合計に税額を足して合計と一致すればok() -> None:
    assert check_consistency([100, 200], total=324, tax=24).ok is True


def test_合計金額が読み取れなければ判定しない() -> None:
    result = check_consistency([150], total=None)

    assert result.ok is None
    assert result.items_sum == 150
