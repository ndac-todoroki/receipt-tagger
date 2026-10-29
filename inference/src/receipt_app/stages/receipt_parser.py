"""レシートの行から、店名候補・品目・合計を取り出す（FR-04 行の役割分類, FR-05 品目抽出）。

まずはルールで実装する。行の役割は、日付の行・小計/合計の行を境に
「見出し → 品目 → 集計」の3区間に分けて決める。
"""

import re
import unicodedata
from dataclasses import dataclass, field

from receipt_app.stages.store_name import normalize_store_name


@dataclass(frozen=True)
class ParsedItem:
    """品目1つ。値引きは負の金額の品目として表す。"""

    name: str
    amount: int
    quantity: int = 1
    unit_price: int | None = None


@dataclass(frozen=True)
class ParsedReceipt:
    """レシート1枚から取り出した内容。store_candidates は確からしい順。"""

    store_candidates: list[str] = field(default_factory=list)
    items: list[ParsedItem] = field(default_factory=list)
    subtotal: int | None = None
    tax: int | None = None
    total: int | None = None


# 末尾の金額。¥ が * に読まれる、カンマがピリオドに読まれる、税区分の印が付く、を許す
_AMOUNT_TAIL = re.compile(
    r"(?P<sign>-)?\s*(?P<yen>[¥\\*])?\s*(?P<sign2>-)?"
    r"(?P<num>\d{1,3}(?:[,.]\d{3})+|\d+)\s*(?:内|外|J|軽)?\s*$"
)
_DATE = re.compile(r"\d{4}\s*[年/.\-]\s*\d{1,2}\s*[月/.\-]\s*\d{1,2}")
_QTY_AT = re.compile(r"@\s*(?P<unit>[\d,.]+)\s*[×xX*]\s*(?P<qty>\d+)")
_QTY_TAN = re.compile(r"[(（]\s*[単单]\s*¥?\s*(?P<unit>[\d,.]+)\s*[)）]\s*[×xX*]\s*(?P<qty>\d+)")
_QTY_KO = re.compile(r"(?P<nums>\d+)\s*個")
_JAN = re.compile(r"JAN\s*\d{8,}")
# 品名の前に付く部門コード・商品コード・オプションの印
_NAME_PREFIXES = [
    re.compile(r"^[#＃]\d+\s*"),
    re.compile(r"^\d{1,2}\s*[xX×]\s*"),
    re.compile(r"^[外内軽]\S{0,2}\s+\d{4,}\s*"),
    re.compile(r"^\d{4,}\s*"),
    re.compile(r"^[>＞]+\s*"),
]
_ITEM_EXCLUDE = re.compile(r"対象|点数|預|釣|番号|TEL|Tel|電話|ポイント|No|登録|レジ|担当|税|稅")
_SUBTOTAL = re.compile(r"小計|小计")
_TOTAL = re.compile(r"合計|合计")
_TAX = re.compile(r"税|稅")
_COMPANY = re.compile(r"株式会社|有限会社|\(株\)|\(有\)")
_LABEL_PREFIX = re.compile(r"^[^：:]*[：:]\s*")
_NOT_STORE_NAME = re.compile(
    r"領収|領收|レシート|TEL|Tel|電話|〒|登録|番号|No|(都|道|府|県).*(市|区|町|村)|\d+-\d+"
)
_MAX_HEADER_ROWS = 6
_MAX_STORE_NAME_LENGTH = 20


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _to_int(num: str) -> int:
    return int(re.sub(r"[,.]", "", num))


def _split_amount(text: str) -> tuple[str, int] | None:
    """行を「末尾の金額」と「その前の部分」に分ける。金額が無ければ None。"""
    m = _AMOUNT_TAIL.search(text)
    if m is None:
        return None
    prefix = text[: m.start()]
    before_num = text[: m.start("num")]
    # 「客数：6」のように語に続く数字は金額ではない。¥ か符号か空白の後ろの数字だけを金額とみなす
    if not (m["yen"] or m["sign"] or m["sign2"] or before_num == "" or before_num[-1].isspace()):
        return None
    sign = -1 if (m["sign"] or m["sign2"]) else 1
    return prefix.strip(), sign * _to_int(m["num"])


def parse_amount(text: str) -> int | None:
    """金額の表記（例: "¥1,080", "874内", "-30"）を整数にする。金額でなければ None。"""
    split = _split_amount(_normalize(text))
    if split is None or split[0] != "":
        return None
    return split[1]


def _clean_name(text: str) -> str:
    name = text
    for prefix in _NAME_PREFIXES:
        name = prefix.sub("", name)
    return name.strip()


def _parse_quantity(text: str, amount: int | None) -> tuple[int, int | None] | None:
    """数量と単価を読む。読めなければ None。"""
    for pattern in (_QTY_AT, _QTY_TAN):
        m = pattern.search(text)
        if m:
            return int(m["qty"]), _to_int(m["unit"])
    m = _QTY_KO.search(text)
    if m is None:
        return None
    nums = m["nums"]
    # 「¥179 2個」が「1792個」とつながって読まれることがあるので、金額と矛盾しない分け方を探す
    for qty_len in (1, 2):
        if len(nums) > qty_len and amount is not None:
            unit, qty = int(nums[:-qty_len]), int(nums[-qty_len:])
            if qty > 0 and unit * qty == amount:
                return qty, unit
    return int(nums), None


def _is_quantity_row(text: str) -> bool:
    return bool(_QTY_AT.search(text) or _QTY_TAN.search(text))


def _parse_items(rows: list[str]) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    pending_name: str | None = None
    for row in rows:
        if _JAN.search(row):
            continue
        quantity_row = _is_quantity_row(row)
        if not quantity_row and (row[0] in "(（" or _ITEM_EXCLUDE.search(row)):
            pending_name = None
            continue
        split = _split_amount(row)
        if split is None:
            # 金額の無い行は、次の行に金額が来る品名とみなす
            pending_name = None if quantity_row else _clean_name(row) or None
            continue
        rest, amount = split
        name = pending_name if quantity_row else (_clean_name(rest) or pending_name)
        pending_name = None
        if amount == 0 or not name:
            continue
        qty = _parse_quantity(rest, amount)
        quantity, unit_price = qty if qty else (1, None)
        items.append(ParsedItem(name=name, amount=amount, quantity=quantity, unit_price=unit_price))
    return items


def _store_candidates(rows: list[str], header_end: int) -> list[str]:
    company = [_LABEL_PREFIX.sub("", r) for r in rows if _COMPANY.search(r)]
    header = [
        r
        for r in rows[: min(header_end, _MAX_HEADER_ROWS)]
        if not _NOT_STORE_NAME.search(r) and len(r) <= _MAX_STORE_NAME_LENGTH
    ]
    # 「〇〇町店」のような支店名だけの行は店の特定に弱いので後ろに回す
    header.sort(key=lambda r: r.endswith("店"))
    candidates: list[str] = []
    for raw in company + header:
        name = normalize_store_name(raw)
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def parse_receipt(raw_rows: list[str]) -> ParsedReceipt:
    """上から順に並んだ行の文字列から、店名候補・品目・小計・税・合計を取り出す。"""
    rows = [r for r in (_normalize(r) for r in raw_rows) if r]
    date_index = next((i for i, r in enumerate(rows) if _DATE.search(r)), None)
    items_start = 0 if date_index is None else date_index + 1
    items_end = next(
        (
            i
            for i in range(items_start, len(rows))
            if _SUBTOTAL.search(_compact(rows[i])) or _TOTAL.search(_compact(rows[i]))
        ),
        len(rows),
    )

    subtotal: int | None = None
    total: int | None = None
    total_index = len(rows)
    for i in range(items_end, len(rows)):
        compact = _compact(rows[i])
        split = _split_amount(rows[i])
        if split is None or rows[i][0] in "(（":
            continue
        if subtotal is None and _SUBTOTAL.search(compact):
            subtotal = split[1]
        elif _TOTAL.search(compact) and not _SUBTOTAL.search(compact):
            total, total_index = split[1], i
            break

    # 合計より前にある税の行だけを外税とみなす（合計の後の「内消費税」は合計に含まれている）
    tax_amounts = [
        split[1]
        for r in rows[items_end:total_index]
        if _TAX.search(r)
        and not re.search(r"対象|内|小計|小计", r)
        and r[0] not in "(（"
        and (split := _split_amount(r)) is not None
    ]

    return ParsedReceipt(
        store_candidates=_store_candidates(rows, len(rows) if date_index is None else date_index),
        items=_parse_items(rows[items_start:items_end]),
        subtotal=subtotal,
        tax=sum(tax_amounts) if tax_amounts else None,
        total=total,
    )
