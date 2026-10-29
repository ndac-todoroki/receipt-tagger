"""品目ジャンル分類（FR-11）の判定ロジックのテスト。

確かめること: 品名に最も近い見本のジャンルを選び、信頼度が閾値未満なら未確定にする。
確かめないこと: 埋め込みモデルの精度（docs/evaluation.md の指標で評価する）。
              ここでは文字列を決まったベクトルに写す偽の埋め込みを使う。
"""

import numpy as np
import numpy.typing as npt

from receipt_app.stages.item_genre import EmbeddingItemGenreClassifier

VECTORS = {
    "緑茶": [1.0, 0.0, 0.0],
    "ポテトチップス": [0.0, 1.0, 0.0],
    "ハンガー": [0.0, 0.0, 1.0],
    "お茶 500ml": [0.9, 0.1, 0.0],
    "あいまいな品": [0.5, 0.5, 0.1],
}


class FakeEncoder:
    def encode(self, texts: list[str]) -> npt.NDArray[np.float32]:
        vectors = np.array([VECTORS[t] for t in texts], dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _classifier(min_confidence: float = 0.5) -> EmbeddingItemGenreClassifier:
    return EmbeddingItemGenreClassifier(
        encoder=FakeEncoder(),
        examples={"飲料": ["緑茶"], "菓子": ["ポテトチップス"], "雑貨": ["ハンガー"]},
        min_confidence=min_confidence,
        temperature=0.05,
    )


def test_最も近い見本のジャンルを選ぶ() -> None:
    [judged] = _classifier().classify(["お茶 500ml"])

    assert judged.genre == "飲料"
    assert judged.status == "confirmed"


def test_信頼度が閾値未満なら未確定にして上位の候補を出す() -> None:
    [judged] = _classifier(min_confidence=0.9).classify(["あいまいな品"])

    assert judged.status == "uncertain"
    assert set(judged.candidates[:2]) == {"飲料", "菓子"}


def test_品名が無ければ空のリストを返す() -> None:
    assert _classifier().classify([]) == []
