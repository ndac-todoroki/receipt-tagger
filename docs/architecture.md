# システム構成図

| 項目 | 内容 |
|---|---|
| 版 | v0.1（ドラフト） |
| 作成日 | 2026-10-23 |
| 関連文書 | `docs/requirements.md` |

> デプロイ方針（A/B/C）は1on1での確認結果で確定する。ここでは3方針すべてに対応できる構成として記述する。

---

## 1. 論理構成（コンポーネント図）

```mermaid
flowchart LR
    subgraph Client["クライアント"]
        U["ユーザー<br/>スマホのブラウザ"]
    end

    subgraph Web["Webコンテナ: Phoenix LiveView"]
        UI["画面<br/>アップロード / 結果表示 / 候補選択"]
        WCtl["推論サービス呼び出し<br/>タイムアウト・リトライ"]
    end

    subgraph Inf["推論コンテナ: FastAPI + transformers"]
        API["API層<br/>サイズ検証 / レート制限"]
        P1["段1 領域抽出<br/>OpenCV"]
        P2["段2 OCR<br/>既存モデルを推論利用"]
        P3["段3 行の役割分類"]
        P4["段4 品目の項目抽出<br/>ルール＋必要時モデル"]
        CHK["整合性チェック<br/>品目合計 = 合計金額"]
        NORM["店名正規化"]
        SRCH["検索クライアント<br/>店名のみ送信"]
        P5["段5 店ジャンル分類<br/>ModernBERT系"]
        MAP["判定粒度の決定<br/>genre_map.yaml"]
        P6["段6 品目ジャンル分類<br/>ModernBERT系"]
        CACHE[("店名→店ジャンル<br/>キャッシュ")]
    end

    subgraph Ext["外部サービス（補助）"]
        SE["検索API"]
    end

    subgraph Store["モデル重み"]
        W[("ボリューム<br/>または Hugging Face Hub")]
    end

    U -->|"画像アップロード"| UI
    UI --> WCtl
    WCtl -->|"HTTP"| API
    API --> P1 --> P2 --> P3
    P3 -->|"品目行"| P4 --> CHK
    P3 -->|"店名行"| NORM --> CACHE
    CACHE -->|"ヒット"| MAP
    CACHE -->|"ミス"| SRCH
    SRCH -->|"店名のみ"| SE
    SE -->|"概要テキスト"| P5
    P5 --> CACHE
    P5 --> MAP
    MAP -->|"品目ごと"| P6
    MAP -->|"全体で1ジャンル"| RES["結果の組み立て"]
    P6 --> RES
    CHK --> RES
    RES -->|"JSON"| WCtl
    WCtl --> UI
    UI -->|"表示"| U

    W -.->|"起動時にロード"| P2
    W -.-> P3
    W -.-> P5
    W -.-> P6
```

**ポイント**

- 外部サービスは検索APIのみ。判定の本体（段2〜6）はすべて推論コンテナ内の自前コードで動く
- 検索に送るのは店名だけで、画像やレシートの他の情報は外部に出ない
- キャッシュにより、同じ店は再検索しない。検索失敗時はキャッシュ、なければ「判定不能」で縮退する

---

## 2. 推論シーケンス（1枚のレシート処理）

```mermaid
sequenceDiagram
    autonumber
    actor User as ユーザー
    participant Web as Phoenix
    participant Inf as 推論サービス
    participant Cache as キャッシュ
    participant Search as 検索API

    User->>Web: レシート画像をアップロード
    Web->>Inf: POST /analyze（画像）
    Inf->>Inf: 領域抽出・補正（失敗時は原画像）
    Inf->>Inf: OCR（行テキスト＋座標）
    Inf->>Inf: 行の役割分類
    Inf->>Inf: 品目の項目抽出と整合性チェック
    Inf->>Inf: 店名の正規化

    alt キャッシュにヒット
        Inf->>Cache: 店名で照会
        Cache-->>Inf: 店ジャンル
    else キャッシュにミス
        Inf->>Search: 店名で検索
        alt 検索成功
            Search-->>Inf: 店の概要テキスト
            Inf->>Inf: 店ジャンル分類（信頼度つき）
            Inf->>Cache: 店名→店ジャンルを保存
        else 検索失敗・タイムアウト
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

## 3. デプロイ構成

### 3.1 方針A: 自宅公開型（DGX Spark）

```mermaid
flowchart TB
    User["ユーザー"] -->|"HTTPS"| CF["Cloudflare<br/>Tunnel / Access"]

    subgraph Home["自宅: DGX Spark（docker compose, profile=gpu）"]
        direction TB
        Web["web<br/>Phoenix"]
        Inf["inference<br/>FastAPI + transformers<br/>GPU・大きめのモデル"]
        Vol[("models ボリューム")]
    end

    CF --> Web
    Web --> Inf
    Vol -.-> Inf
    Inf -->|"店名のみ"| Search["検索API"]
```

### 3.2 方針B: クラウド完結型（軽量CPU構成）

```mermaid
flowchart TB
    User["ユーザー"] -->|"HTTPS"| Host["クラウドのホスティング"]

    subgraph Cloud["クラウド（docker compose, profile=cpu）"]
        direction TB
        Web["web<br/>Phoenix"]
        Inf["inference<br/>FastAPI + transformers<br/>CPU・蒸留した小モデル"]
        Vol[("models ボリューム<br/>または Hub から取得")]
    end

    Host --> Web
    Web --> Inf
    Vol -.-> Inf
    Inf -->|"店名のみ"| Search["検索API"]
```

### 3.3 方針C: 二段構え

```mermaid
flowchart LR
    User["ユーザー"] --> Entry["公開エントリ"]
    Entry -->|"通常"| Spark["自宅 DGX Spark<br/>profile=gpu"]
    Entry -.->|"ヘルスチェック失敗時<br/>自動切替"| CloudSmall["クラウド<br/>profile=cpu"]
```

> 切り替えの実現手段（DNSフェイルオーバー、ロードバランサ、フロント側のフォールバック等）は未決。1on1の回答後に決める。

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
        SHOP["有名チェーン・各業態の店名リスト"]
        SNIP["検索スニペット収集<br/>規約確認の上、非公開で保持"]
        SYN["合成レシート画像<br/>領域抽出の評価用"]
    end

    subgraph Train["学習・評価（ml/）"]
        T3["行の役割分類"]
        T5["店ジャンル分類"]
        T6["品目ジャンル分類"]
        EVAL["交差検証（店舗単位で分割）<br/>指標を docs/evaluation.md に記録"]
    end

    subgraph Out["成果物"]
        MODEL[("学習済みモデル<br/>Hub / ボリューム")]
        PUB[("公開用データ<br/>匿名化済みのみ")]
    end

    IMG --> OCRJ --> PRE --> FIX --> ANON
    SHOP --> SNIP --> PRE
    ANON --> T3
    ANON --> T6
    FIX --> T5
    T3 --> EVAL
    T5 --> EVAL
    T6 --> EVAL
    SYN --> EVAL
    EVAL --> MODEL
    ANON --> PUB
```

**ポイント**

- 実レシート画像とスニペット本文は、リポジトリに含めない（非公開領域で保持）
- 公開するのは、コード、匿名化済みのラベル付きテキスト、学習済みモデル、ラベル仕様書
- 大モデルでの事前ラベル付けは「実験・データ作成」用途。デプロイ物の推論には使わない

---

## 5. ディレクトリ構成（案）

```text
receipt-app/
├── CLAUDE.md
├── README.md
├── docker-compose.yml          # profiles: gpu / cpu
├── .env.example
├── .gitignore
├── config/
│   ├── genre_map.yaml          # 店ジャンル→判定粒度の対応表
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
│       ├── private/            # 実レシート・スニペット（gitignore）
│       └── public/             # 匿名化済み・合成データ
├── inference/
│   ├── Dockerfile.gpu
│   ├── Dockerfile.cpu
│   ├── pyproject.toml
│   ├── src/receipt_app/
│   │   ├── main.py             # FastAPI
│   │   ├── pipeline.py         # 段の組み立て
│   │   ├── stages/             # 段1〜6を個別モジュールで実装
│   │   ├── search.py           # 検索クライアント（店名のみ）
│   │   └── cache.py
│   └── tests/
├── web/                        # Phoenix LiveView
│   ├── Dockerfile
│   └── ...
└── samples/                    # 架空レシート画像（デモ用）
```
