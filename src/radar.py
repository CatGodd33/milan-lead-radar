#!/usr/bin/env python3
"""Milano Lead Radar: descubre, puntua, geolocaliza y avisa de aperturas."""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
USER_AGENT = "MilanLeadRadar/1.0 (public small-business research project)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "it-IT,it;q=0.9,en;q=0.7"})

CATEGORIES = {
    "Ristorante": ["ristorante", "trattoria", "osteria", "pizzeria", "cucina", "restaurant"],
    "Bar / Cafeteria": ["bar", "caffè", "caffe", "caffetteria", "bakery", "brunch", "pasticceria", "gelateria", "enoteca", "cocktail"],
    "Peluquería": ["parrucchiere", "salone", "hair", "barber", "barbiere", "capelli"],
    "Belleza": ["centro estetico", "beauty", "nails", "unghie", "spa", "skincare", "benessere"],
    "Bubble tea / Street food": ["bubble tea", "street food", "wok", "poke", "fast casual"]
}

HIGH_INTENT = ["nuova apertura", "nuove aperture", "apertura", "apre", "aperto", "inaugura", "inaugurazione", "debutta", "arriva a milano"]
RECENT_WORDS = ["oggi", "domani", "questa settimana", "nei giorni scorsi", "appena aperto", "recentemente"]
CHAIN_WORDS = ["dior", "armani", "starbucks", "mcdonald", "esselunga", "hotel", "gruppo internazionale"]


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def has_term(text: str, term: str) -> bool:
    """Match complete words/phrases so `spa` does not match `spazio`."""
    return re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", text.lower()) is not None


def item_id(url: str, title: str) -> str:
    normalized = re.sub(r"\?.*$", "", url).rstrip("/").lower() or title.lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def rss_url(query: str) -> str:
    q = urllib.parse.quote_plus(f'{query} when:{CONFIG["max_age_days"]}d')
    return f"https://news.google.com/rss/search?q={q}&hl=it&gl=IT&ceid=IT:it"


def parse_date(raw: str) -> datetime:
    parsed = email.utils.parsedate_to_datetime(raw) if raw else datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_feed(query: str) -> list[dict[str, Any]]:
    response = SESSION.get(rss_url(query), timeout=25)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    rows = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=CONFIG["max_age_days"])
    for item in root.findall("./channel/item")[: CONFIG["max_results_per_query"]]:
        title = clean(item.findtext("title", ""))
        link = clean(item.findtext("link", ""))
        published = parse_date(item.findtext("pubDate", ""))
        source_node = item.find("source")
        source = clean(source_node.text if source_node is not None else "")
        description = clean(BeautifulSoup(item.findtext("description", ""), "html.parser").get_text(" "))
        if published >= cutoff:
            rows.append({"title": title, "url": link, "published": published, "source": source, "description": description, "query": query})
    return rows


def resolve_and_extract(url: str) -> dict[str, Any]:
    result: dict[str, Any] = {"final_url": url, "text": "", "emails": [], "phones": [], "instagram": []}
    try:
        response = SESSION.get(url, timeout=20, allow_redirects=True)
        response.raise_for_status()
        if "consent.google.com" in response.url:
            return result
        result["final_url"] = response.url
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = clean(soup.get_text(" "))[:16000]
        result["text"] = text
        result["emails"] = sorted(set(re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)))[:5]
        phone_matches = re.findall(r"(?:\+39\s*)?(?:0\d{1,3}|3\d{2})[\s./-]*\d{3,4}[\s./-]*\d{3,5}", text)
        result["phones"] = sorted({clean(p) for p in phone_matches})[:5]
        instagram = []
        for anchor in soup.select('a[href*="instagram.com"]'):
            href = anchor.get("href", "").split("?")[0].rstrip("/")
            if href and "/p/" not in href and "/reel/" not in href:
                instagram.append(href)
        result["instagram"] = sorted(set(instagram))[:4]
    except requests.RequestException:
        pass
    return result


def category_for(text: str) -> str:
    lowered = re.sub(r"\bvia\s+capelli\b", "", text.lower())
    scored = [(sum(1 for word in words if has_term(lowered, word)), category) for category, words in CATEGORIES.items()]
    score, category = max(scored)
    return category if score else "Otro negocio local"


def extract_business_name(title: str) -> str:
    title = re.sub(r"\s*[-|–]\s*[^-|–]{2,50}$", "", title).strip()
    patterns = [
        r"(?:apre|inaugura|arriva|debutta)\s+(?:a\s+Milano\s+)?(?:il\s+|la\s+|lo\s+|un\s+|una\s+)?([^,:]{2,55})",
        r"^([^,:]{2,55})(?:,|:|\s+apre|\s+arriva)"
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.I)
        if match:
            name = clean(match.group(1)).strip(" .\"")
            if 2 <= len(name) <= 55:
                return name
    return title[:55].strip()


def extract_address(text: str) -> str:
    patterns = [
        r"\b(?:via|viale|piazza|corso|largo|vicolo)\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ' .-]{2,45},?\s*\d{1,4}[A-Za-z]?",
        r"\b(?:via|viale|piazza|corso|largo|vicolo)\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ' .-]{2,45}(?=\s+(?:a|nel|Milano|MI)\b)"
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean(match.group(0))
    return "Milano"


def score_lead(text: str, published: datetime, contacts: dict[str, Any]) -> tuple[int, list[str]]:
    lowered = text.lower()
    age = (datetime.now(timezone.utc) - published).days
    score, reasons = 0, []
    if age <= 14:
        score += 35; reasons.append("publicación de los últimos 14 días")
    elif age <= 35:
        score += 25; reasons.append("publicación del último mes")
    else:
        score += 12; reasons.append("publicación reciente")
    if any(has_term(lowered, word) for word in HIGH_INTENT):
        score += 25; reasons.append("señal explícita de apertura")
    if any(has_term(lowered, word) for word in RECENT_WORDS):
        score += 10; reasons.append("lenguaje de apertura inmediata")
    category = category_for(lowered)
    if category != "Otro negocio local":
        score += 20; reasons.append(f"sector ideal: {category.lower()}")
    if contacts["emails"] or contacts["phones"] or contacts["instagram"]:
        score += 10; reasons.append("contacto público encontrado")
    if any(has_term(lowered, word) for word in CHAIN_WORDS):
        score -= 20; reasons.append("empresa grande: venta potencialmente más lenta")
    return max(0, min(100, score)), reasons


def pitch_for(category: str, name: str) -> dict[str, str]:
    if category == "Peluquería" or category == "Belleza":
        service = "tarjeta de fidelidad digital + recordatorios de cita"
        opener = f"He visto la reciente apertura de {name}. Podría ayudaros a hacer que cada primera cita se convierta en una segunda con una tarjeta digital y recordatorios automáticos."
    elif category == "Ristorante" or category == "Bubble tea / Street food":
        service = "menú QR + fidelización digital"
        opener = f"He visto que {name} acaba de abrir. Puedo prepararos un menú QR muy fácil de actualizar y una tarjeta digital para que quienes os prueben vuelvan pronto."
    elif category == "Bar / Cafeteria":
        service = "tarjeta de sellos digital + menú QR"
        opener = f"He visto la apertura de {name}. Vuestro tipo de negocio es perfecto para una tarjeta digital de cafés o consumiciones que convierta visitas ocasionales en clientes habituales."
    else:
        service = "web rápida + fidelización digital"
        opener = f"He visto que {name} es una actividad nueva en Milán. He preparado una idea concreta para ayudaros a captar y hacer volver clientes desde las primeras semanas."
    return {"service": service, "opener": opener}


def geocode(address: str) -> tuple[float | None, float | None]:
    if address == "Milano":
        return None, None
    try:
        response = SESSION.get("https://nominatim.openstreetmap.org/search", params={"q": f"{address}, Milano, Italia", "format": "json", "limit": 1}, timeout=20)
        response.raise_for_status()
        rows = response.json()
        if rows:
            time.sleep(1.05)
            return float(rows[0]["lat"]), float(rows[0]["lon"])
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None, None


def build_lead(item: dict[str, Any]) -> dict[str, Any]:
    extracted = resolve_and_extract(item["url"])
    combined = clean(" ".join([item["title"], item["description"], extracted["text"]]))
    name = extract_business_name(item["title"])
    category = category_for(combined)
    score, reasons = score_lead(combined, item["published"], extracted)
    address = extract_address(combined)
    lat, lon = geocode(address)
    pitch = pitch_for(category, name)
    return {
        "id": item_id(item["url"], item["title"]),
        "name": name,
        "category": category,
        "score": score,
        "published": item["published"].date().isoformat(),
        "found_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": item["source"],
        "title": item["title"],
        "url": extracted["final_url"],
        "address": address,
        "lat": lat,
        "lon": lon,
        "emails": extracted["emails"],
        "phones": extracted["phones"],
        "instagram": extracted["instagram"],
        "recommended_service": pitch["service"],
        "opener": pitch["opener"],
        "reasons": reasons,
        "status": "Nuevo"
    }


def render_email(leads: list[dict[str, Any]], dashboard_url: str) -> tuple[str, str]:
    subject = f"🔔 {len(leads)} nuevos posibles clientes en Milán"
    cards = []
    for lead in leads:
        contact = " · ".join(lead["emails"] + lead["phones"] + lead["instagram"]) or "Visita presencial / fuente"
        cards.append(f"""
        <div style="border:1px solid #ddd;border-radius:12px;padding:16px;margin:14px 0">
          <h2 style="margin:0 0 6px">{html.escape(lead['name'])} · {lead['score']}/100</h2>
          <p><b>{html.escape(lead['category'])}</b> · {html.escape(lead['published'])}<br>{html.escape(lead['address'])}</p>
          <p><b>Contacto:</b> {html.escape(contact)}</p>
          <p><b>Oportunidad:</b> {html.escape(lead['recommended_service'])}</p>
          <p><b>Frase para entrar:</b> “{html.escape(lead['opener'])}”</p>
          <p><a href="{html.escape(lead['url'])}">Ver fuente original</a></p>
        </div>""")
    dashboard = f'<p><a style="background:#111;color:white;padding:12px 18px;border-radius:8px;text-decoration:none" href="{html.escape(dashboard_url)}">Abrir panel y mapa</a></p>' if dashboard_url else ""
    body = f"<html><body style='font-family:Arial,sans-serif;max-width:760px;margin:auto'><h1>Nuevos prospectos detectados</h1>{dashboard}{''.join(cards)}<p style='color:#777'>Generado automáticamente por Milano Lead Radar.</p></body></html>"
    return subject, body


def send_email(leads: list[dict[str, Any]]) -> None:
    user = os.getenv("GMAIL_USER", "")
    password = os.getenv("GMAIL_APP_PASSWORD", "")
    recipient = os.getenv("ALERT_TO", CONFIG.get("recipient_email", ""))
    if not leads or not user or not password or not recipient:
        print("Email omitido: no hay prospectos nuevos o faltan secretos GMAIL_USER/GMAIL_APP_PASSWORD/ALERT_TO.")
        return
    repo = os.getenv("GITHUB_REPOSITORY", "")
    dashboard_url = os.getenv("DASHBOARD_URL", f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[-1]}/" if "/" in repo else "")
    subject, body = render_email(leads[: CONFIG["max_email_leads"]], dashboard_url)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = user
    message["To"] = recipient
    message.set_content("Se han detectado nuevos prospectos. Abre este email en formato HTML para verlos.")
    message.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
        smtp.login(user, password)
        smtp.send_message(message)
    print(f"Email enviado a {recipient} con {min(len(leads), CONFIG['max_email_leads'])} prospectos.")


def write_dashboard_data(leads: list[dict[str, Any]], last_run: str) -> None:
    DOCS.mkdir(exist_ok=True)
    payload = {"updated_at": last_run, "city": CONFIG["city"], "leads": leads}
    (DOCS / "leads.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true")
    args = parser.parse_args()
    state = load_json(DATA / "state.json", {"seen": [], "last_run": None})
    existing = load_json(DATA / "leads.json", [])
    existing_by_id = {lead["id"]: lead for lead in existing}
    seed_leads = load_json(DATA / "seeds.json", [])
    candidates: dict[str, dict[str, Any]] = {}
    for query in CONFIG["queries"]:
        try:
            for item in fetch_feed(query):
                key = item_id(item["url"], item["title"])
                candidates.setdefault(key, item)
        except (requests.RequestException, ET.ParseError) as exc:
            print(f"Aviso: fuente fallida para {query}: {exc}", file=sys.stderr)
    new_leads = []
    seen = set(state.get("seen", []))
    for seed in seed_leads:
        if seed.get("lat") is None and seed.get("address"):
            seed["lat"], seed["lon"] = geocode(seed["address"])
        existing_by_id[seed["id"]] = seed
        if seed["id"] not in seen:
            new_leads.append(seed)
            seen.add(seed["id"])
    for item in sorted(candidates.values(), key=lambda row: row["published"], reverse=True):
        provisional_id = item_id(item["url"], item["title"])
        if provisional_id in seen:
            continue
        headline = f"{item['title']} {item['description']}".lower()
        if not (has_term(headline, "milano") or has_term(headline, "milan")):
            continue
        if not any(has_term(headline, word) for word in HIGH_INTENT):
            continue
        lead = build_lead(item)
        seen.add(provisional_id)
        seen.add(lead["id"])
        if lead["score"] >= CONFIG["minimum_score"]:
            existing_by_id[lead["id"]] = lead
            new_leads.append(lead)
    all_leads = sorted(existing_by_id.values(), key=lambda row: (row["score"], row["published"]), reverse=True)
    last_run = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_json(DATA / "leads.json", all_leads)
    save_json(DATA / "state.json", {"seen": sorted(seen)[-5000:], "last_run": last_run})
    write_dashboard_data(all_leads, last_run)
    print(f"Detectados {len(candidates)} artículos; {len(new_leads)} prospectos nuevos; {len(all_leads)} totales.")
    if not args.no_email:
        send_email(new_leads)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
