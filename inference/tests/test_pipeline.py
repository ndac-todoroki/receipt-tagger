"""各段を組み立てたパイプラインのテスト。

確かめること: 段のつなぎ方（店名の候補を順に検索する、判定粒度で品目の分類を切り替える、
            検索の失敗を判定不能にする、値引きを分類しない）。
確かめないこと: 各段の中身（段ごとのテストで扱う）。読み取り・検索・分類器は偽物を使う。
"""

from pathlib import Path

from PIL import Image

from receipt_app.config import AppConfig, load_config
from receipt_app.pipeline import Pipeline
from receipt_app.schemas import AnalyzeResult
from receipt_app.stages.item_genre import ItemGenreJudgement
from receipt_app.stages.receipt import ParsedItem, ParsedReceipt

CONFIG = load_config(Path(__file__).resolve().parents[2] / "config")


class FakeReader:
    def __init__(self, receipt: ParsedReceipt) -> None:
        self.receipt = receipt

    def read(self, image: Image.Image) -> ParsedReceipt:
        return self.receipt


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


def _receipt(store: str, *items: tuple[str, int], total: int) -> ParsedReceipt:
    return ParsedReceipt(
        store_candidates=[store],
        items=[ParsedItem(name=n, amount=a) for n, a in items],
        total=total,
    )


def _run(
    receipt: ParsedReceipt, tags: dict[str, list[str] | None], config: AppConfig = CONFIG
) -> tuple[AnalyzeResult, FakeSearch, FakeItemClassifier]:
    search, classifier = FakeSearch(tags), FakeItemClassifier()
    pipeline = Pipeline(
        config=config, reader=FakeReader(receipt), search=search, item_classifier=classifier
    )
    return pipeline.analyze(Image.new("RGB", (10, 10))), search, classifier


def test_店名の候補を順に検索し最初に見つかった店で店ジャンルを決める() -> None:
    receipt = ParsedReceipt(
        store_candidates=["サンプルマート", "サンブルマ"],
        items=[ParsedItem(name="ポテチ", amount=150)],
        total=150,
    )

    result, search, _ = _run(receipt, {"サンブルマ": ["shop=convenience"]})

    assert search.queries == ["サンプルマート", "サンブルマ"]
    assert result.store.name == "サンブルマ"
    assert result.store.genre == "コンビニ"


def test_品目ごとに判定する店では品目ジャンルを分類する() -> None:
    receipt = _receipt("サンプルマート", ("ポテチ", 150), total=150)

    result, _, classifier = _run(receipt, {"サンプルマート": ["shop=convenience"]})

    assert result.granularity == "per_item"
    assert result.items[0].genre == "菓子"
    assert classifier.names == ["ポテチ"]


def test_全体で1ジャンルの店では品目を分類しない() -> None:
    receipt = _receipt("サンプル食堂", ("定食", 800), total=800)

    result, _, classifier = _run(receipt, {"サンプル食堂": ["amenity=restaurant"]})

    assert result.granularity == "whole"
    assert classifier.names == []


def test_検索に失敗したら店ジャンルは判定不能にして品目ごとに判定する() -> None:
    receipt = _receipt("サンプルマート", ("ポテチ", 150), total=150)

    result, _, _ = _run(receipt, {"サンプルマート": None})

    assert result.store.status == "unknown"
    assert result.granularity == "per_item"


def test_値引きの行は品目ジャンルを分類しない() -> None:
    receipt = _receipt("サンプルマート", ("ポテチ", 150), ("値引", -20), total=130)

    result, _, classifier = _run(receipt, {"サンプルマート": ["shop=convenience"]})

    assert classifier.names == ["ポテチ"]
    assert result.items[1].genre is None
    assert result.consistency.ok is True
