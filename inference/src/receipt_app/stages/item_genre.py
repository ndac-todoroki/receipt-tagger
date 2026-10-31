"""品目ジャンル分類（FR-11）。学習なしで、埋め込みの類似度から品目ジャンルを決める。

各ジャンルに代表的な品名の「見本」を用意し（config/item_genre_examples.yaml）、
品名と最も近い見本の類似度をジャンルごとのスコアにする。スコアを温度付きの softmax で
確率にし、最大の確率を信頼度とする。
"""

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import numpy.typing as npt

from receipt_app.config import AppConfig
from receipt_app.schemas import JudgeStatus

MODEL_NAME = "cl-nagoya/ruri-v3-30m"
# Ruri v3 は用途ごとに接頭辞を付ける。分類には「トピック: 」を使う
TOPIC_PREFIX = "トピック: "
CANDIDATE_COUNT = 3


class Encoder(Protocol):
    """文字列を、長さ1に正規化した埋め込みベクトルに変換する。"""

    def encode(self, texts: list[str]) -> npt.NDArray[np.float32]: ...


@dataclass(frozen=True)
class ItemGenreJudgement:
    """品目ジャンルの判定結果。candidates は確率の高い順。判定不能なら genre は None。"""

    genre: str | None
    confidence: float | None
    status: JudgeStatus
    candidates: list[str] = field(default_factory=list)


class _SentenceTransformerEncoder:
    def __init__(self, model_name: str) -> None:
        # 重いライブラリなので、モデルを使うときにだけ読み込む（テストや設定の読み込みを軽くする）
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts: list[str]) -> npt.NDArray[np.float32]:
        vectors = self._model.encode(
            [TOPIC_PREFIX + t for t in texts], normalize_embeddings=True, convert_to_numpy=True
        )
        return np.asarray(vectors, dtype=np.float32)


class EmbeddingItemGenreClassifier:
    """見本の品名との類似度で品目ジャンルを決める分類器。"""

    def __init__(
        self,
        encoder: Encoder,
        examples: dict[str, list[str]],
        min_confidence: float,
        temperature: float,
    ) -> None:
        self._encoder = encoder
        self._genres = list(examples)
        self._min_confidence = min_confidence
        self._temperature = temperature
        all_examples = [e for genre in self._genres for e in examples[genre]]
        self._example_vectors = encoder.encode(all_examples)
        self._example_genre = np.array(
            [i for i, genre in enumerate(self._genres) for _ in examples[genre]]
        )

    @classmethod
    def load(cls, config: AppConfig) -> "EmbeddingItemGenreClassifier":
        """設定の見本と閾値で、埋め込みモデルを読み込んだ分類器を作る。起動時に1回だけ呼ぶ。"""
        return cls(
            encoder=_SentenceTransformerEncoder(MODEL_NAME),
            examples=config.item_genre_examples,
            min_confidence=config.thresholds.item_genre_min_confidence,
            temperature=config.thresholds.item_genre_temperature,
        )

    def classify(self, names: list[str]) -> list[ItemGenreJudgement]:
        """品名ごとに品目ジャンルを判定する。"""
        if not names:
            return []
        similarity = self._encoder.encode(names) @ self._example_vectors.T
        # ジャンルごとに、最も近い見本との類似度をスコアにする
        scores = np.stack(
            [similarity[:, self._example_genre == g].max(axis=1) for g in range(len(self._genres))],
            axis=1,
        )
        logits = scores / self._temperature
        probs = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs /= probs.sum(axis=1, keepdims=True)

        judgements = []
        for row in probs:
            order = np.argsort(-row)
            confidence = float(row[order[0]])
            judgements.append(
                ItemGenreJudgement(
                    genre=self._genres[order[0]],
                    confidence=confidence,
                    status="confirmed" if confidence >= self._min_confidence else "uncertain",
                    candidates=[self._genres[i] for i in order[:CANDIDATE_COUNT]],
                )
            )
        return judgements
