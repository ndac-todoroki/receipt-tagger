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
    r"(?P<num>\d{1,3}(?:[,.]\d{3})+|\d+)\s*(?P<mark>内|外|J|軽|円|-)?\s*$"
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
_ADDRESS = r"(都|道|府|県).*(市|区|町|村)"
_ITEM_EXCLUDE = re.compile(
    r"対象|点数|預|釣|番号|TEL|Tel|電話|ポイント|No|登録|レジ|担当|税|稅|" + _ADDRESS
)
_SUBTOTAL = re.compile(r"小計|小计")
_TOTAL = re.compile(r"合計|合计")
# 合計の行が無いレシートで、合計の代わりになる行
_TOTAL_FALLBACK = re.compile(r"支払金額|お支払|請求|領収金額")
_HAS_WORD = re.compile(r"[^\W\d_]")
# 品目のうち円記号などの印が付いた金額がこの割合以上なら、印の無い数字は金額とみなさない
_MARKED_STYLE_RATIO = 0.5
_TAX = re.compile(r"税|稅")
_COMPANY = re.compile(r"株式会社|有限会社|\(株\)|\(有\)")
_LABEL_PREFIX = re.compile(r"^[^：:]*[：:]\s*")
_NOT_STORE_NAME = re.compile(
    r"領収|領收|レシート|TEL|Tel|電話|〒|登録|番号|No|" + _ADDRESS + r"|\d+-\d+"
)
_MAX_HEADER_ROWS = 6
_MAX_STORE_NAME_LENGTH = 20


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _to_int(num: str) -> int:
    return int(re.sub(r"[,.]", "", num))


@dataclass(frozen=True)
class _Amount:
    prefix: str
    value: int
    # 円記号・符号・税区分の印など、金額であることを示す印が付いていたか
    marked: bool


def _split_amount(text: str) -> _Amount | None:
    """行を「末尾の金額」と「その前の部分」に分ける。金額が無ければ None。"""
    m = _AMOUNT_TAIL.search(text)
    if m is None:
        return None
    # 「3丁目26-6」のように語に続くハイフンは符号ではない
    if m["sign"] and m.start("sign") > 0 and not text[m.start("sign") - 1].isspace():
        return None
    num = m["num"]
    # 「¥0」が「04」のように読まれることがあるので、0で始まる数字は金額とみなさない
    if num.startswith("0") and len(num) > 1:
        return None
    before_num = text[: m.start("num")]
    signed = bool(m["sign"] or m["sign2"])
    # 「客数：6」のように語に続く数字は金額ではない。¥ か符号か空白の後ろの数字だけを金額とみなす
    if not (m["yen"] or signed or before_num == "" or before_num[-1].isspace()):
        return None
    return _Amount(
        prefix=text[: m.start()].strip(),
        value=(-1 if signed else 1) * _to_int(num),
        marked=bool(m["yen"] or signed or m["mark"]),
    )


def parse_amount(text: str) -> int | None:
    """金額の表記（例: "¥1,080", "874内", "-30"）を整数にする。金額でなければ None。"""
    amount = _split_amount(_normalize(text))
    if amount is None or amount.prefix != "":
        return None
    return amount.value


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


def _is_excluded(row: str) -> bool:
    return not _is_quantity_row(row) and (row[0] in "(（" or bool(_ITEM_EXCLUDE.search(row)))


def _parse_items(rows: list[str]) -> list[ParsedItem]:
    amounts = [a for r in rows if not _is_excluded(r) and (a := _split_amount(r)) is not None]
    marked_style = bool(amounts) and (
        sum(a.marked for a in amounts) / len(amounts) >= _MARKED_STYLE_RATIO
    )

    items: list[ParsedItem] = []
    pending_name: str | None = None

    def add(name: str, amount: int, rest: str) -> None:
        if amount == 0 or not _HAS_WORD.search(name):
            return
        qty = _parse_quantity(rest, amount)
        quantity, unit_price = qty if qty else (1, None)
        items.append(ParsedItem(name=name, amount=amount, quantity=quantity, unit_price=unit_price))

    for row in rows:
        split = _split_amount(row)
        if marked_style and split is not None and not split.marked:
            # 金額の多くに印があるレシートで、印の無い数字はレジ番号などとみなす
            split = None
        if _JAN.search(row):
            # 印字の位置がずれて、前の品目の金額が次の品目のJANの行に読まれることがある
            if split is not None and pending_name:
                add(pending_name, split.value, "")
            pending_name = None
            continue
        quantity_row = _is_quantity_row(row)
        if _is_excluded(row):
            pending_name = None
            continue
        if split is None:
            if row.startswith("@"):
                # 単価と数量の行が読み切れなかったもの。品名は次の金額の行まで持ち越す
                continue
            # 金額の無い行は、次の行に金額が来る品名とみなす
            pending_name = None if quantity_row else _clean_name(row) or None
            continue
        name = pending_name if quantity_row else (_clean_name(split.prefix) or pending_name)
        pending_name = None
        if name:
            add(name, split.value, split.prefix)
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
            if re.search(
                "|".join(p.pattern for p in (_SUBTOTAL, _TOTAL, _TOTAL_FALLBACK)),
                _compact(rows[i]),
            )
        ),
        len(rows),
    )

    subtotal: int | None = None
    total: int | None = None
    total_index = len(rows)
    for i in range(items_end, len(rows)):
        compact = _compact(rows[i])
        amount = _split_amount(rows[i])
        if amount is None or rows[i][0] in "(（":
            continue
        if subtotal is None and _SUBTOTAL.search(compact):
            subtotal = amount.value
        elif _TOTAL.search(compact) and not _SUBTOTAL.search(compact):
            total, total_index = amount.value, i
            break
    if total is None:
        for i in range(items_end, len(rows)):
            amount = _split_amount(rows[i])
            if amount is not None and _TOTAL_FALLBACK.search(_compact(rows[i])):
                total, total_index = amount.value, i
                break

    # 合計より前にある税の行だけを外税とみなす（合計の後の「内消費税」は合計に含まれている）
    tax_rows = [
        (r, amount.value)
        for r in rows[items_end:total_index]
        if _TAX.search(r)
        and not re.search(r"対象|内|小計|小计", r)
        and r[0] not in "(（"
        and (amount := _split_amount(r)) is not None
    ]
    # 「外税額計」のような税額の合計行があれば、税率ごとの内訳と二重に数えない
    summary = [value for r, value in tax_rows if "計" in r]
    tax_amounts = summary or [value for _, value in tax_rows]

    return ParsedReceipt(
        store_candidates=_store_candidates(rows, len(rows) if date_index is None else date_index),
        items=_parse_items(rows[items_start:items_end]),
        subtotal=subtotal,
        tax=sum(tax_amounts) if tax_amounts else None,
        total=total,
    )
