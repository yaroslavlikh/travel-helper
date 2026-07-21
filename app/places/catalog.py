"""Bounded OSM import scopes for every current product destination."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogDestination:
    destination_id: str
    name: str
    country_code: str
    # west, south, east, north; each scope is deliberately bounded, never country-wide.
    bbox: tuple[float, float, float, float]


DESTINATIONS = {
    "sochi": CatalogDestination("sochi", "Сочи", "RU", (39.65, 43.36, 40.05, 43.65)),
    "kaliningrad": CatalogDestination(
        "kaliningrad", "Калининград", "RU", (20.35, 54.62, 20.65, 54.82)
    ),
    "antalya": CatalogDestination("antalya", "Анталья", "TR", (30.45, 36.80, 30.85, 37.10)),
    "bodrum": CatalogDestination("bodrum", "Бодрум", "TR", (27.25, 36.95, 27.55, 37.15)),
    "hurghada": CatalogDestination("hurghada", "Хургада", "EG", (33.65, 27.05, 33.95, 27.40)),
    "sharm": CatalogDestination("sharm", "Шарм-эш-Шейх", "EG", (34.15, 27.75, 34.45, 28.25)),
    "batumi": CatalogDestination("batumi", "Батуми", "GE", (41.55, 41.57, 41.72, 41.72)),
    "dubai": CatalogDestination("dubai", "Дубай", "AE", (55.05, 25.00, 55.45, 25.40)),
    "budva": CatalogDestination("budva", "Будва", "ME", (18.75, 42.25, 18.95, 42.35)),
    "phuket": CatalogDestination("phuket", "Пхукет", "TH", (98.20, 7.70, 98.45, 8.15)),
    "nhatrang": CatalogDestination("nhatrang", "Нячанг", "VN", (109.10, 12.15, 109.30, 12.35)),
    "kohsamui": CatalogDestination("kohsamui", "Самуи", "TH", (99.95, 9.35, 100.12, 9.62)),
    "krabi": CatalogDestination("krabi", "Краби", "TH", (98.75, 7.75, 99.15, 8.20)),
    "kualalumpur": CatalogDestination(
        "kualalumpur", "Куала-Лумпур", "MY", (101.55, 3.00, 101.85, 3.30)
    ),
    "langkawi": CatalogDestination("langkawi", "Лангкави", "MY", (99.60, 6.20, 100.00, 6.55)),
    "penang": CatalogDestination("penang", "Пенанг", "MY", (100.10, 5.20, 100.45, 5.60)),
    "barcelona": CatalogDestination("barcelona", "Барселона", "ES", (2.00, 41.25, 2.35, 41.50)),
    "mallorca": CatalogDestination("mallorca", "Майорка", "ES", (2.30, 39.35, 3.05, 39.80)),
    "tenerife": CatalogDestination("tenerife", "Тенерифе", "ES", (-16.95, 28.00, -16.10, 28.60)),
    "crete": CatalogDestination("crete", "Крит", "GR", (23.30, 34.80, 26.35, 35.70)),
    "rhodes": CatalogDestination("rhodes", "Родос", "GR", (27.55, 35.75, 28.30, 36.50)),
    "bali": CatalogDestination("bali", "Бали", "ID", (114.40, -8.90, 115.75, -8.00)),
    "danang": CatalogDestination("danang", "Дананг", "VN", (108.05, 15.90, 108.45, 16.25)),
    "abudhabi": CatalogDestination("abudhabi", "Абу-Даби", "AE", (54.25, 24.25, 54.65, 24.65)),
    "istanbul": CatalogDestination("istanbul", "Стамбул", "TR", (28.55, 40.80, 29.45, 41.35)),
    "sicily": CatalogDestination("sicily", "Сицилия", "IT", (13.60, 37.30, 15.50, 38.35)),
}


def catalog_destination(destination_id: str) -> CatalogDestination:
    try:
        return DESTINATIONS[destination_id.casefold()]
    except KeyError as error:
        raise ValueError(f"Unsupported catalog destination: {destination_id}") from error
