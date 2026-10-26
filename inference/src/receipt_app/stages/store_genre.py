"""店ジャンル判定（FR-09）と判定粒度の決定（FR-10）。"""

from receipt_app.config import GenreMap, Granularity

FALLBACK_STORE_GENRE = "その他"


def store_genre_from_osm_tag(osm_tag: str | None, genre_map: GenreMap) -> str | None:
    """OSMの店種別タグ（例: "shop=convenience"）を店ジャンルに変換する。

    タグが無い（店が見つからない）ときは判定不能として None を返す。
    """
    if osm_tag is None:
        return None
    return genre_map.osm_tag_to_store_genre.get(osm_tag, FALLBACK_STORE_GENRE)


def decide_granularity(store_genre: str | None, genre_map: GenreMap) -> Granularity:
    """店ジャンルから、全体で1ジャンルにするか品目ごとに判定するかを決める。"""
    if store_genre is None:
        return "per_item"
    return genre_map.store_genre_to_granularity.get(store_genre, "per_item")
