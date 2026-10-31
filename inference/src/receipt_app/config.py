"""config/*.yaml を型付きで読み込む。"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

Granularity = Literal["whole", "per_item"]


class Labels(BaseModel):
    """店ジャンルと品目ジャンルの定義（labels.yaml）。

    品目ジャンルは大分類→小分類の2段。item_categories は大分類ごとの小分類の一覧。
    """

    store_genres: list[str]
    item_categories: dict[str, list[str]]

    @model_validator(mode="after")
    def _unique_genres(self) -> "Labels":
        # 小分類から大分類を一意に引けるように、小分類の名前は全体で重ならないようにする
        if len(self.item_genres) != len(set(self.item_genres)):
            raise ValueError("品目ジャンルの小分類の名前が重なっている")
        return self

    @property
    def item_genres(self) -> list[str]:
        """小分類の一覧（大分類の順）。"""
        return [g for genres in self.item_categories.values() for g in genres]

    def category_of(self, genre: str) -> str:
        """小分類が属する大分類。"""
        return next(c for c, genres in self.item_categories.items() if genre in genres)


class GenreMap(BaseModel):
    """OSMタグ→店ジャンル、店ジャンル→判定粒度の対応表（genre_map.yaml）。"""

    osm_tag_to_store_genre: dict[str, str]
    store_genre_to_granularity: dict[str, Granularity]
    # 品名に含まれる語→店ジャンル。検索の結果より優先する
    item_keyword_to_store_genre: dict[str, str] = {}


class Thresholds(BaseModel):
    """信頼度の閾値（thresholds.yaml）。"""

    store_genre_min_confidence: float
    item_genre_min_confidence: float
    item_genre_temperature: float


class AppConfig(BaseModel):
    """アプリ全体の設定。"""

    labels: Labels
    genre_map: GenreMap
    thresholds: Thresholds
    item_genre_examples: dict[str, list[str]]


def _read_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(config_dir: Path) -> AppConfig:
    """config_dir の YAML を読み込む。形式が違えば ValueError（pydantic の検証エラー）。"""
    return AppConfig(
        labels=Labels.model_validate(_read_yaml(config_dir / "labels.yaml")),
        genre_map=GenreMap.model_validate(_read_yaml(config_dir / "genre_map.yaml")),
        thresholds=Thresholds.model_validate(_read_yaml(config_dir / "thresholds.yaml")),
        item_genre_examples=_read_yaml(config_dir / "item_genre_examples.yaml"),  # type: ignore[arg-type]
    )
