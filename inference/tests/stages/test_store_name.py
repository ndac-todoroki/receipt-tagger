"""店名正規化（FR-07）のテスト。

確かめること: 検索の邪魔になる法人格・支店名・全角表記を取り除く。
確かめないこと: OCRの誤読の補正（この段の責務ではない）。
"""

import pytest

from receipt_app.stages.store_name import normalize_store_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("株式会社ローソン", "ローソン"),
        ("(株)マツモトキヨシ", "マツモトキヨシ"),
        ("㈱マツモトキヨシ", "マツモトキヨシ"),
        ("有限会社 まるや商店", "まるや商店"),
    ],
)
def test_法人格を取り除く(raw: str, expected: str) -> None:
    assert normalize_store_name(raw) == expected


def test_空白で区切られた末尾の支店名を取り除く() -> None:
    assert normalize_store_name("ファミリーマート 新宿西口店") == "ファミリーマート"


def test_店で終わる語が店名と続いている場合は取り除かない() -> None:
    assert normalize_store_name("紀伊國屋書店") == "紀伊國屋書店"


def test_全角英数字と全角空白を半角にそろえる() -> None:
    assert normalize_store_name("ＦＡＭＩＬＹ　ＭＡＲＴ") == "FAMILY MART"


@pytest.mark.parametrize("raw", ["", "   ", "株式会社"])
def test_店名が残らない場合はNoneを返す(raw: str) -> None:
    assert normalize_store_name(raw) is None
