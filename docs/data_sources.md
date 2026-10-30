# データ出典・ライセンス

外部データや外部サービスを追加したら、ここに出典と利用条件を記録する。

| 名称 | 用途 | ライセンス・利用条件 | 必要な表記 |
|---|---|---|---|
| OpenStreetMap（Nominatim 公開サーバー） | 店名から店種別タグを取得し、店ジャンルを判定する（FR-08） | データは ODbL。Nominatim の利用規約により、問い合わせは1秒1回まで、User-Agent でアプリを名乗る、結果はキャッシュする、大量の一括問い合わせはしない | 画面と README・スライドに「© OpenStreetMap contributors」を表示する |

- 利用規約: https://operations.osmfoundation.org/policies/nominatim/
- 著作権表記: https://www.openstreetmap.org/copyright

## モデル・推論サーバー

| 名称 | 用途 | ライセンス・利用条件 | 必要な表記 |
|---|---|---|---|
| Qwen3.6-35B-A3B（Qwen） | レシート画像から店名・品目・合計を読み取る（FR-03） | Apache-2.0 | README・スライドにモデル名と出典 |
| RedHatAI/Qwen3.6-35B-A3B-NVFP4 | 上記を NVFP4 に量子化したもの。実際に配信するのはこちら | Apache-2.0 | 同上 |
| vLLM（NGC コンテナ `nvcr.io/nvidia/vllm:26.10-py3`） | 上記モデルの配信 | vLLM 本体は Apache-2.0。NGC コンテナは NVIDIA の利用規約（NVIDIA Deep Learning Container License）に従う | ― |

- https://huggingface.co/Qwen/Qwen3.6-35B-A3B
- https://huggingface.co/RedHatAI/Qwen3.6-35B-A3B-NVFP4
