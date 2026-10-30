"""旧方式の読み取り（OCR → 行の組み立て → パーサ）のつなぎ方のテスト。

確かめること: OCR の箱を行にまとめてからパーサに渡す。
確かめないこと: 行の組み立てとパーサの中身（それぞれのテストで扱う）。OCR は偽物を使う。
"""

from PIL import Image

from receipt_app.stages.ocr_reader.lines import OcrBox
from receipt_app.stages.ocr_reader.reader import OcrReceiptReader
from receipt_app.stages.receipt import ParsedItem


class FakeOcr:
    def __init__(self, boxes: list[OcrBox]) -> None:
        self.boxes = boxes

    def read(self, image: Image.Image) -> list[OcrBox]:
        return self.boxes


def _box(text: str, x: int, y: int) -> OcrBox:
    return OcrBox(text=text, score=0.9, box=[[x, y], [x + 80, y], [x + 80, y + 20], [x, y + 20]])


def test_同じ高さの箱を1行にまとめてから品目と合計を取り出す() -> None:
    boxes = [
        _box("サンプルマート", 0, 0),
        _box("2026年10月1日（水）12:00", 0, 40),
        _box("ポテチ", 0, 80),
        _box("¥150", 200, 80),
        _box("合計", 0, 120),
        _box("¥150", 200, 120),
    ]

    receipt = OcrReceiptReader(FakeOcr(boxes)).read(Image.new("RGB", (10, 10)))

    assert receipt.store_candidates == ["サンプルマート"]
    assert receipt.items == [ParsedItem(name="ポテチ", amount=150)]
    assert receipt.total == 150
