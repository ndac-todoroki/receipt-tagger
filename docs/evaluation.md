# 評価

モデルの部分（TDD の対象外）は、ここに**測る前に**決めた指標で評価する。結果は `devlog.md` に残す。

## 品目ジャンル分類（FR-11）

### サマリー

- 比べるもの: 分類器2種（埋め込み・LLM）× 判定の段数2種（1段・2段）の4通り
- 主な指標: **大分類の正解率**（家計簿で使うのは大分類なので）
- データ: 実レシート89枚から読み取った品目（約460）。約100枚と少ないので**結果は参考値**

### 比べるもの

| | 1段: 大分類6個から直接選ぶ | 2段: 小分類24個から選び、対応表で大分類に直す |
|---|---|---|
| 埋め込み（Ruri v3 30m の類似度） | 見本は、その大分類に属する小分類の見本をまとめたもの | アプリの既定 |
| LLM（Qwen3.6 の制約付きデコーディング） | 同上 | `ITEM_CLASSIFIER=llm` |

- どれも学習しないので、学習用と評価用の分割はしない
- 見本・指示文・温度・閾値は、この評価データの誤りを見て調整しない。調整した場合は、その後の結果を「調整に使ったデータでの値」と明記する

### 指標

- 主: 大分類の正解率
- 副
  - 大分類のマクロ F1（件数の少ない大分類を見落としていないか）
  - 小分類の正解率（2段のみ）
  - 信頼度が閾値（`thresholds.yaml` の `item_genre_min_confidence`）以上の品目の割合と、その中での大分類の正解率（低信頼時の選択が画面でどれだけ出るか）
  - 1品目あたりの処理時間

### 正解ラベル

- 読み取りは Qwen3.6 の struct（`devlog.md` の 2026-10-31、合計整合率92%）の出力を使う。読み取りの誤りで品名が崩れていても、その品名から読み取れるジャンルを正解にする
- 下書き: LLM の2段（小分類）で付け（`ml/scripts/draft_item_labels.py`）、人が `genre` 列を直す。直す前の `draft_genre` は残す
- 飲食店のレシートの品目は外食として店ジャンルでまとめるので、`genre` を空にして評価から除く
- 下書きと同じ分類器（LLM の2段）は、直しが少ないほど有利に出る。そのため、下書きと正解の一致率（＝直さなかった割合）も結果に書く
- 置き場所: `ml/data/private/labels/item_genres_draft.csv`（実レシートの品名なのでコミットしない）

### 手順

```bash
# 下書き（推論サーバーは compose の内部にしかないので、Spark の app コンテナの中で動かす）
docker compose cp <詳細.jsonl> app:/tmp/detail.jsonl
docker compose cp ml/scripts/draft_item_labels.py app:/tmp/ml/scripts/draft.py
docker compose exec -T app python /tmp/ml/scripts/draft.py /tmp/detail.jsonl /tmp/draft.csv \
  --url http://vllm:8000/v1/chat/completions --config /app/config
```
