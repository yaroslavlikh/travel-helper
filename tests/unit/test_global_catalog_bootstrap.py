from __future__ import annotations

from app.geography.bootstrap import load_country_seed, normalized_alias


def test_initial_global_catalog_has_the_planned_sixty_unique_countries() -> None:
    countries = load_country_seed().countries

    assert len(countries) == 60
    assert {country.iso2 for country in countries} >= {"RU", "TH", "MY", "CN", "JP", "FR", "KE"}
    assert len({country.slug for country in countries}) == 60


def test_country_aliases_normalize_for_russian_and_english_input() -> None:
    countries = {country.iso2: country for country in load_country_seed().countries}

    assert normalized_alias("  ОАЭ ") in {
        normalized_alias(alias) for alias in countries["AE"].aliases
    }
    assert normalized_alias("Малазия") in {
        normalized_alias(alias) for alias in countries["MY"].aliases
    }
