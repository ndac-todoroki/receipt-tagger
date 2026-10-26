"""店名正規化（FR-07）。レシートの店名行を、検索に使える形に整える。"""

import re
import unicodedata

# NFKC で ㈱ は (株) に、全角括弧は半角になるので、半角の表記だけを相手にすればよい
_CORPORATE_FORMS = re.compile(r"株式会社|有限会社|合同会社|\(株\)|\(有\)")


def normalize_store_name(raw: str) -> str | None:
    """店名から法人格と末尾の支店名を除き、表記をそろえる。何も残らなければ None。"""
    text = unicodedata.normalize("NFKC", raw)
    text = _CORPORATE_FORMS.sub(" ", text)
    tokens = text.split()
    # 「紀伊國屋書店」のように店名自体が店で終わるものを残すため、
    # 空白で区切られた語だけを支店名とみなす
    while len(tokens) > 1 and tokens[-1].endswith("店"):
        tokens.pop()
    return " ".join(tokens) or None
