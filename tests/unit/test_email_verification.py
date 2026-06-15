"""Tests unitaires du flux de confirmation d'email (fonctions pures).

Couvre la génération/vérification du code (hash bcrypt + expiration) et le
rendu de l'email brandé Jenny — sans base de données ni réseau.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jenny.api.auth.email_verification import (
    CODE_LENGTH,
    code_expiry,
    generate_code,
    hash_code,
    is_expired,
    verify_code,
)
from jenny.notifications.verification_email import build_verification_email


class TestCodeGeneration:
    def test_generate_code_is_six_digits(self) -> None:
        for _ in range(50):
            code = generate_code()
            assert len(code) == CODE_LENGTH
            assert code.isdigit()

    def test_codes_vary(self) -> None:
        # Très improbable d'obtenir 20 fois le même code s'ils sont aléatoires.
        codes = {generate_code() for _ in range(20)}
        assert len(codes) > 1


class TestCodeHashing:
    def test_hash_then_verify_roundtrip(self) -> None:
        code = "123456"
        hashed = hash_code(code)
        assert hashed != code  # jamais stocké en clair
        assert verify_code(code, hashed) is True

    def test_wrong_code_fails(self) -> None:
        hashed = hash_code("123456")
        assert verify_code("654321", hashed) is False

    def test_none_hash_fails(self) -> None:
        assert verify_code("123456", None) is False


class TestExpiry:
    def test_none_is_expired(self) -> None:
        assert is_expired(None) is True

    def test_past_is_expired(self) -> None:
        past = datetime.now(UTC) - timedelta(minutes=1)
        assert is_expired(past) is True

    def test_future_is_not_expired(self) -> None:
        future = datetime.now(UTC) + timedelta(minutes=5)
        assert is_expired(future) is False

    def test_naive_datetime_treated_as_utc(self) -> None:
        # SQLite renvoie des datetimes naïfs : on les traite comme UTC.
        naive_future = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        assert is_expired(naive_future) is False

    def test_code_expiry_is_in_the_future(self) -> None:
        assert code_expiry() > datetime.now(UTC)


class TestBrandedEmail:
    def test_subject_and_text_contain_code(self) -> None:
        msg = build_verification_email(to="x@y.com", code="135790", ttl_minutes=15)
        assert "135790" in msg.subject
        assert "135790" in msg.body_text
        assert msg.to == "x@y.com"

    def test_html_is_branded_and_shows_each_digit(self) -> None:
        msg = build_verification_email(to="x@y.com", code="246810", ttl_minutes=15)
        assert msg.body_html is not None
        # Identité Jenny : nom de marque + couleur corail.
        assert "Jenny" in msg.body_html
        assert "#FF7F6A" in msg.body_html or "#E5674F" in msg.body_html
        # Chaque chiffre du code est rendu dans une case dédiée.
        for digit in "246810":
            assert digit in msg.body_html

    def test_greeting_uses_first_name_and_is_escaped(self) -> None:
        msg = build_verification_email(
            to="x@y.com", code="111111", full_name="Alice <script> Martin"
        )
        # Le prénom apparaît mais le HTML est échappé (pas d'injection).
        assert "Alice" in msg.body_html
        assert "<script>" not in msg.body_html

    def test_ttl_minutes_is_displayed(self) -> None:
        msg = build_verification_email(to="x@y.com", code="222222", ttl_minutes=42)
        assert "42" in msg.body_text
        assert "42" in msg.body_html
