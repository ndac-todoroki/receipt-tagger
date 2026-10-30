"""OCRの文字の箱を行にまとめる処理のテスト。

確かめること: 縦位置が近い箱を1行にし、行の中は左から並べる。
確かめないこと: 文字の読み取り（OCRモデルの責務）。
"""

from receipt_app.stages.ocr_reader.lines import OcrBox, group_rows


def _box(text: str, x: float, y: float, w: float = 50, h: float = 20) -> OcrBox:
    return OcrBox(text=text, score=0.9, box=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


def test_同じ高さの箱は左から順に1行にまとめる() -> None:
    rows = group_rows([_box("¥150", 300, 102), _box("おにぎり", 10, 100)])

    assert [row.text for row in rows] == ["おにぎり ¥150"]


def test_縦に箱の高さの半分以上ずれていれば別の行にする() -> None:
    rows = group_rows([_box("合計", 10, 130), _box("おにぎり", 10, 100)])

    assert [row.text for row in rows] == ["おにぎり", "合計"]


def _tilted_box(text: str, x: float, y: float, slope: float, w: float = 100) -> OcrBox:
    h = 20
    return OcrBox(
        text=text,
        score=0.9,
        box=[[x, y], [x + w, y + w * slope], [x + w, y + w * slope + h], [x, y + h]],
    )


def test_傾いた写真でも傾きを打ち消して同じ行にまとめる() -> None:
    # 右の箱ほど下にずれる（傾き0.1）。ずれは箱の高さの半分を超えるが、同じ行として扱いたい
    slope = 0.1
    rows = group_rows(
        [
            _tilted_box("おにぎり", 0, 100, slope),
            _tilted_box("¥150", 300, 130, slope),
            _tilted_box("お茶", 0, 160, slope),
            _tilted_box("¥130", 300, 190, slope),
        ]
    )

    assert [row.text for row in rows] == ["おにぎり ¥150", "お茶 ¥130"]


def test_箱が少しずつずれて並んでいても全体が1行につながらない() -> None:
    # 直前の箱とだけ比べると、少しずつずれた箱が鎖のようにつながって1行になってしまう
    boxes = [_box(f"t{i}", (i % 2) * 300, 100 + i * 8) for i in range(10)]

    assert len(group_rows(boxes)) > 1


def test_箱が無ければ行も無い() -> None:
    assert group_rows([]) == []
