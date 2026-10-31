"""設定ファイル（config/*.yaml）の読み込みのテスト。

確かめること: リポジトリの設定が読めて、対応表とジャンル定義が食い違っていない。
確かめないこと: 対応表の中身が妥当か（ジャンル定義の議論で決める）。
"""

from pathlib import Path

import pytest

from receipt_app.config import AppConfig, Labels, load_config

REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config(REPO_CONFIG_DIR)


def test_OSMタグの対応先はすべて定義済みの店ジャンル(config: AppConfig) -> None:
    unknown = set(config.genre_map.osm_tag_to_store_genre.values()) - set(
        config.labels.store_genres
    )
    assert unknown == set()


def test_品名の語の対応先はすべて定義済みの店ジャンル(config: AppConfig) -> None:
    unknown = set(config.genre_map.item_keyword_to_store_genre.values()) - set(
        config.labels.store_genres
    )
    assert unknown == set()


def test_すべての店ジャンルに判定粒度が決まっている(config: AppConfig) -> None:
    assert set(config.genre_map.store_genre_to_granularity) == set(config.labels.store_genres)


def test_品目ジャンルの見本がすべての小分類にある(config: AppConfig) -> None:
    assert list(config.item_genre_examples) == config.labels.item_genres
    assert all(config.item_genre_examples.values())


def test_小分類から大分類を引ける() -> None:
    labels = Labels(
        store_genres=[],
        item_categories={"食材": ["肉", "魚介"], "飲み物": ["飲料"]},
    )

    assert labels.item_genres == ["肉", "魚介", "飲料"]
    assert labels.category_of("魚介") == "食材"


def test_小分類の名前が大分類をまたいで重なれば読み込みで弾く() -> None:
    with pytest.raises(ValueError):
        Labels(store_genres=[], item_categories={"食材": ["その他"], "食品以外": ["その他"]})


def test_粒度の値がwholeかper_item以外なら読み込みで弾く(tmp_path: Path) -> None:
    for name in ("labels.yaml", "thresholds.yaml", "item_genre_examples.yaml"):
        (tmp_path / name).write_text((REPO_CONFIG_DIR / name).read_text("utf-8"), "utf-8")
    (tmp_path / "genre_map.yaml").write_text(
        "osm_tag_to_store_genre: {}\nstore_genre_to_granularity:\n  飲食店: all\n", "utf-8"
    )

    with pytest.raises(ValueError):
        load_config(tmp_path)
