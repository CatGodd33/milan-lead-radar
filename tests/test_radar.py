import importlib.util
from datetime import datetime, timezone
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
    score, _ = radar.score_lead("nuova apertura ristorante oggi", datetime.now(timezone.utc), contacts)
    assert score >= 80


def test_pitch_matches_category():
    pitch = radar.pitch_for("Peluquería", "Reborn")
    assert "fidelidad" in pitch["service"]
    assert "Reborn" in pitch["opener"]

