"""Ordered document model produced by extract.py and consumed by the renderer."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Run:
    text: str
    bold: bool = False
    underline: bool = False


@dataclass
class Paragraph:
    runs: list[Run]
    heading: int | None = None  # 1 = top level


@dataclass
class Image:
    asset_id: str


@dataclass
class Cell:
    row: int | None
    col: int | None
    rowspan: int
    colspan: int
    blocks: list['Block']
    header: bool = False


@dataclass
class Table:
    cells: list[Cell]


Block = Paragraph | Table | Image


@dataclass
class Asset:
    id: str
    data: bytes
    ext: str  # like '.png'; '.bin' for non-raster
    media_type: str


@dataclass
class Document:
    format: str
    blocks: list[Block]
    assets: dict[str, Asset]
    warnings: list[str]
