# CLAUDE.md

レシート画像から店ジャンル・品目ジャンルを自動判定してWeb表示するアプリ。機械学習コース最終課題（**提出期限 2026-10-30**）。

- 仕様: `docs/requirements.md`、構成: `docs/architecture.md`（作業前に該当箇所を読む）
- 旧版の開発ルール: `docs/CLAUDE.draft.md`（参考。本ファイルが優先）

## 最重要ルール（修了要件。ユーザーの指示なしに変えない）

1. 推論の本体は、リポジトリ内のPythonコードでモデルをロードして実行する（transformers / ONNX Runtime / PyTorch）
2. ジャンル判定を外部LLM API（OpenAI、HF Inference API等）に置き換えない。外部APIは店情報の検索のみ
3. デプロイ物の推論に Ollama・vLLM 等の配信サーバーを使わない（事前ラベル付け・実験では可）
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

- **開発**: Windows（この機）。uv、Docker あり。Elixir は未インストールなので、Phoenix は Docker 経由で動かす
- **学習・実験**: DGX Spark（aarch64 / Ubuntu 24.04 / NVIDIA GB10 / 統合メモリ128GB）。NVIDIA Sync の SSH 設定経由で接続する
  ```bash
  ssh -F "$LOCALAPPDATA/NVIDIA Corporation/Sync/config/ssh_config" K-EdgeXpert '<command>'
  ```
  - aarch64 なので、PyTorch・Dockerイメージは arm64 + CUDA 対応のものを選ぶ（NGC コンテナ推奨）
  - 長時間の学習は DGX Spark 側で `tmux` / `nohup` を使って起動し、ログをファイルに出す

## 開発コマンド

> 骨組みを作ったら、実際のコマンドに更新する。

```bash
# 推論サービス
cd inference && uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
# 全体起動
docker compose --profile cpu up --build   # gpu プロファイルは DGX Spark 上で
```

## コーディング規約

- 識別子は英語、コメント・docstring・コミットメッセージ・ドキュメントは日本語
- パイプラインの各段は `inference/src/receipt_app/stages/` に独立モジュールとして置き、単体でテストできるようにする
- ジャンル定義・対応表・閾値はコードに直書きせず、`config/*.yaml` から読む
- モデルのロードは起動時に1回だけ行う
- 外部APIの失敗は「判定不能」として縮退させる。アプリ全体を落とさない
- Web（Phoenix）は最小限にする（アップロード、結果表示、低信頼時の選択）

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

- デプロイ先の選定、有料サービスの利用、検索APIの選定
- ジャンル定義（`config/labels.yaml`）の大きな変更
- 外部サービスの追加、データの削除、履歴の書き換え
