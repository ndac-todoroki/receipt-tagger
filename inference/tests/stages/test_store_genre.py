"""店ジャンル判定（FR-09）と判定粒度の決定（FR-10）のテスト。

確かめること: OSMの店種別タグを店ジャンルに変換し、店ジャンルから粒度を決める。
確かめないこと: OSMへの問い合わせ（検索クライアントのテストで扱う）。
"""

from receipt_app.config import GenreMap
from receipt_app.stages.store_genre import decide_granularity, store_genre_from_osm_tag

GENRE_MAP = GenreMap(
    osm_tag_to_store_genre={"shop=convenience": "コンビニ", "amenity=restaurant": "飲食店"},
    store_genre_to_granularity={"コンビニ": "per_item", "飲食店": "whole", "その他": "per_item"},
)


def test_対応表にあるタグは店ジャンルに変換する() -> None:
    assert store_genre_from_osm_tag("shop=convenience", GENRE_MAP) == "コンビニ"


def test_対応表にないタグはその他にする() -> None:
    assert store_genre_from_osm_tag("shop=bakery", GENRE_MAP) == "その他"


def test_タグが無ければ判定不能としてNoneを返す() -> None:
    assert store_genre_from_osm_tag(None, GENRE_MAP) is None


def test_店ジャンルに応じた粒度を返す() -> None:
    assert decide_granularity("飲食店", GENRE_MAP) == "whole"
    assert decide_granularity("コンビニ", GENRE_MAP) == "per_item"


def test_店ジャンルが判定不能なら品目ごとに判定する() -> None:
    assert decide_granularity(None, GENRE_MAP) == "per_item"
