# CLAUDE.md

レシート画像から店ジャンル・品目ジャンルを自動判定してWeb表示するアプリ。機械学習コース最終課題（**提出期限 2026-10-30**）。

- 仕様: `docs/requirements.md`、構成: `docs/architecture.md`（作業前に該当箇所を読む）
- 旧版の開発ルール: `docs/CLAUDE.draft.md`（参考。本ファイルが優先）

## 最重要ルール（修了要件。ユーザーの指示なしに変えない）

1. 推論は、自分たちの環境（DGX Spark）で動かすモデルで行う。Hugging Face 等の公開モデルをそのまま、または量子化（NVFP4 等）して使ってよい
2. ジャンル判定を外部LLM API（OpenAI、HF Inference API等）に置き換えない。外部APIは店情報の検索のみ
3. 推論には transformers / ONNX Runtime / PyTorch のほか、Ollama・vLLM・SGLang・llama.cpp 等の配信サーバーを使ってよい（自前の環境で動かすものに限る）
4. 学習に使ったノートブック・スクリプトを削除・移動しない
5. 期限が近いので、**端から端まで動く最小構成を最優先**する。精度改善・拡張機能は後回し

## 個人情報・セキュリティ

- Claude Code は実レシートの画像・OCR結果を読んでよい。ただし**コミット・公開物・ログには含めない**
- `ml/data/private/`（実レシートとその派生データ、検索スニペット）は常に gitignore 対象
- 公開してよいのは匿名化済みデータ、合成データ、`samples/` の架空レシートのみ
- 外部の検索APIに送るのは**店名だけ**
- アップロード画像はディスクに保存せず、ログにも出さない。例外ログにOCR全文を含めない
- 認証情報は環境変数で渡す。リポジトリには `.env.example` だけを置く
- コミット前に `git status` と差分を見て、画像・データ・`.env`・重みが入っていないことを確認する
- 外部データや依存パッケージを追加するときは、ライセンスを確認して `docs/data_sources.md` に記録する

## 実行環境

- **構成**: 推論APIは FastAPI。フロントエンドは Solid.js で作り、ビルド成果物を FastAPI から静的配信する（コンテナ1つ）
- **モデル**: 多段パイプラインは設計どおり。まずは既存モデルを推論に使うだけで端から端まで通し、ファインチューニングは余裕があれば行う（最初の対象は品目ジャンル分類）
- **デプロイ**: DGX Spark 上の docker compose を Cloudflare Tunnel で公開する（方針A）
- **開発**: Windows（この機）。uv、Node、Docker あり
- **GitHub**: `ndac-todoroki/receipt-tagger`（private。提出時に公開へ切り替える）。`gh` は**常に `ndac-todoroki` で操作する**。この機には別のアカウントでもログインしているため、`gh` を使う前に `gh api user --jq .login` で確かめ、違えば `gh auth switch -u ndac-todoroki` する
- **学習・実験**: DGX Spark（aarch64 / Ubuntu 24.04 / NVIDIA GB10 / 統合メモリ128GB）。NVIDIA Sync の SSH 設定経由で接続する
  ```bash
  ssh -F "$LOCALAPPDATA/NVIDIA Corporation/Sync/config/ssh_config" K-EdgeXpert '<command>'
  ```
  - aarch64 なので、PyTorch・Dockerイメージは arm64 + CUDA 対応のものを選ぶ（NGC コンテナ推奨）
  - 長時間の学習は DGX Spark 側で `tmux` / `nohup` を使って起動し、ログをファイルに出す

## 開発コマンド

```bash
# 推論API（inference/）: 変更後は必ず全部通す
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
uv run uvicorn receipt_app.main:app --reload          # 開発サーバー（:8000）

# 画面（frontend/）
npm run dev      # :5173。/api は :8000 の uvicorn へ転送される
npm run build    # 型チェックを含む

# DGX Spark へのデプロイ: コミット済みの main を push する
git push spark main
# → Spark の ~/repos/receipt-tagger.git の post-receive hook が ~/receipt-tagger に展開し、
#   docker compose up -d --build とヘルスチェック（localhost:8080。8000 は NIM が使用中）まで行う
#   remote spark への ssh は git config core.sshCommand で NVIDIA Sync の設定を使う
# 公開: .env に TUNNEL_TOKEN を置いて docker compose --profile tunnel up -d
```

- この Windows 機では Docker Desktop が常時起動していないので、コンテナの確認は DGX Spark で行う

## コーディング規約

- 識別子は英語、コメント・docstring・コミットメッセージ・ドキュメントは日本語
- パイプラインの各段は `inference/src/receipt_app/stages/` に独立モジュールとして置き、単体でテストできるようにする
- ジャンル定義・対応表・閾値はコードに直書きせず、`config/*.yaml` から読む
- モデルのロードは起動時に1回だけ行う
- 外部APIの失敗は「判定不能」として縮退させる。アプリ全体を落とさない
- フロントエンドの機能は、アップロード、結果表示、低信頼時の選択の3つに絞る

## テスト

- ルールで書く部分（品目抽出、店名正規化、整合性チェック、粒度判定、キャッシュ）は TDD（t-wada流）で書く
- モデルの部分は TDD の対象にせず、`docs/evaluation.md` に**学習前に**決めた指標で評価する
- 実レシートを使うテストはローカルでの手動検証に限り、リポジトリに含めない
- 「動いた」と報告する前に、画面から入力 → 結果表示まで確認する。確認できていない場合はそう書く

## 機械学習

- 評価データは**店舗単位で分割**する（リーク防止）。約100枚なので交差検証にし、結果は参考値と明記する
- シード・依存バージョン・ハイパーパラメータは `ml/configs/` に固定する
- LLMで事前ラベル付けした場合は人間の修正版を正解にし、修正前後の差分も残す
- 試したこと・失敗・対処を `docs/devlog.md` に残す（スライドの「つまずいた点」の材料になる）
- 学習済み重みはコミットしない

## 事前にユーザーへ確認すること

- 有料サービスの利用、検索APIの選定、Cloudflare の設定変更
- ジャンル定義（`config/labels.yaml`）の大きな変更
- 外部サービスの追加、データの削除、履歴の書き換え
