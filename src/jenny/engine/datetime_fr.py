"""Dates et heures en français naturel."""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# fuseau par défaut
DEFAULT_TZ = "Europe/Paris"

_WEEKDAYS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}
_WD_ALT = "|".join(_WEEKDAYS)

# mois et abréviations
_MONTHS = {
    "janvier": 1,
    "janv": 1,
    "fevrier": 2,
    "fevr": 2,
    "fev": 2,
    "mars": 3,
    "avril": 4,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "juil": 7,
    "aout": 8,
    "septembre": 9,
    "sept": 9,
    "octobre": 10,
    "oct": 10,
    "novembre": 11,
    "nov": 11,
    "decembre": 12,
    "dec": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
# noms complets seulement
_FULL_MONTH_ALT = (
    "janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre"
)

# nombres en lettres
_NUM_WORDS = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "vingt": 20,
    "trente": 30,
}
_NUM_ALT = r"\d{1,3}|" + "|".join(sorted(_NUM_WORDS, key=len, reverse=True))


def _strip(text: str) -> str:
    """Minuscule, sans accents."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")  # noqa: RUF001
    return re.sub(r"\s+", " ", t).strip()


def _num(token: str) -> int | None:
    """Chiffre ou mot."""
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token)


def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def now_in(tz: str | None = None) -> datetime:
    """Heure locale du salon."""
    return datetime.now(_zone(tz))


def today_in(tz: str | None = None) -> date:
    """Date du jour au salon."""
    return now_in(tz).date()


# ── dates ──

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_DAY_MONTH_RE = re.compile(
    rf"\b(1er|premier|\d{{1,2}})(?:er)?\s+({_MONTH_ALT})\b\.?(?:\s+(\d{{4}}))?"
)
_NUMERIC_RE = re.compile(
    r"(?<![\d.,/-])\b(\d{1,2})\s*[/-]\s*(\d{1,2})(?:\s*[/-]\s*(\d{2,4}))?\b"
    r"(?!\s*(?:€|eur|%|h\b|heures?|[/-]\s*\d))"
    r"|(?<![\d.,])\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b(?!\.\d)"
)
_APRES_DEMAIN_RE = re.compile(r"\bapres[\s-]?demain\b")
_DEMAIN_RE = re.compile(r"\bdemain\b")
_TODAY_RE = re.compile(r"\baujourd(?:'?\s?hui)?|\bce\s+jour\b")
# « ce soir », souvent du bavardage
_SOFT_TODAY_RE = re.compile(
    r"\bce\s+(?:matin|soir|midi)\b|\bcet\s+apres[\s-]?midi\b|\btout\s+a\s+l'heure\b|\bcet\s+aprem\b"
)
_IN_N_RE = re.compile(rf"\b(?:dans|d'ici)\s+({_NUM_ALT})\s+(jours?|semaines?|mois)\b")
_IN_ONE_RE = re.compile(r"\b(?:dans|d'ici)\s+(?:une|un)\s+(semaine|mois)\b")
_EN_HUIT_RE = re.compile(r"\ben\s+(huit|quinze)\b")
_WD_RE = re.compile(rf"\b({_WD_ALT})\b")
_WD_DOM_RE = re.compile(rf"\b(?:{_WD_ALT})\s+(1er|\d{{1,2}})\b(?!\s*(?:h\b|h\d|heures?|:|[.,]\d))")
_NEXT_AFTER_WD_RE = re.compile(
    r"^\s*(?:prochain|de\s+la\s+semaine\s+(?:prochaine|d'apres|suivante)|"
    r"d'apres|suivant)\b"
)
_NEXT_WEEK_RE = re.compile(r"\b(?:semaine\s+(?:prochaine|d'apres|suivante)|prochaine\s+semaine)\b")
_THIS_WEEK_RE = re.compile(r"\b(?:cette\s+semaine|dans\s+la\s+semaine)\b")
_WEEKEND_RE = re.compile(r"\bweek[\s-]?ends?\b")
_MONTH_ANCHOR_RE = re.compile(
    r"\b(debut|mi|fin|courant|en|au\s+mois\s+(?:de|d')|mois\s+(?:de|d'))[\s-]*"
    rf"(?:(?:du\s+)?mois\s+(?:de\s+|d'))?({_FULL_MONTH_ALT})\b"
)
_NEXT_MONTH_RE = re.compile(r"\b(?:(debut|mi|fin)[\s-]+(?:du\s+)?)?(?:le\s+)?mois\s+prochain\b")
_THIS_MONTH_RE = re.compile(r"\b(debut|mi|fin)[\s-]+(?:du|de)\s+mois\b")
_DOM_RE = re.compile(
    r"\b(?:le|du|au|ce)\s+(1er|premier|\d{1,2})(?:er)?\b"
    r"(?!\s*(?:h\b|h\d|heures?|:|[.,]\d|€|eur|euros?|%|ans?\b|km|kg|cm|min|minutes?|"
    r"jours?|semaines?|mois\b|personnes?|fois|/|-|\d|e\b|eme|ieme|places?|clients?|"
    r"rue|avenue|av\b|bd\b|boulevard|allee|chemin|impasse|bis\b|ter\b))"
)

# jours exclus (« pas demain »)
_DAY_WORD = rf"(?:apres[\s-]?demain|demain|aujourd'?\s?hui|(?:{_WD_ALT})(?:\s+prochain)?)"
# « pourquoi pas samedi » : un oui
_NEG_BEFORE_RE = re.compile(
    r"(?<!pourquoi )\b(?:pas|sauf|hors)\s+(?:dispo(?:nibles?)?\s+|libres?\s+|possible\s+|la\s+)?"
    rf"(?:pour\s+)?(?:le\s+|ce\s+)?{_DAY_WORD}\b"
)
# « pas un souci » : pas un refus
_NOT_A_REFUSAL = (
    r"(?!\s+(?:de\s+|d'|un\s+|une\s+|du\s+tout\s+(?:un\s+)?)?"
    r"(?:soucis?|problemes?|mal|grave|inconvenients?|gene|genant)\b)"
)
_NEG_AFTER_RE = re.compile(
    rf"\b{_DAY_WORD}\s*,?\s*(?:c'est|ce\s+n'est|"
    r"ca\s+(?:ne\s+)?(?:me\s+|m'\s?)?(?:va|vas|arrange|irait|ira|m'arrange|m'arrangerait)|"
    rf"je\s+(?:ne\s+)?(?:peux|suis))\s+pas\b{_NOT_A_REFUSAL}"
)


def _day_num(token: str) -> int:
    return 1 if token in ("1er", "premier") else int(token)


def _add_months(d: date, n: int) -> date:
    """Ajoute n mois."""
    month0 = d.month - 1 + n
    y, m = d.year + month0 // 12, month0 % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _next_monday(today: date) -> date:
    return today + timedelta(days=7 - today.weekday())


def _resolve_day_month(day: int, month: int, year: int | None, today: date) -> date | None:
    """Jour + mois, sinon an suivant."""
    if year is not None:
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    y = today.year
    # 29 février : année bissextile
    for _ in range(9):
        try:
            d = date(y, month, day)
        except ValueError:
            if not (month == 2 and day == 29):
                return None
        else:
            if d >= today:
                return d
        y += 1
    return None


def _next_dom(day: int, today: date) -> date | None:
    """Prochain « le 14 »."""
    if not 1 <= day <= 31:
        return None
    y, m = today.year, today.month
    for _ in range(13):
        try:
            d = date(y, m, day)
        except ValueError:
            d = None
        if d is not None and d >= today:
            return d
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return None


def _anchor_day(where: str, y: int, month: int) -> int:
    last = calendar.monthrange(y, month)[1]
    if where == "mi":
        return 15
    if where == "fin":
        # dernière semaine
        return max(1, last - 6)
    return 1


def _month_anchor(where: str, month: int, today: date) -> date:
    """Début / mi / fin de mois."""
    y = today.year + (1 if month < today.month else 0)
    d = date(y, month, _anchor_day(where, y, month))
    return max(d, today)


def _weekday_date(t: str, m: re.Match, today: date) -> date:
    """Jour de semaine cité."""
    idx = _WEEKDAYS[m.group(1)]
    after = t[m.end() :]
    if _NEXT_AFTER_WD_RE.match(after) or _NEXT_WEEK_RE.search(t):
        # semaine suivante
        return _next_monday(today) + timedelta(days=idx)
    d = today + timedelta(days=(idx - today.weekday()) % 7)
    return _shift_en_huit(d, after)


def _shift_en_huit(d: date, t: str) -> date:
    """« mardi en huit »."""
    m = _EN_HUIT_RE.search(t)
    if m and m.start() <= 3:
        return d + timedelta(days=7 if m.group(1) == "huit" else 14)
    return d


# types de date
EXACT = "exact"
SOFT = "soft"  # « ce soir »
VAGUE = "vague"  # « le week-end »


def _kind(d: date | None, kind: str) -> tuple[date | None, str | None]:
    return (d, kind) if d is not None else (None, None)


def _parse_date(text: str, today: date | None) -> tuple[date | None, str | None]:
    """Date trouvée et son type."""
    if not text:
        return None, None
    today = today or today_in()
    t = _strip(text)
    t = _NEG_BEFORE_RE.sub(" ", t)
    t = _NEG_AFTER_RE.sub(" ", t)

    # format iso
    m = _ISO_DATE_RE.search(t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), EXACT
        except ValueError:
            return None, None

    # « 14 février »
    m = _DAY_MONTH_RE.search(t)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        d = _resolve_day_month(_day_num(m.group(1)), _MONTHS[m.group(2)], year, today)
        return _kind(d, EXACT)

    # jj/mm(/aaaa)
    m = _NUMERIC_RE.search(t)
    if m:
        if m.group(1):
            day, month, yr = m.group(1), m.group(2), m.group(3)
        else:
            day, month, yr = m.group(4), m.group(5), m.group(6)
        if not 1 <= int(month) <= 12:
            return None, None
        d = _resolve_day_month(int(day), int(month), int(yr) if yr else None, today)
        return _kind(d, EXACT)

    # demain, après-demain
    for rx, delta in ((_APRES_DEMAIN_RE, 2), (_DEMAIN_RE, 1)):
        m = rx.search(t)
        if m:
            return _shift_en_huit(today + timedelta(days=delta), t[m.end() :]), EXACT

    # dans 3 jours
    m = _IN_N_RE.search(t)
    if m:
        n = _num(m.group(1))
        unit = m.group(2)
        if n is not None and n <= 400:
            if unit.startswith("jour"):
                # 8 jours = 1 semaine
                n = {8: 7, 15: 14}.get(n, n)
                return today + timedelta(days=n), EXACT
            if unit.startswith("semaine"):
                return today + timedelta(weeks=n), EXACT
            # jour du mois deviné
            return _add_months(today, n), VAGUE
    m = _IN_ONE_RE.search(t)
    if m:
        if m.group(1) == "semaine":
            return today + timedelta(weeks=1), EXACT
        return _add_months(today, 1), VAGUE

    # « mardi 14 »
    m = _WD_DOM_RE.search(t)
    if m:
        d = _next_dom(_day_num(m.group(1)), today)
        if d is not None:
            return d, EXACT

    # jour de semaine
    m = _WD_RE.search(t)
    if m:
        return _weekday_date(t, m, today), EXACT

    # week-end
    m = _WEEKEND_RE.search(t)
    if m:
        around = t[max(0, m.start() - 12) : m.end() + 12]
        if "prochain" in around:
            return _next_monday(today) + timedelta(days=5), VAGUE
        if today.weekday() >= 5:
            return today, VAGUE
        return today + timedelta(days=5 - today.weekday()), VAGUE

    # semaine prochaine
    if _NEXT_WEEK_RE.search(t):
        return _next_monday(today), VAGUE
    if _THIS_WEEK_RE.search(t):
        return today, VAGUE

    # début mars, fin du mois
    m = _MONTH_ANCHOR_RE.search(t)
    if m:
        where = m.group(1) if m.group(1) in ("debut", "mi", "fin") else "debut"
        return _month_anchor(where, _MONTHS[m.group(2)], today), VAGUE
    m = _NEXT_MONTH_RE.search(t)
    if m:
        nxt = _add_months(today.replace(day=1), 1)
        return nxt.replace(day=_anchor_day(m.group(1) or "debut", nxt.year, nxt.month)), VAGUE
    m = _THIS_MONTH_RE.search(t)
    if m:
        d = today.replace(day=_anchor_day(m.group(1), today.year, today.month))
        return max(d, today), VAGUE

    # « le 14 »
    m = _DOM_RE.search(t)
    if m:
        return _kind(_next_dom(_day_num(m.group(1)), today), EXACT)

    # aujourd'hui en dernier
    m = _TODAY_RE.search(t)
    if m:
        return _shift_en_huit(today, t[m.end() :]), EXACT
    m = _SOFT_TODAY_RE.search(t)
    if m:
        return _shift_en_huit(today, t[m.end() :]), SOFT

    return None, None


def parse_fr_date(text: str, *, today: date | None = None) -> date | None:
    """Expression de date FR vers ``date``, None si flou."""
    return _parse_date(text, today)[0]


def fr_date_kind(text: str, *, today: date | None = None) -> str | None:
    """Date exacte, douce ou floue ?"""
    return _parse_date(text, today)[1]


# ── heures ──

_REL_TIME_RE = re.compile(
    r"\b(?:dans|d'ici)\s+(?:\d{1,2}|une?|deux|trois|quatre)\s*(?:h|heures?)(?![a-z])(?:\s*\d{2})?"
)
_DURATION_CTX_RE = re.compile(
    r"\b(?:dure|durent|durer|duree|pendant|prend|prendra|prennent|compter|comptez|faut)\s+"
    r"(?:environ\s+|a\s+peu\s+pres\s+|au\s+moins\s+|bien\s+|plus\s+de\s+|moins\s+de\s+|"
    r"presque\s+)?\d{1,2}\s*(?:h|heures?)(?![a-z])(?:\s*\d{2})?"
)
_NEG_TIME_RE = re.compile(
    r"(?<!pourquoi )\bpas\s+(?:a\s+)?(?:\d{1,2}\s*(?:h|heures?|:)(?:\s*\d{2})?|midi|minuit)"
    r"(?![a-z\d])"
)
_HM_RE = re.compile(r"(?<![\d:,.])(\d{1,2})\s*(?:h|heures?|:)(?![a-z])\s*(\d{2})?(?!\d)")
_MIDI_RE = re.compile(r"(?<!apres-)(?<!apres )(?<!avant )\b(midi|minuit)\b")
_MIDI_MIN_RE = re.compile(r"^\s*(\d{2})\b(?!\s*(?:€|eur|%|min|h\b|heures?))")
_BARE_RE = re.compile(
    # « est à 15 » = un prix
    r"(?<!il y )(?<!est )(?<!sont )(?<!coute )(?<!coutent )\b(?:a|vers)\s+(\d{1,2})"
    r"(?=\s*(?:$|[?!.,;)]|(?:et|ou|svp|stp|s'il|c'est|ca|si|plutot|alors|merci|le|la|les|"
    r"ce|cet|cette|demain|apres|avant|pile|precises?|tapantes?|environ)\b))"
)
_HALF_RE = re.compile(r"^\s*(?:et\s+(demie?|quart)|moins\s+(?:le\s+)?(quart)|moins\s+(\d{1,2}))\b")
_PM_RE = re.compile(
    r"^\s*(?:du\s+soir|de\s+l'apres[\s-]?midi|de\s+l'aprem|l'apres[\s-]?midi|ce\s+soir|"
    r"cet\s+apres[\s-]?midi|le\s+soir|l'aprem)\b"
)


def _apply_modifiers(hour: int, minute: int, after: str) -> time | None:
    """Et demie, du soir..."""
    m = _HALF_RE.match(after)
    if m:
        if m.group(1):
            minute += 30 if m.group(1).startswith("demi") else 15
        else:
            minute -= 15 if m.group(2) else int(m.group(3))
        after = after[m.end() :]
        if minute < 0:
            hour, minute = (hour - 1) % 24, minute + 60
        elif minute >= 60:
            hour, minute = hour + 1, minute - 60
    if 1 <= hour < 12 and _PM_RE.match(after):
        hour += 12
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour, minute)
    return None


def parse_fr_time(text: str) -> time | None:
    """Expression d'heure FR vers ``time``, None si flou."""
    if not text:
        return None
    t = _strip(text)
    # durées et heures relatives
    for rx in (_REL_TIME_RE, _DURATION_CTX_RE, _NEG_TIME_RE):
        t = rx.sub(" ", t)

    found: list[tuple[int, time]] = []
    for m in _HM_RE.finditer(t):
        minute = int(m.group(2)) if m.group(2) else 0
        tm = _apply_modifiers(int(m.group(1)), minute, t[m.end() :])
        if tm is not None:
            found.append((m.start(), tm))
            break
    m = _MIDI_RE.search(t)
    if m:
        base = 12 if m.group(1) == "midi" else 0
        after = t[m.end() :]
        mm = _MIDI_MIN_RE.match(after)
        if mm:
            tm = _apply_modifiers(base, int(mm.group(1)), "")
        else:
            tm = _apply_modifiers(base, 0, after)
        if tm is not None:
            found.append((m.start(), tm))
    if found:
        return min(found, key=lambda x: x[0])[1]

    # « à 14 » sans h
    m = _BARE_RE.search(t)
    if m and 8 <= int(m.group(1)) <= 20:
        return time(int(m.group(1)), 0)
    return None


# ── durées ──

_DUR_H_RE = re.compile(
    r"(\d{1,2}|une?|deux|trois|quatre|cinq)\s*(?:h|heures?)(?![a-z])"
    r"\s*(?:et\s+(demie?|quart)|(\d{1,2})\s*(?:min(?:utes?)?)?)?"
)
_DUR_MIN_RE = re.compile(r"(\d{1,3})\s*(?:min(?:utes?)?|mn)\b")


def parse_fr_duration(text: str) -> int | None:
    """Durée FR en minutes."""
    t = _strip(text)
    if not t:
        return None
    minutes: int | None = None
    m = _DUR_H_RE.search(t)
    if m:
        h = _num(m.group(1)) or 0
        minutes = h * 60
        if m.group(2):
            minutes += 30 if m.group(2).startswith("demi") else 15
        elif m.group(3):
            minutes += int(m.group(3))
    elif re.search(r"\bdemi[\s-]?heure\b", t):
        minutes = 30
    else:
        m = _DUR_MIN_RE.search(t) or re.fullmatch(r"(\d{1,3})", t)
        if m:
            minutes = int(m.group(1))
    if minutes is None or not 5 <= minutes <= 600:
        return None
    return minutes


# ── formes absolues ──

_MONTH_LABELS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def format_fr_date(value: str | date | None, *, today: date | None = None) -> str | None:
    """Date en clair, « jeudi 29 octobre »."""
    d = value if isinstance(value, date) else parse_fr_date(value or "", today=today)
    if d is None:
        return None
    label = f"{list(_WEEKDAYS)[d.weekday()]} {d.day} {_MONTH_LABELS[d.month - 1]}"
    # année si pas celle-ci
    if d.year != (today or today_in()).year:
        label += f" {d.year}"
    return label


def format_fr_time(value: str | time | None) -> str | None:
    """Heure en clair, « 14h » ou « 14h30 »."""
    t = value if isinstance(value, time) else parse_fr_time(value or "")
    if t is None:
        return None
    return f"{t.hour}h" if t.minute == 0 else f"{t.hour}h{t.minute:02d}"


def to_iso_date(text: str, *, today: date | None = None) -> str | None:
    """Date FR vers AAAA-MM-JJ."""
    d = parse_fr_date(text, today=today)
    return d.isoformat() if d else None


def to_hhmm(text: str) -> str | None:
    """Heure FR vers HH:MM."""
    tm = parse_fr_time(text)
    return tm.strftime("%H:%M") if tm else None


def combine_fr(
    date_text: str | None,
    time_text: str | None,
    *,
    now: datetime | None = None,
    default_hour: int = 10,
    tz: str | None = None,
) -> datetime | None:
    """Date + heure FR en ``datetime`` naïf local."""
    now = now or now_in(tz)
    d = parse_fr_date(date_text or "", today=now.date())
    if d is None:
        return None
    tm = parse_fr_time(time_text or "") or time(default_hour, 0)
    return datetime(d.year, d.month, d.day, tm.hour, tm.minute)
