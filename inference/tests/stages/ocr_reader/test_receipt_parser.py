"""レシートの行から店名候補・品目・合計を取り出すルール（FR-04, FR-05）のテスト。

確かめること: 実レシートで見られた行の形（品名と金額の分かれ方、数量表記、外税、
            OCRの読み誤りの癖）から、品目と合計を取り出せる。
確かめないこと: OCRの精度、店名で店を当てられるか（検索の段で扱う）。
テストの行はすべて架空の値で、実レシートの内容は含めない。
"""

import pytest

from receipt_app.stages.ocr_reader.receipt_parser import parse_amount, parse_receipt

DATE = "2026年10月1日（水）12:00"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¥1,080", 1080),
        ("¥1.804", 1804),  # カンマがピリオドに読まれる
        ("*269", 269),  # ¥ が * に読まれる
        ("¥139J", 139),  # 軽減税率の印が末尾に付く
        ("874内", 874),
        ("-30", -30),
        ("¥0", 0),
    ],
)
def test_金額の表記ゆれを数値にする(text: str, expected: int) -> None:
    assert parse_amount(text) == expected


def test_金額でなければNone() -> None:
    assert parse_amount("おにぎり") is None


def test_日付の後から小計の前までの金額付きの行を品目にする() -> None:
    receipt = parse_receipt(
        [
            "サンプルマート",
            DATE,
            "ポテトチップス ¥149",
            "おにぎり 鮭 ¥150",
            "小計 ¥299",
            "合計 ¥299",
        ]
    )

    assert [(i.name, i.amount) for i in receipt.items] == [
        ("ポテトチップス", 149),
        ("おにぎり 鮭", 150),
    ]
    assert receipt.subtotal == 299
    assert receipt.total == 299


@pytest.mark.parametrize(
    ("row", "name"),
    [
        ("01 xポテトチップス ¥149", "ポテトチップス"),
        ("外8 362012スープ春雨 ¥149", "スープ春雨"),
        ("585007めかぶ ¥149", "めかぶ"),
        (">追加トッピング ¥149", "追加トッピング"),
    ],
)
def test_品名の前に付く部門コードや商品コードを取り除く(row: str, name: str) -> None:
    receipt = parse_receipt([DATE, row, "合計 ¥149"])

    assert receipt.items[0].name == name


def test_品名と単価数量と金額が別の行に分かれていてもまとめる() -> None:
    receipt = parse_receipt(
        [DATE, "#021 JAN4900000000000", "木製ハンガー3本組", "@500 × 2 1,000内", "合計 ¥1,000"]
    )

    item = receipt.items[0]
    assert (item.name, item.quantity, item.unit_price, item.amount) == (
        "木製ハンガー3本組",
        2,
        500,
        1000,
    )


def test_括弧付きの単価と数量の行を直前の品名に結び付ける() -> None:
    receipt = parse_receipt([DATE, "チャージ料", "(単¥1,000) *3 ¥3,000", "合計 ¥3,000"])

    item = receipt.items[0]
    assert (item.name, item.quantity, item.unit_price, item.amount) == ("チャージ料", 3, 1000, 3000)


def test_値引きは負の金額の品目として残す() -> None:
    receipt = parse_receipt([DATE, "カフェラテ ¥300", "値引額 -30", "合計 ¥270"])

    assert [(i.name, i.amount) for i in receipt.items] == [("カフェラテ", 300), ("値引額", -30)]


def test_金額が0円の行は品目にしない() -> None:
    receipt = parse_receipt([DATE, "セット ¥500", ">オプション *1 ¥0", "合計 ¥500"])

    assert [i.name for i in receipt.items] == ["セット"]


def test_括弧で囲まれた集計行や税の行は品目にしない() -> None:
    receipt = parse_receipt(
        [DATE, "パン ¥200", "(商品代金 ¥200)", "税率 8%対象 ¥200", "小計 ¥200", "合計 ¥216"]
    )

    assert [i.name for i in receipt.items] == ["パン"]


def test_合計の前にある外税を税額として読む() -> None:
    receipt = parse_receipt(
        [DATE, "パン ¥200", "小計 ¥200", "外税額 8% ¥16", "合計 ¥216", "(内消費税等 8% ¥16)"]
    )

    assert (receipt.subtotal, receipt.tax, receipt.total) == (200, 16, 216)


def test_合計の後にある内税は税額として扱わない() -> None:
    receipt = parse_receipt([DATE, "パン ¥216", "合計 ¥216", "(内消費税等 8% ¥16)"])

    assert receipt.tax is None


def test_合計の文字の間の空白や簡体字の読み誤りを許す() -> None:
    receipt = parse_receipt([DATE, "パン ¥200", "合 计 2点 ¥200"])

    assert receipt.total == 200


def test_日付の行が無くても電話番号などの見出し行は品目にしない() -> None:
    receipt = parse_receipt(["電話：04-0000-0000 レジ#2", "パン ¥200", "合計 ¥200"])

    assert [i.name for i in receipt.items] == ["パン"]


def test_事業者名の行を店名の最優先の候補にする() -> None:
    receipt = parse_receipt(["サンブルマ", "見本町店", "事業者名：株式会社サンプルマート", DATE])

    assert receipt.store_candidates[0] == "サンプルマート"
    assert "サンブルマ" in receipt.store_candidates


def test_住所や電話番号や領収証の行は店名の候補にしない() -> None:
    receipt = parse_receipt(
        ["領収証", "サンプルマート", "東京都千代田区見本町1-1", "TEL 03-0000-0000", DATE]
    )

    assert receipt.store_candidates == ["サンプルマート"]


@pytest.mark.parametrize(("text", "expected"), [("730円", 730), ("¥1,000-", 1000)])
def test_円や末尾のハイフンが付いた金額も読む(text: str, expected: int) -> None:
    assert parse_amount(text) == expected


def test_先頭が0の数字は金額とみなさない() -> None:
    # 「¥0」が「04」のように読まれることがある
    assert parse_amount("04") is None


def test_語に続くハイフンは負の符号とみなさない() -> None:
    assert parse_amount("3丁目26-6") is None


def test_金額の多くに円記号が付くレシートでは円記号の無い数字の行を品目にしない() -> None:
    # レジ担当者名とレジ番号のような行
    receipt = parse_receipt(
        [DATE, "やまだ 5519", "パン ¥200", "牛乳 ¥180", "値引 -20", "小計 ¥360", "合計 ¥360"]
    )

    assert [i.name for i in receipt.items] == ["パン", "牛乳", "値引"]


def test_住所の行は品目にしない() -> None:
    receipt = parse_receipt([DATE, "東京都千代田区見本町1丁目2-3", "パン ¥200", "合計 ¥200"])

    assert [i.name for i in receipt.items] == ["パン"]


def test_JANの行に付いた金額は直前の品名の金額にする() -> None:
    # 印字の位置がずれて、前の品目の金額が次の品目のJANと同じ行に読まれることがある
    receipt = parse_receipt(
        [DATE, "#021 JAN4900000000001", "ハンガー", "#021 JAN4900000000002 874内", "合計 ¥874"]
    )

    assert [(i.name, i.amount) for i in receipt.items] == [("ハンガー", 874)]


def test_読み切れなかった単価の行は品名として扱わない() -> None:
    receipt = parse_receipt([DATE, "ハンガー", "@437 ×", "874内", "合計 ¥874"])

    assert [(i.name, i.amount) for i in receipt.items] == [("ハンガー", 874)]


def test_数字と記号だけの品名は品目にしない() -> None:
    receipt = parse_receipt([DATE, "-1 295", "パン ¥200", "合計 ¥200"])

    assert [i.name for i in receipt.items] == ["パン"]


def test_税額の合計行があれば税率ごとの内訳と二重に数えない() -> None:
    receipt = parse_receipt(
        [
            DATE,
            "パン ¥300",
            "小計 ¥300",
            "外税額計 ¥24",
            "10%消費税等 ¥8",
            "8%消費税等 ¥16",
            "合計 ¥324",
        ]
    )

    assert receipt.tax == 24


def test_合計の行が無ければ支払金額を合計にする() -> None:
    receipt = parse_receipt([DATE, "パン ¥200", "支払金額 ¥200"])

    assert receipt.total == 200


@pytest.mark.parametrize(
    ("row", "name"),
    [
        ("カップメン ト”ンヘ“エ ¥200", "カップメン ドンベエ"),
        ("ハ°スタ ¥200", "パスタ"),
        ("アイス 5°C ¥200", "アイス 5°C"),
    ],
)
def test_半角カナの濁点と半濁点が記号に読まれたものを直す(row: str, name: str) -> None:
    receipt = parse_receipt([DATE, row, "合計 ¥200"])

    assert receipt.items[0].name == name
