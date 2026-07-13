from app.services.extraction import extract_travel_request


def test_extracts_user_supplied_travel_constraints() -> None:
    request = extract_travel_request(
        "Живу в Москве, хочу улететь на море в августе на 7–10 дней, "
        "бюджет 150 тысяч рублей на одного, не люблю сильную жару"
    )

    assert request.origin_city == "Москва"
    assert request.month == 8
    assert request.duration_nights_min == 7
    assert request.duration_nights_max == 10
    assert request.budget_total_rub == 150_000
    assert request.adults == 1
    assert request.sea_required is True
    assert request.heat_tolerance == "low"
    assert request.destination_scope is None


def test_answers_merge_without_rewriting_known_request_fields() -> None:
    request = extract_travel_request(
        "Из Москвы в августе на море, бюджет 150 тысяч на одного",
        {"destination_scope": "international", "visa_willingness": "no_visa"},
    )

    assert request.origin_city == "Москва"
    assert request.destination_scope == "international"
    assert request.visa_willingness == "no_visa"
