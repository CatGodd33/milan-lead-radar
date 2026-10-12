import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "src" / "radar.py"
spec = importlib.util.spec_from_file_location("radar", MODULE)
radar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(radar)


def test_category_restaurant():
    assert radar.category_for("Nuova apertura ristorante con cucina malese") == "Ristorante"


def test_category_hair():
    assert radar.category_for("Nuovo salone parrucchiere e hair spa") == "Peluquería"


def test_business_name():
    assert radar.extract_business_name("A Milano apre Noloteca, il nuovo locale") == "Noloteca"


def test_score_is_high_for_new_relevant_contactable_lead():
    contacts = {"emails": ["ciao@example.com"], "phones": [], "instagram": []}
    opening = {"days": 0, "label": "abre hoy", "confidence": "alta"}
    score, _ = radar.score_lead("nuova apertura ristorante oggi", datetime.now(timezone.utc), contacts, opening)
    assert score >= 80


def test_pitch_matches_category():
    pitch = radar.pitch_for("Peluquería", "Reborn")
    assert "fidelidad" in pitch["service"]
    assert "Reborn" in pitch["opener"]


def test_opening_recency_detects_month_old_business():
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    result = radar.opening_recency("Il locale ha aperto un mese fa a Milano", now, now)
    assert result["days"] == 30
    assert result["confidence"] == "alta"


def test_opening_recency_uses_explicit_date_near_opening_word():
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    result = radar.opening_recency("Il nuovo salone inaugura il 10 ottobre", now, now)
    assert result["days"] == 2


def test_old_opening_is_not_alerted_even_if_article_is_new():
    lead = {
        "score": 90, "article_age_days": 0, "opening_age_days": 30,
        "opening_confidence": "alta", "category": "Belleza",
    }
    eligible, problems = radar.alert_eligible(lead)
    assert not eligible
    assert any("más de una semana" in problem for problem in problems)


def test_new_high_fit_business_is_alerted():
    lead = {
        "score": 88, "article_age_days": 1, "opening_age_days": 1,
        "opening_confidence": "alta", "category": "Peluquería",
    }
    assert radar.alert_eligible(lead)[0]


def test_beauty_fit_prioritizes_loyalty():
    points, _, services = radar.commercial_fit("Belleza")
    assert points == 30
    assert "fidelización digital" in services

