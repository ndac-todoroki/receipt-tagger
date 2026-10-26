"""config/*.yaml を型付きで読み込む。"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

Granularity = Literal["whole", "per_item"]


class Labels(BaseModel):
    """店ジャンルと品目ジャンルの定義（labels.yaml）。"""

    store_genres: list[str]
    item_genres: list[str]


class GenreMap(BaseModel):
    """OSMタグ→店ジャンル、店ジャンル→判定粒度の対応表（genre_map.yaml）。"""

    osm_tag_to_store_genre: dict[str, str]
    store_genre_to_granularity: dict[str, Granularity]


class Thresholds(BaseModel):
    """信頼度の閾値（thresholds.yaml）。"""

    store_genre_min_confidence: float
    item_genre_min_confidence: float


class AppConfig(BaseModel):
    """アプリ全体の設定。"""

    labels: Labels
    genre_map: GenreMap
    thresholds: Thresholds


def _read_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(config_dir: Path) -> AppConfig:
    """config_dir の YAML を読み込む。形式が違えば ValueError（pydantic の検証エラー）。"""
    return AppConfig(
        labels=Labels.model_validate(_read_yaml(config_dir / "labels.yaml")),
        genre_map=GenreMap.model_validate(_read_yaml(config_dir / "genre_map.yaml")),
        thresholds=Thresholds.model_validate(_read_yaml(config_dir / "thresholds.yaml")),
    )
