"""passe 2 moteur : prompt en français clair."""

from __future__ import annotations

from datetime import timedelta

from jenny.engine.datetime_fr import format_fr_date, today_in
from jenny.engine.state_manager import ConversationState
from jenny.llm.prompts import PromptBuilder, slots_for_prompt


def _prompt(state: ConversationState) -> str:
    return PromptBuilder().build_system_prompt(state)


class TestSlotsEnClair:
    def test_iso_rendu_en_francais(self) -> None:
        state = ConversationState()
        day = today_in() + timedelta(days=3)
        state.set_slot("date", day.isoformat())
        state.set_slot("time", "14:30")
        state.set_slot("service", "Coupe femme")
        state.set_slot("duration", "45")
        state.set_slot("appointment_id", "4f1c0d1e-0000-0000-0000-000000000000")
        state.set_slot("operation", "reschedule")
        text = slots_for_prompt(state)
        assert format_fr_date(day) in text
        assert "heure : 14h30" in text
        assert "prestation : Coupe femme" in text
        assert "durée : 45 min" in text
        # rien d'interne ni d'iso
        assert day.isoformat() not in text
        assert "4f1c0d1e" not in text and "reschedule" not in text
        prompt = _prompt(state)
        assert f"Informations déjà connues sur le client : {text}" in prompt
        assert day.isoformat() not in prompt

    def test_heure_pile(self) -> None:
        state = ConversationState()
        state.set_slot("time", "09:00")
        assert slots_for_prompt(state) == "heure : 9h"

    def test_vieux_texte_libre(self) -> None:
        state = ConversationState()
        state.set_slot("date", "demain")
        assert format_fr_date(today_in() + timedelta(days=1)) in slots_for_prompt(state)

    def test_fuseau_du_salon(self) -> None:
        state = ConversationState()
        state.business_timezone = "Pacific/Kiritimati"
        state.set_slot("date", "demain")
        tomorrow = today_in("Pacific/Kiritimati") + timedelta(days=1)
        assert format_fr_date(tomorrow, today=tomorrow) in slots_for_prompt(state)


class TestReportCoiffeur:
    def _state(self, **extra) -> ConversationState:
        state = ConversationState()
        state.action_result = {
            "success": True,
            "operation": "reschedule",
            "when": "jeudi 29/10 à 14h00",
            **extra,
        }
        return state

    def test_coiffeur_nomme(self) -> None:
        prompt = _prompt(self._state(staff_name="Léa", staff_changed=False))
        assert "DÉPLACÉ au jeudi 29/10 à 14h00 avec Léa" in prompt
        assert "C'est maintenant" not in prompt

    def test_pas_de_doublon(self) -> None:
        state = self._state(staff_name="Léa", staff_changed=True)
        state.action_result["when"] = "jeudi 29/10 à 14h00 avec Léa"
        prompt = _prompt(state)
        assert prompt.count("avec Léa") == 1
        assert "C'est maintenant Léa" in prompt

    def test_sans_coiffeur(self) -> None:
        prompt = _prompt(self._state())
        assert "DÉPLACÉ au jeudi 29/10 à 14h00 :" in prompt


class TestNomEtConfirme:
    def test_ligne_confirmation(self) -> None:
        state = ConversationState()
        state.action_result = {
            "success": True,
            "named": True,
            "name": "Marie",
            "confirmed": True,
            "confirmed_when": "jeudi 29/10 à 14h00",
        }
        prompt = _prompt(state)
        assert "« Marie »" in prompt
        assert "(jeudi 29/10 à 14h00) est aussi CONFIRMÉ" in prompt


class TestAssistanteVirtuelle:
    def test_jamais_une_vraie_personne(self) -> None:
        prompt = _prompt(ConversationState())
        assert "assistante virtuelle" in prompt
        assert "vraie personne" not in prompt
