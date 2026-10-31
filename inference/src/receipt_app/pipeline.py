"""各段を組み立てて、レシート1枚を解析する。

読み取り（店名候補・品目・合計） → 店の検索と店ジャンル判定
→ 判定粒度の決定 → 品目ジャンル分類 → 整合性チェック
"""

import dataclasses
from pathlib import Path
from typing import Literal, Protocol

from PIL import Image

from receipt_app.config import AppConfig
from receipt_app.schemas import AnalyzeResult, ItemResult, StoreResult
from receipt_app.search import NominatimClient
from receipt_app.stages.consistency import check_consistency
from receipt_app.stages.item_cleanup import fix_quantities, merge_discounts
from receipt_app.stages.item_genre import EmbeddingItemGenreClassifier, ItemGenreJudgement
from receipt_app.stages.llm_item_genre import LlmItemGenreClassifier
from receipt_app.stages.receipt import ParsedItem, ParsedReceipt
from receipt_app.stages.store_genre import (
    StoreGenreJudgement,
    decide_granularity,
    judge_store_genre,
)
from receipt_app.stages.vlm_reader import VlmReceiptReader

# 読み取りの方式。ocr は比較用に残している旧方式（stages/ocr_reader）
ReaderKind = Literal["vlm", "ocr"]
# 品目ジャンルの分類器。embedding は埋め込みの類似度、
# llm は読み取りと同じ LLM の制約付きデコーディング
ItemClassifierKind = Literal["embedding", "llm"]
DEFAULT_VLM_URL = "http://localhost:30000/v1/chat/completions"

# 店名の候補を検索する上限。Nominatim は1秒1回までなので、待ち時間を抑えるため絞る
MAX_STORE_QUERIES = 3


class ReceiptReader(Protocol):
    def read(self, image: Image.Image) -> ParsedReceipt: ...


class StoreSearch(Protocol):
    def search_tags(self, store_name: str) -> list[str] | None: ...


class ItemClassifier(Protocol):
    def classify(self, names: list[str]) -> list[ItemGenreJudgement]: ...


class Pipeline:
    """レシート画像の解析パイプライン。各段は差し替えられる。"""

    def __init__(
        self,
        config: AppConfig,
        reader: ReceiptReader,
        search: StoreSearch,
        item_classifier: ItemClassifier,
    ) -> None:
        self._config = config
        self._reader = reader
        self._search = search
        self._item_classifier = item_classifier

    @classmethod
    def load(
        cls,
        config: AppConfig,
        model_dir: Path | None = None,
        reader: ReaderKind = "vlm",
        vlm_url: str = DEFAULT_VLM_URL,
        item_classifier: ItemClassifierKind = "embedding",
    ) -> "Pipeline":
        """本物のモデルを読み込んだパイプラインを作る。起動時に1回だけ呼ぶ。"""
        return cls(
            config=config,
            reader=VlmReceiptReader(vlm_url) if reader == "vlm" else _load_ocr_reader(model_dir),
            search=NominatimClient(),
            item_classifier=(
                LlmItemGenreClassifier.load(config, vlm_url)
                if item_classifier == "llm"
                else EmbeddingItemGenreClassifier.load(config)
            ),
        )

    def analyze(self, image: Image.Image) -> AnalyzeResult:
        """レシート画像を解析して結果を返す。"""
        receipt = self._reader.read(image)
        receipt = dataclasses.replace(receipt, items=merge_discounts(fix_quantities(receipt.items)))

        store_name, store = self._judge_store(receipt.store_candidates)
        granularity = decide_granularity(
            store.genre if store.status != "unknown" else None, self._config.genre_map
        )
        items = self._judge_items(receipt.items, per_item=granularity == "per_item")
        consistency = check_consistency(
            [i.amount for i in receipt.items],
            total=receipt.total,
            subtotal=receipt.subtotal,
            tax=receipt.tax,
        )
        return AnalyzeResult(
            store=StoreResult(
                name=store_name,
                genre=store.genre,
                status=store.status,
                candidates=store.candidates or self._config.labels.store_genres,
            ),
            granularity=granularity,
            items=items,
            total=receipt.total,
            consistency=consistency,
            item_categories={
                g: self._config.labels.category_of(g) for g in self._config.labels.item_genres
            },
        )

    def _judge_store(self, candidates: list[str]) -> tuple[str | None, StoreGenreJudgement]:
        # ロゴのOCRや事業者名など、候補のどれが店として見つかるかは試すまで分からない
        for name in candidates[:MAX_STORE_QUERIES]:
            tags = self._search.search_tags(name)
            if tags:
                return name, judge_store_genre(
                    tags,
                    self._config.genre_map,
                    min_confidence=self._config.thresholds.store_genre_min_confidence,
                )
        unknown = StoreGenreJudgement(genre=None, confidence=None, status="unknown")
        return (candidates[0] if candidates else None), unknown

    def _judge_items(self, items: list[ParsedItem], per_item: bool) -> list[ItemResult]:
        # 値引きは品物ではないので分類しない
        targets = [i for i in items if per_item and i.amount + i.discount > 0]
        judged = dict(
            zip(
                map(id, targets),
                self._item_classifier.classify([i.name for i in targets]),
                strict=True,
            )
        )
        results = []
        for item in items:
            j = judged.get(id(item))
            results.append(
                ItemResult(
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                    discount=item.discount,
                    genre=j.genre if j else None,
                    category=self._config.labels.category_of(j.genre) if j and j.genre else None,
                    confidence=j.confidence if j else None,
                    status=j.status if j else "confirmed",
                    candidates=j.candidates if j else [],
                )
            )
        return results


def _load_ocr_reader(model_dir: Path | None) -> ReceiptReader:
    # RapidOCR は重いので、旧方式を選んだときだけ読み込む
    from receipt_app.stages.ocr_reader.ocr import RapidOcrReader
    from receipt_app.stages.ocr_reader.reader import OcrReceiptReader

    ocr = RapidOcrReader(model_dir=None if model_dir is None else model_dir / "rapidocr")
    return OcrReceiptReader(ocr)
