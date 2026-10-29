"""OCRの文字の箱を行にまとめる処理のテスト。

確かめること: 縦位置が近い箱を1行にし、行の中は左から並べる。
確かめないこと: 文字の読み取り（OCRモデルの責務）。
"""

from receipt_app.stages.lines import OcrBox, group_rows


def _box(text: str, x: float, y: float, w: float = 50, h: float = 20) -> OcrBox:
    return OcrBox(text=text, score=0.9, box=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


def test_同じ高さの箱は左から順に1行にまとめる() -> None:
    rows = group_rows([_box("¥150", 300, 102), _box("おにぎり", 10, 100)])

    assert [row.text for row in rows] == ["おにぎり ¥150"]


def test_縦に箱の高さの半分以上ずれていれば別の行にする() -> None:
    rows = group_rows([_box("合計", 10, 130), _box("おにぎり", 10, 100)])

    assert [row.text for row in rows] == ["おにぎり", "合計"]


def test_箱が無ければ行も無い() -> None:
    assert group_rows([]) == []
