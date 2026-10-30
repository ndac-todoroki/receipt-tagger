# システム構成図

| 項目 | 内容 |
|---|---|
| 版 | v0.2（2026-10-23 方針決定を反映） |
| 作成日 | 2026-10-23 |
| 関連文書 | `docs/requirements.md` |

> デプロイは方針A（DGX Spark＋Cloudflare Tunnel）に確定。フロントはSolid.jsで、FastAPIから静的配信する。店ジャンルはOpenStreetMap（Nominatim）の店種別タグ＋対応表で判定する。

---

## 1. 論理構成（コンポーネント図）

```mermaid
flowchart LR
    subgraph Client["クライアント"]
        U["ユーザー<br/>スマホのブラウザ"]
    end

    subgraph Front["画面: Solid.js（ブラウザで実行）"]
        UI["アップロード / 結果表示 / 候補選択"]
    end

    subgraph Inf["アプリコンテナ: FastAPI + transformers"]
        STATIC["静的配信<br/>Solid.jsのビルド成果物"]
        API["API層<br/>サイズ検証 / レート制限"]
        P1["段1 領域抽出<br/>OpenCV"]
        P2["段2〜4 読み取り<br/>VLMの応答JSONを検証・変換"]
        CHK["整合性チェック<br/>品目合計 = 合計金額"]
        NORM["店名正規化"]
        SRCH["検索クライアント<br/>店名のみ送信"]
        P5["段5 店ジャンル判定<br/>店種別タグ→対応表"]
        MAP["判定粒度の決定<br/>genre_map.yaml"]
        P6["段6 品目ジャンル分類<br/>既存モデル（余裕があればFT）"]
        CACHE[("店名→店ジャンル<br/>キャッシュ")]
    end

    subgraph VLM["読み取りコンテナ: vLLM（compose内部のみ）"]
        QW["Qwen3.6-35B-A3B NVFP4<br/>画像→店名・品目・合計のJSON"]
    end

    subgraph Ext["外部サービス（補助）"]
        SE["OpenStreetMap<br/>Nominatim"]
    end

    subgraph Store["モデル重み"]
        W[("ボリューム<br/>または Hugging Face Hub")]
    end

    STATIC -.->|"画面を配信"| UI
    U -->|"画像アップロード"| UI
    UI -->|"POST /api/analyze"| API
    API --> P1 --> P2
    P2 <-->|"画像 / JSON"| QW
    P2 -->|"品目・合計"| CHK
    P2 -->|"店名"| NORM --> CACHE
    CACHE -->|"ヒット"| MAP
    CACHE -->|"ミス"| SRCH
    SRCH -->|"店名のみ"| SE
    SE -->|"店種別タグ"| P5
    P5 --> CACHE
    P5 --> MAP
    MAP -->|"品目ごと"| P6
    MAP -->|"全体で1ジャンル"| RES["結果の組み立て"]
    P6 --> RES
    CHK --> RES
    RES -->|"JSON"| UI
    UI -->|"表示"| U

    W -.->|"起動時にロード"| QW
    W -.-> P6
```

**ポイント**

- 外部サービスはOpenStreetMapの店舗検索のみ。読み取りと品目ジャンル分類は、DGX Spark 上の自前のコンテナで動く
- 読み取りは、旧方式（OCR→行の組み立て→ルールのパーサ）から視覚言語モデルに置き換えた（2026-10-30）。旧方式のコードは `stages/` に残し、比較に使う
- 検索に送るのは店名だけで、画像やレシートの他の情報は外部に出ない
- キャッシュにより、同じ店は再検索しない。検索失敗時はキャッシュ、なければ「判定不能」で縮退する

---

## 2. 推論シーケンス（1枚のレシート処理）

```mermaid
sequenceDiagram
    autonumber
    actor User as ユーザー
    participant Web as 画面（Solid.js）
    participant Inf as FastAPI
    participant VLM as vLLM
    participant Cache as キャッシュ
    participant Search as Nominatim

    User->>Web: レシート画像をアップロード
    Web->>Inf: POST /api/analyze（画像）
    Inf->>Inf: 領域抽出・補正（失敗時は原画像）
    Inf->>VLM: 画像と指示文（JSONスキーマを指定）
    alt 応答が正しいJSON
        VLM-->>Inf: 店名・品目・小計・外税・合計
    else 壊れた応答・タイムアウト
        Inf-->>Web: 読み取り失敗
    end
    Inf->>Inf: 整合性チェック
    Inf->>Inf: 店名の正規化

    alt キャッシュにヒット
        Inf->>Cache: 店名で照会
        Cache-->>Inf: 店ジャンル
    else キャッシュにミス
        Inf->>Search: 店名で検索
        alt 検索成功
            Search-->>Inf: 店種別タグ（shop=convenience 等）
            Inf->>Inf: 対応表で店ジャンルに変換
            Inf->>Cache: 店名→店ジャンルを保存
        else 検索失敗・タイムアウト・該当なし
            Inf->>Inf: 店ジャンル＝判定不能
        end
    end

    Inf->>Inf: 判定粒度を決定（genre_map.yaml）
    opt 品目ごとに判定する店
        Inf->>Inf: 品目ジャンル分類（信頼度つき）
    end

    Inf-->>Web: 結果JSON（画像は保持しない）
    Web-->>User: 表示（低信頼は候補から選択）
```

---

## 3. デプロイ構成（方針A: DGX Spark＋Cloudflare Tunnel）

```mermaid
flowchart TB
    User["ユーザー"] -->|"HTTPS"| CF["Cloudflare<br/>Tunnel"]

    subgraph Home["自宅: DGX Spark（docker compose）"]
        direction TB
        Tun["cloudflared"]
        App["app<br/>FastAPI + transformers<br/>Solid.jsを静的配信"]
        VL["vllm<br/>Qwen3.6-35B-A3B NVFP4"]
        Vol[("models ボリューム")]
        HF[("Hugging Face キャッシュ")]
    end

    CF --> Tun --> App
    App -->|"compose内部のみ"| VL
    Vol -.-> App
    HF -.-> VL
    App -->|"店名のみ"| Search["OpenStreetMap<br/>Nominatim"]
```

- 各サービスに `restart: unless-stopped` を付け、DGX Sparkの再起動後に自動で復帰させる
- vLLM は CPU と GPU で共有するメモリを起動時に計測する。他のプロセスの増減で計測が揺れて失敗するので、KV キャッシュの量と使用率の上限を固定する
- クラウドでのCPU構成（旧方針B・C）は採用しない

---

## 4. 学習・データ作成パイプライン（DGX Spark）

```mermaid
flowchart TB
    subgraph Raw["非公開領域（リポジトリ外）"]
        IMG[("レシート画像 約100枚")]
    end

    subgraph Prep["データ準備"]
        OCRJ["OCRを全画像に実行<br/>行テキスト＋座標をJSON保存"]
        PRE["事前ラベル付け<br/>大きなLLM / VLM"]
        FIX["人間が誤りだけ修正<br/>Label Studio等"]
        ANON["匿名化・加工"]
    end

    subgraph Aux["補強データ"]
        SYN["合成レシート画像<br/>領域抽出の評価用"]
    end

    subgraph Train["学習・評価（ml/）"]
        T6["品目ジャンル分類<br/>（余裕があればFT）"]
        EVAL["交差検証（店舗単位で分割）<br/>指標を docs/evaluation.md に記録"]
    end

    subgraph Out["成果物"]
        MODEL[("学習済みモデル<br/>Hub / ボリューム")]
        PUB[("公開用データ<br/>匿名化済みのみ")]
    end

    IMG --> OCRJ --> PRE --> FIX --> ANON
    ANON --> T6
    T6 --> EVAL
    SYN --> EVAL
    EVAL --> MODEL
    ANON --> PUB
```

**ポイント**

- 実レシート画像は、リポジトリに含めない（非公開領域で保持）
- 公開するのは、コード、匿名化済みのラベル付きテキスト、学習済みモデル、ラベル仕様書
- 大モデルでの事前ラベル付けは「実験・データ作成」用途。デプロイ物の推論には使わない

---

## 5. ディレクトリ構成（案）

```text
receipt-tagger/
├── CLAUDE.md
├── README.md
├── docker-compose.yml          # app + vllm + cloudflared
├── .env.example
├── .gitignore
├── config/
│   ├── genre_map.yaml          # 店種別タグ→店ジャンル、店ジャンル→判定粒度の対応表
│   ├── labels.yaml             # 店ジャンル・品目ジャンル・行ラベルの定義
│   └── thresholds.yaml         # 信頼度の閾値
├── docs/
│   ├── requirements.md
│   ├── architecture.md
│   ├── evaluation.md           # 評価指標と目標値、結果
│   ├── label_guide.md          # ラベル仕様
│   └── data_sources.md         # データ出典・ライセンス
├── ml/
│   ├── notebooks/              # 学習・分析ノートブック（消さずに残す）
│   ├── scripts/                # 学習・評価・データ作成スクリプト
│   ├── configs/                # 学習設定（シード・ハイパーパラメータ）
│   └── data/
│       ├── private/            # 実レシートとその派生データ（gitignore）
│       └── public/             # 匿名化済み・合成データ
├── inference/
│   ├── Dockerfile              # Solid.jsのビルドも含むマルチステージ
│   ├── pyproject.toml
│   ├── src/receipt_app/
│   │   ├── main.py             # FastAPI（APIと静的配信）
│   │   ├── pipeline.py         # 段の組み立て
│   │   ├── stages/             # 段1〜6を個別モジュールで実装
│   │   ├── config.py           # config/*.yaml の読み込み
│   │   └── search.py           # Nominatimクライアント（店名のみ）とキャッシュ
│   └── tests/
├── frontend/                   # Solid.js（Vite）
│   └── ...
└── samples/                    # 架空レシート画像（デモ用）
```
