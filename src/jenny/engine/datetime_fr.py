"""Normalisation de dates/heures en français naturel → datetime concret.

Le modèle NER extrait des expressions brutes (« mardi », « demain », « 14h »,
« 14h30 ») ; cette couche les transforme en date/heure réelles pour réserver un
rendez-vous. Pensé pour le cas coiffeur (créneaux à l'heure ou demi-heure).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta

_WEEKDAYS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


def _strip(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def parse_fr_date(text: str, *, today: date | None = None) -> date | None:
    """Convertit une expression de date FR en ``date``. None si indéterminé.

    Gère : aujourd'hui, demain, après-demain, les jours de la semaine (prochain
    jour à venir), et les formats JJ/MM ou JJ/MM/AAAA.
    """
    if not text:
        return None
    today = today or datetime.now().date()
    t = _strip(text)

    if "apres demain" in t or "apres-demain" in t:
        return today + timedelta(days=2)
    if "demain" in t:
        return today + timedelta(days=1)
    if "aujourd" in t:  # aujourd'hui
        return today

    # JJ/MM ou JJ/MM/AAAA (ou avec des tirets).
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            d = date(year, month, day)
            # Sans année explicite, une date déjà passée vise l'an prochain.
            if m.group(3) is None and d < today:
                d = date(year + 1, month, day)
            return d
        except ValueError:
            return None

    # Jour de la semaine → prochaine occurrence (>= aujourd'hui).
    for name, idx in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", t):
            delta = (idx - today.weekday()) % 7
            if delta == 0 and ("prochain" in t):
                delta = 7
            return today + timedelta(days=delta)

    return None


def parse_fr_time(text: str) -> time | None:
    """Convertit une expression d'heure FR en ``time``. None si indéterminé.

    Gère : « 14h », « 14h30 », « 14:30 », « 14 heures », « 9h », « 9 h 15 ».
    """
    if not text:
        return None
    t = _strip(text)

    m = re.search(r"\b(\d{1,2})\s*(?:h|:|heures?|heure)\s*(\d{2})?\b", t)
    if not m:
        m = re.search(r"\b(\d{1,2})\s*(?:h|:|heures?|heure)\b", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if (m.lastindex and m.group(2)) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
    return None


def combine_fr(
    date_text: str | None,
    time_text: str | None,
    *,
    now: datetime | None = None,
    default_hour: int = 10,
) -> datetime | None:
    """Combine date + heure FR en ``datetime`` (heure par défaut si absente).

    Renvoie None si la date est indéterminée (l'heure, elle, a un défaut).
    """
    now = now or datetime.now()
    d = parse_fr_date(date_text or "", today=now.date())
    if d is None:
        return None
    tm = parse_fr_time(time_text or "") or time(default_hour, 0)
    return datetime(d.year, d.month, d.day, tm.hour, tm.minute)
