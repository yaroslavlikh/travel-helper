"""Validated, non-published identity seed for the initial 60-country catalog."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COUNTRY_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "countries.seed.json"
_ISO2 = re.compile(r"^[A-Z]{2}$")
_ISO3 = re.compile(r"^[A-Z]{3}$")


class CountrySeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iso2: str
    iso3: str
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    name_ru: str = Field(min_length=2, max_length=120)
    name_en: str = Field(min_length=2, max_length=120)
    aliases: list[str] = Field(min_length=2, max_length=12)

    @field_validator("iso2", "iso3", "slug", "name_ru", "name_en", "aliases")
    @classmethod
    def normalize(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, list):
            return [" ".join(item.split()) for item in value]
        return " ".join(value.split())

    @model_validator(mode="after")
    def validate_codes_and_aliases(self) -> CountrySeed:
        if not _ISO2.fullmatch(self.iso2):
            raise ValueError("iso2 must be two uppercase letters")
        if not _ISO3.fullmatch(self.iso3):
            raise ValueError("iso3 must be three uppercase letters")
        if len({item.casefold() for item in self.aliases}) != len(self.aliases):
            raise ValueError("aliases must be unique case-insensitively")
        return self


class CountrySeedManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    countries: list[CountrySeed] = Field(min_length=60, max_length=60)

    @model_validator(mode="after")
    def validate_unique_countries(self) -> CountrySeedManifest:
        for attribute in ("iso2", "iso3", "slug"):
            values = [getattr(item, attribute) for item in self.countries]
            if len(set(values)) != len(values):
                raise ValueError(f"{attribute} must be unique")
        return self


def load_country_seed(path: Path = COUNTRY_SEED_PATH) -> CountrySeedManifest:
    """Load the reviewed catalog roadmap; it contains identity only, never support claims."""

    return CountrySeedManifest.model_validate_json(path.read_text(encoding="utf-8"))


def normalized_alias(value: str) -> str:
    """Use the same conservative identity key for bootstrap aliases and future resolver input."""

    return " ".join(re.findall(r"[\wÀ-ÿ-]+", value.casefold(), flags=re.UNICODE))
