"""各段を組み立てたパイプラインのテスト。

確かめること: 段のつなぎ方（店名の候補を順に検索する、判定粒度で品目の分類を切り替える、
            検索の失敗を判定不能にする、値引きを分類しない）。
確かめないこと: 各段の中身（段ごとのテストで扱う）。OCR・検索・分類器は偽物を使う。
"""

from pathlib import Path

from PIL import Image

from receipt_app.config import AppConfig, load_config
from receipt_app.pipeline import Pipeline
from receipt_app.schemas import AnalyzeResult
from receipt_app.stages.item_genre import ItemGenreJudgement
from receipt_app.stages.lines import OcrBox

CONFIG = load_config(Path(__file__).resolve().parents[2] / "config")
DATE = "2026年10月1日（水）12:00"


class FakeOcr:
    def __init__(self, rows: list[str]) -> None:
        self.rows = rows

    def read(self, image: Image.Image) -> list[OcrBox]:
        # 1行に1つの箱を、行の高さ20・行間40で縦に並べる
        return [
            OcrBox(text=t, score=0.9, box=[[0, y], [100, y], [100, y + 20], [0, y + 20]])
            for t, y in ((t, i * 40) for i, t in enumerate(self.rows))
        ]


class FakeSearch:
    def __init__(self, tags: dict[str, list[str] | None]) -> None:
        self.tags = tags
        self.queries: list[str] = []

    def search_tags(self, store_name: str) -> list[str] | None:
        self.queries.append(store_name)
        return self.tags.get(store_name, [])


class FakeItemClassifier:
    def __init__(self) -> None:
        self.names: list[str] = []

    def classify(self, names: list[str]) -> list[ItemGenreJudgement]:
        self.names.extend(names)
        return [ItemGenreJudgement(genre="菓子", confidence=0.9, status="confirmed") for _ in names]


def _run(
    rows: list[str], tags: dict[str, list[str] | None], config: AppConfig = CONFIG
) -> tuple[AnalyzeResult, FakeSearch, FakeItemClassifier]:
    search, classifier = FakeSearch(tags), FakeItemClassifier()
    pipeline = Pipeline(config=config, ocr=FakeOcr(rows), search=search, item_classifier=classifier)
    return pipeline.analyze(Image.new("RGB", (10, 10))), search, classifier


def test_店名の候補を順に検索し最初に見つかった店で店ジャンルを決める() -> None:
    rows = ["サンブルマ", "事業者名：株式会社サンプルマート", DATE, "ポテチ ¥150", "合計 ¥150"]

    result, search, _ = _run(rows, {"サンブルマ": ["shop=convenience"]})

    assert search.queries == ["サンプルマート", "サンブルマ"]
    assert result.store.name == "サンブルマ"
    assert result.store.genre == "コンビニ"


def test_品目ごとに判定する店では品目ジャンルを分類する() -> None:
    rows = ["サンプルマート", DATE, "ポテチ ¥150", "合計 ¥150"]

    result, _, classifier = _run(rows, {"サンプルマート": ["shop=convenience"]})

    assert result.granularity == "per_item"
    assert result.items[0].genre == "菓子"
    assert classifier.names == ["ポテチ"]


def test_全体で1ジャンルの店では品目を分類しない() -> None:
    rows = ["サンプル食堂", DATE, "定食 ¥800", "合計 ¥800"]

    result, _, classifier = _run(rows, {"サンプル食堂": ["amenity=restaurant"]})

    assert result.granularity == "whole"
    assert classifier.names == []


def test_検索に失敗したら店ジャンルは判定不能にして品目ごとに判定する() -> None:
    rows = ["サンプルマート", DATE, "ポテチ ¥150", "合計 ¥150"]

    result, _, _ = _run(rows, {"サンプルマート": None})

    assert result.store.status == "unknown"
    assert result.granularity == "per_item"


def test_値引きの行は品目ジャンルを分類しない() -> None:
    rows = ["サンプルマート", DATE, "ポテチ ¥150", "値引 -20", "合計 ¥130"]

    result, _, classifier = _run(rows, {"サンプルマート": ["shop=convenience"]})

    assert classifier.names == ["ポテチ"]
    assert result.items[1].genre is None
    assert result.consistency.ok is True
