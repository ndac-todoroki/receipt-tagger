"""OCRが返す文字の箱を、レシートの行にまとめる。"""

from dataclasses import dataclass


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


@dataclass(frozen=True)
class Row:
    """レシートの1行。text は箱の文字列を左から空白区切りで連結したもの。"""

    boxes: list[OcrBox]

    @property
    def text(self) -> str:
        return " ".join(b.text for b in self.boxes)


def group_rows(boxes: list[OcrBox]) -> list[Row]:
    """縦位置の近い箱を1行にまとめ、上から順に返す。"""
    groups: list[list[OcrBox]] = []
    for box in sorted(boxes, key=lambda b: b.center_y):
        # 直前の行の最後の箱と比べるので、少し傾いた写真でも行が途切れにくい
        if groups and abs(box.center_y - groups[-1][-1].center_y) < box.height * 0.5:
            groups[-1].append(box)
        else:
            groups.append([box])
    return [Row(boxes=sorted(g, key=lambda b: b.left)) for g in groups]
