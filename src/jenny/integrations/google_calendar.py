"""Intégration Google Calendar pour Jenny.

Permet à Jenny de :
- Lire les créneaux disponibles du prestataire en temps réel
- Créer des rendez-vous directement dans le calendrier
- Modifier un rendez-vous existant
- Annuler un rendez-vous
- Vérifier le prochain créneau disponible (urgent)

Configuration requise :
    JENNY_GOOGLE_CALENDAR_ID        — ID du calendrier (ou "primary")
    JENNY_GOOGLE_SERVICE_ACCOUNT_JSON — Chemin vers le fichier JSON credentials

Deux modes :
    1. Mode API réel : utilise google-api-python-client (production)
    2. Mode simulé : données fictives (dev/test sans credentials)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from jenny.core.config import get_settings
from jenny.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CalendarSlot:
    """Créneau disponible dans le calendrier."""

    date: str  # "2026-03-16"
    time: str  # "14:00"
    end_time: str  # "15:00"
    day_name: str  # "Lundi"
    available: bool = True


@dataclass
class CalendarEvent:
    """Événement (RDV) dans le calendrier."""

    id: str = ""
    title: str = ""
    start: str = ""  # ISO datetime
    end: str = ""  # ISO datetime
    description: str = ""
    customer_name: str = ""
    customer_email: str = ""
    customer_phone: str = ""
    service: str = ""
    status: Literal["confirmed", "cancelled", "modified"] = "confirmed"
    location: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CalendarResult:
    """Résultat d'une opération calendrier."""

    success: bool
    message: str
    event: CalendarEvent | None = None
    available_slots: list[CalendarSlot] = field(default_factory=list)
    data: dict = field(default_factory=dict)


# ── Jours de la semaine en français ──
JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


class GoogleCalendarService:
    """Service d'intégration Google Calendar.

    Gère toutes les interactions avec le calendrier du prestataire.
    Fonctionne en mode réel (API Google) ou simulé (dev/test).
    """

    def __init__(
        self,
        calendar_id: str | None = None,
        service_account_json: str | None = None,
        slot_duration_minutes: int = 60,
        opening_hour: int = 9,
        closing_hour: int = 19,
        days_ahead: int = 14,
        lunch_start: int = 12,
        lunch_end: int = 14,
    ) -> None:
        settings = get_settings()
        self.calendar_id = calendar_id or settings.google_calendar_id
        self.service_account_json = service_account_json or settings.google_service_account_json
        self.slot_duration = slot_duration_minutes
        self.opening_hour = opening_hour
        self.closing_hour = closing_hour
        self.days_ahead = days_ahead
        self.lunch_start = lunch_start
        self.lunch_end = lunch_end
        self._service = None
        self._simulated_events: list[CalendarEvent] = []

    @property
    def is_configured(self) -> bool:
        """Vérifie si Google Calendar est configuré (mode réel)."""
        return bool(self.service_account_json)

    def _get_google_service(self):
        """Initialise le client Google Calendar API (lazy loading)."""
        if self._service is not None:
            return self._service

        if not self.is_configured:
            return None

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_file(
                self.service_account_json,
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            self._service = build("calendar", "v3", credentials=credentials)
            logger.info("google_calendar.connected", calendar_id=self.calendar_id)
            return self._service
        except ImportError:
            logger.warning(
                "google_calendar.lib_not_installed",
                hint="pip install google-api-python-client google-auth",
            )
            return None
        except Exception as e:
            logger.error("google_calendar.connection_failed", error=str(e))
            return None

    # ════════════════════════════════════════════
    #  LIRE LES DISPONIBILITÉS
    # ════════════════════════════════════════════

    async def get_available_slots(
        self,
        from_date: datetime | None = None,
        days: int | None = None,
    ) -> list[CalendarSlot]:
        """Récupère les créneaux disponibles.

        Lit les événements existants dans le calendrier
        et retourne les créneaux libres.

        Args:
            from_date: Date de début (défaut: maintenant).
            days: Nombre de jours à consulter.

        Returns:
            Liste des créneaux disponibles.
        """
        start = from_date or datetime.now(UTC)
        num_days = days or self.days_ahead

        service = self._get_google_service()
        if service is not None:
            return await self._get_real_slots(service, start, num_days)
        else:
            return self._get_simulated_slots(start, num_days)

    async def _get_real_slots(self, service, start: datetime, days: int) -> list[CalendarSlot]:
        """Récupère les créneaux depuis l'API Google Calendar."""
        time_min = start.isoformat()
        time_max = (start + timedelta(days=days)).isoformat()

        try:
            events_result = (
                service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            busy_times = []
            for event in events_result.get("items", []):
                event_start = event["start"].get("dateTime", event["start"].get("date"))
                event_end = event["end"].get("dateTime", event["end"].get("date"))
                busy_times.append((event_start, event_end))

            # Générer les créneaux libres
            slots = []
            current = start.replace(hour=0, minute=0, second=0, microsecond=0)

            for day_offset in range(days):
                day = current + timedelta(days=day_offset)
                if day.weekday() == 6:  # Dimanche fermé
                    continue

                day_name = JOURS_FR[day.weekday()]

                for hour in range(self.opening_hour, self.closing_hour):
                    # Pause déjeuner
                    if self.lunch_start <= hour < self.lunch_end:
                        continue

                    slot_start = day.replace(hour=hour, minute=0)
                    slot_start + timedelta(minutes=self.slot_duration)

                    # Vérifier si le créneau est libre
                    is_busy = False
                    for busy_start, busy_end in busy_times:
                        # Comparaison simplifiée
                        if busy_start <= slot_start.isoformat() < busy_end:
                            is_busy = True
                            break

                    if not is_busy and slot_start > start:
                        slots.append(
                            CalendarSlot(
                                date=day.strftime("%Y-%m-%d"),
                                time=f"{hour:02d}:00",
                                end_time=f"{(hour + 1):02d}:00",
                                day_name=day_name,
                                available=True,
                            )
                        )

            logger.info("google_calendar.slots_fetched", count=len(slots))
            return slots

        except Exception as e:
            logger.error("google_calendar.fetch_error", error=str(e))
            return self._get_simulated_slots(start, days)

    def _get_simulated_slots(self, start: datetime, days: int) -> list[CalendarSlot]:
        """Génère des créneaux simulés (mode dev/test)."""
        slots = []
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)

        for day_offset in range(days):
            day = current + timedelta(days=day_offset)
            if day.weekday() == 6:  # Dimanche fermé
                continue

            day_name = JOURS_FR[day.weekday()]

            for hour in range(self.opening_hour, self.closing_hour):
                if self.lunch_start <= hour < self.lunch_end:
                    continue

                slot_start = day.replace(hour=hour, minute=0)

                # Simuler quelques créneaux occupés
                is_booked = any(
                    e.start.startswith(slot_start.strftime("%Y-%m-%dT%H"))
                    for e in self._simulated_events
                )

                if not is_booked and slot_start > start:
                    slots.append(
                        CalendarSlot(
                            date=day.strftime("%Y-%m-%d"),
                            time=f"{hour:02d}:00",
                            end_time=f"{(hour + 1):02d}:00",
                            day_name=day_name,
                            available=True,
                        )
                    )

        logger.info("google_calendar.simulated_slots", count=len(slots))
        return slots

    async def get_next_available_slot(self) -> CalendarSlot | None:
        """Trouve le prochain créneau disponible (le plus tôt possible).

        Parfait pour les demandes urgentes type :
        "Je veux le RDV le plus rapide possible"
        """
        slots = await self.get_available_slots(days=7)
        return slots[0] if slots else None

    # ════════════════════════════════════════════
    #  CRÉER UN RDV
    # ════════════════════════════════════════════

    async def create_event(
        self,
        title: str,
        start_datetime: str,
        end_datetime: str,
        customer_name: str = "",
        customer_email: str = "",
        customer_phone: str = "",
        service: str = "",
        description: str = "",
        location: str = "",
    ) -> CalendarResult:
        """Crée un rendez-vous dans le calendrier.

        Args:
            title: Titre du RDV (ex: "Coupe + Brushing — Marie").
            start_datetime: Début au format ISO (2026-03-16T14:00:00).
            end_datetime: Fin au format ISO.
            customer_name: Nom du client.
            customer_email: Email du client.
            customer_phone: Téléphone du client.
            service: Prestation demandée.
            description: Notes supplémentaires.
            location: Adresse du salon.

        Returns:
            CalendarResult avec l'événement créé.
        """
        event = CalendarEvent(
            title=title,
            start=start_datetime,
            end=end_datetime,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            service=service,
            description=description,
            location=location,
            status="confirmed",
        )

        google_service = self._get_google_service()
        if google_service is not None:
            return await self._create_real_event(google_service, event)
        else:
            return self._create_simulated_event(event)

    async def _create_real_event(self, service, event: CalendarEvent) -> CalendarResult:
        """Crée l'événement via l'API Google Calendar."""
        try:
            body = {
                "summary": event.title,
                "description": (
                    f"Client: {event.customer_name}\n"
                    f"Tél: {event.customer_phone}\n"
                    f"Email: {event.customer_email}\n"
                    f"Prestation: {event.service}\n\n"
                    f"{event.description}"
                ),
                "start": {"dateTime": event.start, "timeZone": "Europe/Paris"},
                "end": {"dateTime": event.end, "timeZone": "Europe/Paris"},
                "location": event.location,
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email", "minutes": 24 * 60},
                        {"method": "popup", "minutes": 60},
                    ],
                },
            }

            if event.customer_email:
                body["attendees"] = [{"email": event.customer_email}]

            result = (
                service.events()
                .insert(calendarId=self.calendar_id, body=body, sendUpdates="all")
                .execute()
            )

            event.id = result.get("id", "")

            logger.info(
                "google_calendar.event_created",
                event_id=event.id,
                start=event.start,
            )

            return CalendarResult(
                success=True,
                message=f"Rendez-vous confirmé le {event.start}",
                event=event,
            )

        except Exception as e:
            logger.error("google_calendar.create_error", error=str(e))
            return CalendarResult(
                success=False,
                message=f"Erreur lors de la création du RDV : {e}",
            )

    def _create_simulated_event(self, event: CalendarEvent) -> CalendarResult:
        """Crée un événement simulé (mode dev/test)."""
        from uuid import uuid4

        event.id = f"gcal-{uuid4().hex[:8]}"
        self._simulated_events.append(event)

        logger.info(
            "google_calendar.simulated_event_created",
            event_id=event.id,
            start=event.start,
        )

        return CalendarResult(
            success=True,
            message=f"Rendez-vous confirmé le {event.start}",
            event=event,
        )

    # ════════════════════════════════════════════
    #  MODIFIER UN RDV
    # ════════════════════════════════════════════

    async def update_event(
        self,
        event_id: str,
        new_start: str | None = None,
        new_end: str | None = None,
        new_title: str | None = None,
        new_description: str | None = None,
    ) -> CalendarResult:
        """Modifie un rendez-vous existant."""
        google_service = self._get_google_service()
        if google_service is not None:
            return await self._update_real_event(
                google_service, event_id, new_start, new_end, new_title, new_description
            )
        else:
            return self._update_simulated_event(event_id, new_start, new_end, new_title)

    async def _update_real_event(
        self,
        service,
        event_id: str,
        new_start: str | None,
        new_end: str | None,
        new_title: str | None,
        new_description: str | None,
    ) -> CalendarResult:
        """Modifie via l'API Google Calendar."""
        try:
            event = service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()

            if new_start:
                event["start"]["dateTime"] = new_start
            if new_end:
                event["end"]["dateTime"] = new_end
            if new_title:
                event["summary"] = new_title
            if new_description:
                event["description"] = new_description

            (
                service.events()
                .update(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    body=event,
                    sendUpdates="all",
                )
                .execute()
            )

            logger.info("google_calendar.event_updated", event_id=event_id)

            return CalendarResult(
                success=True,
                message=f"Rendez-vous {event_id} modifié avec succès",
                event=CalendarEvent(
                    id=event_id,
                    start=new_start or "",
                    end=new_end or "",
                    status="modified",
                ),
            )

        except Exception as e:
            logger.error("google_calendar.update_error", error=str(e))
            return CalendarResult(
                success=False,
                message=f"Erreur lors de la modification : {e}",
            )

    def _update_simulated_event(
        self,
        event_id: str,
        new_start: str | None,
        new_end: str | None,
        new_title: str | None,
    ) -> CalendarResult:
        """Modifie un événement simulé."""
        for event in self._simulated_events:
            if event.id == event_id:
                if new_start:
                    event.start = new_start
                if new_end:
                    event.end = new_end
                if new_title:
                    event.title = new_title
                event.status = "modified"

                return CalendarResult(
                    success=True,
                    message=f"Rendez-vous {event_id} modifié",
                    event=event,
                )

        return CalendarResult(
            success=False,
            message=f"Rendez-vous {event_id} non trouvé",
        )

    # ════════════════════════════════════════════
    #  ANNULER UN RDV
    # ════════════════════════════════════════════

    async def cancel_event(self, event_id: str) -> CalendarResult:
        """Annule un rendez-vous."""
        google_service = self._get_google_service()
        if google_service is not None:
            try:
                google_service.events().delete(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    sendUpdates="all",
                ).execute()

                logger.info("google_calendar.event_cancelled", event_id=event_id)

                return CalendarResult(
                    success=True,
                    message=f"Rendez-vous {event_id} annulé",
                    event=CalendarEvent(id=event_id, status="cancelled"),
                )

            except Exception as e:
                logger.error("google_calendar.cancel_error", error=str(e))
                return CalendarResult(
                    success=False,
                    message=f"Erreur lors de l'annulation : {e}",
                )
        else:
            # Mode simulé
            self._simulated_events = [e for e in self._simulated_events if e.id != event_id]
            return CalendarResult(
                success=True,
                message=f"Rendez-vous {event_id} annulé",
                event=CalendarEvent(id=event_id, status="cancelled"),
            )

    # ════════════════════════════════════════════
    #  HELPERS
    # ════════════════════════════════════════════

    async def get_day_schedule(self, date: str) -> list[CalendarEvent]:
        """Récupère tous les RDV d'une journée.

        Args:
            date: Date au format YYYY-MM-DD.

        Returns:
            Liste des événements de la journée.
        """
        google_service = self._get_google_service()
        if google_service is not None:
            try:
                time_min = f"{date}T00:00:00Z"
                time_max = f"{date}T23:59:59Z"

                result = (
                    google_service.events()
                    .list(
                        calendarId=self.calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )

                events = []
                for item in result.get("items", []):
                    events.append(
                        CalendarEvent(
                            id=item["id"],
                            title=item.get("summary", ""),
                            start=item["start"].get("dateTime", ""),
                            end=item["end"].get("dateTime", ""),
                            description=item.get("description", ""),
                            location=item.get("location", ""),
                        )
                    )
                return events

            except Exception as e:
                logger.error("google_calendar.schedule_error", error=str(e))

        # Mode simulé
        return [e for e in self._simulated_events if e.start.startswith(date)]

    async def health_check(self) -> bool:
        """Vérifie la connectivité avec Google Calendar."""
        service = self._get_google_service()
        if service is None:
            return False
        try:
            service.calendarList().list().execute()
            return True
        except Exception:
            return False
