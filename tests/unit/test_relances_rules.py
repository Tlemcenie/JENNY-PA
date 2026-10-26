"""Règles pures des relances : plafond, texte, plan des offres."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from jenny.services.campaigns import SEGMENTS, first_name, footer, is_gsm, render_message, sms_parts
from jenny.services.gap_filler import (
    Candidate,
    offer_text,
    plan_offers,
    when_label,
    window_ok,
)
from jenny.services.offer_cap import can_offer, is_stop_reply

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
PARIS = ZoneInfo("Europe/Paris")


def _cust(**kw):
    base = {
        "id": uuid4(),
        "anonymized_at": None,
        "marketing_opt_out_at": None,
        "offer_window_start": None,
        "offer_window_count": 0,
        "last_offer_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


class TestCanOffer:
    def test_jamais_sollicite(self) -> None:
        assert can_offer(_cust(), NOW)

    def test_une_par_semaine(self) -> None:
        c = _cust(offer_window_start=NOW - timedelta(days=2), offer_window_count=1)
        assert not can_offer(c, NOW)
        assert can_offer(c, NOW, max_per_week=2)

    def test_fenetre_expiree(self) -> None:
        c = _cust(offer_window_start=NOW - timedelta(days=7), offer_window_count=5)
        assert can_offer(c, NOW)

    def test_stop_et_anonymise(self) -> None:
        assert not can_offer(_cust(marketing_opt_out_at=NOW), NOW)
        assert not can_offer(_cust(anonymized_at=NOW), NOW)
        assert not can_offer(None, NOW)
        assert not can_offer(_cust(), NOW, max_per_week=0)

    def test_date_naive_sqlite(self) -> None:
        naive = (NOW - timedelta(days=1)).replace(tzinfo=None)
        assert not can_offer(_cust(offer_window_start=naive, offer_window_count=1), NOW)


class TestStop:
    def test_stop(self) -> None:
        for txt in ("STOP", " stop ", "Stop.", "désinscription", "arrête"):
            assert is_stop_reply(txt), txt

    def test_pas_stop(self) -> None:
        for txt in ("", None, "stop au bruit chez vous", "ok merci", "je veux un rdv"):
            assert not is_stop_reply(txt), txt


class TestMessage:
    def test_prenom(self) -> None:
        out = render_message("Bonjour {prenom}, ça va ?", name="Léa", salon="Salon Zoé")
        assert out.startswith("Bonjour Léa, ça va ?")
        assert "assistante virtuelle" in out and "STOP" in out and "Salon Zoé" in out

    def test_sans_prenom(self) -> None:
        assert render_message("Bonjour {prenom} !", name="", salon="S").startswith("Bonjour !")
        assert render_message("{prénom}, on vous attend", name="", salon="S").startswith(
            "On vous attend"
        )

    def test_first_name(self) -> None:
        assert first_name("marie dupont") == "Marie"
        assert first_name("+33612345678") == ""
        assert first_name("lea@mail.fr") == ""
        assert first_name(None) == ""

    def test_textes_en_alphabet_sms(self) -> None:
        # un « ç » double le prix
        assert is_gsm(footer("Salon Zoe"))
        for seg in SEGMENTS.values():
            assert is_gsm(render_message(seg.suggestion, name="Marie", salon="Salon")), seg.key
        c = Candidate(source="rebook", duration=30, service="Coupe", name="Marie")
        txt = offer_text(c, salon="Salon", when="demain à 10h00", link="http://x/book/s")
        assert is_gsm(txt) and "assistante virtuelle" in txt

    def test_sms_parts(self) -> None:
        assert sms_parts("a" * 160) == 1
        assert sms_parts("a" * 161) == 2
        # « ê » hors alphabet SMS
        assert sms_parts("ê" * 71) == 2


class TestWindow:
    today = date(2026, 10, 26)  # lundi

    def _loc(self, d: int, h: int) -> datetime:
        return datetime(2026, 10, 26 + d, h, 0, tzinfo=PARIS)

    def test_matin_soir(self) -> None:
        assert window_ok("matin", self._loc(0, 10), self.today)
        assert not window_ok("le matin svp", self._loc(0, 15), self.today)
        assert window_ok("en soirée", self._loc(1, 18), self.today)
        assert not window_ok("soir", self._loc(1, 11), self.today)

    def test_jour(self) -> None:
        assert window_ok("demain", self._loc(1, 10), self.today)
        assert not window_ok("demain", self._loc(0, 10), self.today)
        assert window_ok("mardi", self._loc(1, 10), self.today)
        assert not window_ok("mercredi", self._loc(1, 10), self.today)
        assert window_ok(None, self._loc(0, 10), self.today)

    def test_label(self) -> None:
        now = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
        s = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)
        assert when_label(s, PARIS, now) == "demain à 14h00"


class TestPlan:
    def _cand(self, source="rebook", duration=30, window=None) -> Candidate:
        return Candidate(
            source=source,
            duration=duration,
            customer=SimpleNamespace(id=uuid4()),
            window=window,
        )

    def _slots(self, n: int, step: int = 30) -> list[datetime]:
        base = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
        return [base + timedelta(minutes=step * i) for i in range(n)]

    def test_une_place_par_client_sans_chevauchement(self) -> None:
        a, b = self._cand(), self._cand(duration=60)
        gaps = {30: self._slots(4), 60: self._slots(2, 60)}
        plan = plan_offers([a, b], gaps, held=[], offered=set(), tz=PARIS, today=date(2026, 10, 26))
        assert [p.candidate for p in plan] == [a, b]
        # b ne chevauche pas a
        assert plan[1].slot_start >= plan[0].slot_end

    def test_jamais_le_meme_creneau_au_meme_client(self) -> None:
        a = self._cand()
        slots = self._slots(3)
        offered = {(a.recipient_key, slots[0])}
        plan = plan_offers(
            [a], {30: slots}, held=[], offered=offered, tz=PARIS, today=date(2026, 10, 26)
        )
        assert plan[0].slot_start == slots[1]

    def test_creneau_tenu(self) -> None:
        a = self._cand()
        slots = self._slots(2)
        held = [(slots[0], slots[0] + timedelta(minutes=30))]
        plan = plan_offers(
            [a], {30: slots}, held=held, offered=set(), tz=PARIS, today=date(2026, 10, 26)
        )
        assert plan[0].slot_start == slots[1]

    def test_limite_et_doublon(self) -> None:
        a = self._cand()
        plan = plan_offers(
            [a, a, self._cand(), self._cand()],
            {30: self._slots(10)},
            held=[],
            offered=set(),
            tz=PARIS,
            today=date(2026, 10, 26),
            limit=2,
        )
        assert len(plan) == 2
        assert len({p.candidate.recipient_key for p in plan}) == 2

    def test_fenetre_liste_attente(self) -> None:
        # 8h UTC = 9h Paris : matin
        w = self._cand(source="waitlist", window="après-midi")
        slots = self._slots(16)  # 9h -> 16h30 Paris
        plan = plan_offers(
            [w], {30: slots}, held=[], offered=set(), tz=PARIS, today=date(2026, 10, 26)
        )
        assert plan[0].slot_start.astimezone(PARIS).hour >= 12
