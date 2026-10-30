"""OCRが返す文字の箱を、レシートの行にまとめる。"""

import math
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class OcrBox:
    """OCRが検出した文字列1つ。box は左上から時計回りの4点 [[x, y], ...]。"""

    text: str
    score: float
    box: list[list[float]]

    @property
    def center_y(self) -> float:
        return sum(p[1] for p in self.box) / 4

    @property
    def height(self) -> float:
        ys = [p[1] for p in self.box]
        return max(ys) - min(ys)

    @property
    def left(self) -> float:
        return min(p[0] for p in self.box)

    @property
    def center_x(self) -> float:
        return sum(p[0] for p in self.box) / 4

    @property
    def top_edge_angle(self) -> float:
        (x0, y0), (x1, y1) = self.box[0][:2], self.box[1][:2]
        return math.atan2(y1 - y0, x1 - x0)


@dataclass(frozen=True)
class Row:
    """レシートの1行。text は箱の文字列を左から空白区切りで連結したもの。"""

    boxes: list[OcrBox]

    @property
    def text(self) -> str:
        return " ".join(b.text for b in self.boxes)


def _estimate_tilt(boxes: list[OcrBox]) -> float:
    """写真の傾き（ラジアン）を、横長の箱の上辺の傾きの中央値で見積もる。"""
    angles = [b.top_edge_angle for b in boxes if b.box[1][0] - b.box[0][0] > b.height]
    return median(angles) if angles else 0.0


def group_rows(boxes: list[OcrBox]) -> list[Row]:
    """縦位置の近い箱を1行にまとめ、上から順に返す。

    写真の傾きを打ち消した縦位置で比べる。比べる相手は直前の箱ではなく行全体の平均位置にし、
    少しずつずれた箱が鎖のようにつながってレシート全体が1行になるのを防ぐ。
    """
    if not boxes:
        return []
    tilt = _estimate_tilt(boxes)
    cos, sin = math.cos(tilt), math.sin(tilt)

    def upright_y(b: OcrBox) -> float:
        return b.center_y * cos - b.center_x * sin

    # ロゴなど大きな箱に引きずられないよう、しきい値は箱の高さの中央値から決める
    threshold = median(b.height for b in boxes) * 0.5
    groups: list[tuple[list[OcrBox], list[float]]] = []
    for box in sorted(boxes, key=upright_y):
        y = upright_y(box)
        if groups and abs(y - sum(groups[-1][1]) / len(groups[-1][1])) < threshold:
            groups[-1][0].append(box)
            groups[-1][1].append(y)
        else:
            groups.append(([box], [y]))
    return [Row(boxes=sorted(g, key=lambda b: b.left)) for g, _ in groups]
