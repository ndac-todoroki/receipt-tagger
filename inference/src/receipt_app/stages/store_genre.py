"""店ジャンル判定（FR-09）と判定粒度の決定（FR-10）。"""

from collections import Counter
from dataclasses import dataclass, field

from receipt_app.config import GenreMap, Granularity
from receipt_app.schemas import JudgeStatus

FALLBACK_STORE_GENRE = "その他"


@dataclass(frozen=True)
class StoreGenreJudgement:
    """店ジャンルの判定結果。candidates は票の多い順。"""

    genre: str | None
    confidence: float | None
    status: JudgeStatus
    candidates: list[str] = field(default_factory=list)


def judge_store_genre(
    osm_tags: list[str], genre_map: GenreMap, min_confidence: float
) -> StoreGenreJudgement:
    """検索で得たOSM店種別タグ（例: "shop=convenience"）から店ジャンルを決める。

    同名の店が複数ヒットするため、各タグを店ジャンルに変換して多数決をとり、
    最多票の割合を信頼度とする。タグが無ければ判定不能。
    """
    if not osm_tags:
        return StoreGenreJudgement(genre=None, confidence=None, status="unknown")
    votes = Counter(
        genre_map.osm_tag_to_store_genre.get(tag, FALLBACK_STORE_GENRE) for tag in osm_tags
    )
    ranked = [genre for genre, _ in votes.most_common()]
    confidence = votes[ranked[0]] / len(osm_tags)
    status: JudgeStatus = "confirmed" if confidence >= min_confidence else "uncertain"
    return StoreGenreJudgement(
        genre=ranked[0], confidence=confidence, status=status, candidates=ranked
    )


def store_genre_from_items(
    item_names: list[str], genre_map: GenreMap
) -> StoreGenreJudgement | None:
    """品名に決め手の語（例: 調剤）を含む行があれば、その語の店ジャンルに確定する。

    無ければ None。
    """
    for keyword, genre in genre_map.item_keyword_to_store_genre.items():
        if any(keyword in name for name in item_names):
            return StoreGenreJudgement(
                genre=genre, confidence=1.0, status="confirmed", candidates=[genre]
            )
    return None


def decide_granularity(store_genre: str | None, genre_map: GenreMap) -> Granularity:
    """店ジャンルから、全体で1ジャンルにするか品目ごとに判定するかを決める。"""
    if store_genre is None:
        return "per_item"
    return genre_map.store_genre_to_granularity.get(store_genre, "per_item")
