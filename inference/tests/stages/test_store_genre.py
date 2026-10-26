"""店ジャンル判定（FR-09）と判定粒度の決定（FR-10）のテスト。

確かめること: 検索で得た複数のOSM店種別タグを店ジャンルに変換し、多数決で1つに決める。
            店ジャンルから粒度を決める。
確かめないこと: OSMへの問い合わせ（検索クライアントのテストで扱う）。
"""

import pytest

from receipt_app.config import GenreMap
from receipt_app.stages.store_genre import decide_granularity, judge_store_genre

GENRE_MAP = GenreMap(
    osm_tag_to_store_genre={
        "shop=convenience": "コンビニ",
        "shop=chemist": "ドラッグストア",
        "amenity=pharmacy": "ドラッグストア",
        "shop=supermarket": "スーパー",
        "amenity=restaurant": "飲食店",
    },
    store_genre_to_granularity={
        "コンビニ": "per_item",
        "飲食店": "whole",
        "その他": "per_item",
    },
)


def test_同じ店ジャンルになるタグは合算して多数決で決める() -> None:
    judged = judge_store_genre(
        ["shop=chemist", "amenity=pharmacy", "shop=supermarket"], GENRE_MAP, min_confidence=0.5
    )

    assert judged.genre == "ドラッグストア"
    assert judged.confidence == pytest.approx(2 / 3)
    assert judged.status == "confirmed"


def test_対応表にないタグはその他として票に数える() -> None:
    judged = judge_store_genre(["shop=bakery"], GENRE_MAP, min_confidence=0.5)

    assert judged.genre == "その他"


def test_信頼度が閾値未満なら未確定にして票の多い順に候補を出す() -> None:
    judged = judge_store_genre(
        ["shop=supermarket", "shop=convenience", "shop=convenience", "shop=bakery"],
        GENRE_MAP,
        min_confidence=0.6,
    )

    assert judged.status == "uncertain"
    assert judged.candidates[0] == "コンビニ"
    assert set(judged.candidates) == {"コンビニ", "スーパー", "その他"}


def test_タグが1つも無ければ判定不能() -> None:
    judged = judge_store_genre([], GENRE_MAP, min_confidence=0.5)

    assert judged.genre is None
    assert judged.status == "unknown"


def test_店ジャンルに応じた粒度を返す() -> None:
    assert decide_granularity("飲食店", GENRE_MAP) == "whole"
    assert decide_granularity("コンビニ", GENRE_MAP) == "per_item"


def test_店ジャンルが判定不能なら品目ごとに判定する() -> None:
    assert decide_granularity(None, GENRE_MAP) == "per_item"
