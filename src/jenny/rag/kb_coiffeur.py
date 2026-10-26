"""Fiches KB coiffeur, tirées des données du salon.

Deux jeux :
- démo : le salon démo, avec des faits inventés (adresse, équipe...) ;
- réel : uniquement ce que la base sait (horaires, prestations,
  acompte, rappels, équipe) ou ce que Jenny fait vraiment.
"""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

DEMO_SLUG = "demo"
SEED_TAG = "seed_kb_coiffeur"

# sujets non couverts exprès
UNCOVERED_TOPICS = ("extensions", "lissage brésilien / kératine", "maquillage", "recrutement")

_DAYS = [
    ("mon", "lundi"),
    ("tue", "mardi"),
    ("wed", "mercredi"),
    ("thu", "jeudi"),
    ("fri", "vendredi"),
    ("sat", "samedi"),
    ("sun", "dimanche"),
]


def slugify(text: str) -> str:
    """Nom → clé ascii."""
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def fmt_price(cents: int) -> str:
    """3900 → « 39 € »."""
    euros, rest = divmod(int(cents), 100)
    return f"{euros} €" if rest == 0 else f"{euros},{rest:02d} €"


def fmt_duration(minutes: int) -> str:
    """90 → « 1h30 »."""
    h, m = divmod(int(minutes), 60)
    if h == 0:
        return f"{m} min"
    return f"{h}h{m:02d}" if m else f"{h} h"


def fmt_hour(hhmm: str) -> str:
    """« 09:00 » → « 9h »."""
    h, _, m = hhmm.partition(":")
    return f"{int(h)}h{m}" if m and m != "00" else f"{int(h)}h"


def _join_fr(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " et " + items[-1]


_HHMM_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _day_range(rng) -> tuple[str, str] | None:
    """Plage « HH:MM » valide ou None."""
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        return None
    a, b = rng
    if not (isinstance(a, str) and isinstance(b, str)):
        return None
    if not (_HHMM_RE.match(a) and _HHMM_RE.match(b)):
        return None
    return a, b


def has_hours(hours: dict | None) -> bool:
    """Au moins un jour ouvert ?"""
    return isinstance(hours, dict) and any(_day_range(hours.get(k)) for k, _ in _DAYS)


def describe_hours(hours: dict | None) -> tuple[str, list[str], dict[str, tuple[str, str]]]:
    """Phrase horaires, jours fermés, plages."""
    hours = hours if isinstance(hours, dict) else {}
    open_days: dict[str, tuple[str, str]] = {}
    closed: list[str] = []
    for key, label in _DAYS:
        rng = _day_range(hours.get(key))
        if rng:
            open_days[label] = rng
        else:
            closed.append(label)
    # jours groupés par plage
    groups: dict[tuple[str, str], list[str]] = {}
    for label, rng in open_days.items():
        groups.setdefault(rng, []).append(label)
    parts = [
        f"le {_join_fr(days)} de {fmt_hour(a)} à {fmt_hour(b)}" for (a, b), days in groups.items()
    ]
    sentence = "Le salon est ouvert " + _join_fr(parts) + "."
    if closed:
        sentence += " Il est fermé " + _join_fr([f"le {d}" for d in closed]) + "."
    return sentence, closed, open_days


# descriptions par prestation
_PRESTA_TEXT = {
    "coupe femme": (
        "Elle comprend le shampoing, la coupe et un séchage simple. Le brushing complet "
        "est en supplément ({brushing})."
    ),
    "coupe homme": "Elle inclut le shampoing, la coupe aux ciseaux ou à la tondeuse et le coiffage.",
    "degrade a la lame": (
        "C'est notre spécialité homme : contours nets et dégradé progressif sur cheveux courts. "
        "Pour une coupe complète, choisissez la coupe homme."
    ),
    "brushing": (
        "Il comprend le shampoing et la mise en forme à la brosse et au sèche-cheveux, "
        "lisse ou wavy au choix."
    ),
    "coloration": (
        "Elle couvre les racines ou toute la longueur ; shampoing et soin après couleur "
        "sont inclus."
    ),
    "balayage": (
        "Mèches peintes à main levée pour un éclaircissement naturel et lumineux. Un "
        "diagnostic couleur est conseillé avant un premier balayage."
    ),
    "soin profond": (
        "Il nourrit et répare les cheveux secs ou abîmés, et peut s'ajouter à n'importe "
        "quelle prestation."
    ),
    "barbe": "La taille de barbe comprend la tonte, les contours au rasoir et une serviette chaude.",
}


def _find(prestas: list[dict], name: str) -> dict | None:
    for p in prestas:
        if slugify(p["name"]).replace("-", " ") == name:
            return p
    return None


def _demo_entries(business: dict, prestations: list[dict]) -> list[dict]:
    """Fiches du salon démo (faits inventés)."""
    entries: list[dict] = []

    def add(key: str, title: str, category: str, content: str) -> None:
        entries.append({"key": key, "title": title, "category": category, "content": content})

    prestas = [p for p in prestations if p.get("is_active", True)]

    # ── horaires (depuis la base) ──
    sentence, closed, open_days = describe_hours(business.get("business_hours"))
    add("horaires-semaine", "Horaires d'ouverture", "horaires", sentence)
    late = {d: r for d, r in open_days.items() if int(r[1].split(":")[0]) >= 20}
    for day, (_a, b) in late.items():
        last = f"{int(b.split(':')[0]) - 1}h"
        add(
            "horaires-nocturne",
            f"Nocturne du {day}",
            "horaires",
            f"Le {day}, le salon reste ouvert jusqu'à {fmt_hour(b)} : pratique pour venir "
            f"après le travail. Les derniers rendez-vous du {day} commencent à {last}.",
        )
        break
    if closed:
        add(
            "horaires-fermeture",
            "Jours de fermeture",
            "horaires",
            "Le salon est fermé "
            + _join_fr([f"le {d}" for d in closed])
            + ", ainsi que les jours fériés.",
        )
    if "samedi" in open_days:
        a, b = open_days["samedi"]
        add(
            "horaires-samedi",
            "Ouverture le samedi",
            "horaires",
            f"Le samedi, nous sommes ouverts de {fmt_hour(a)} à {fmt_hour(b)}. C'est la "
            "journée la plus demandée : pensez à réserver quelques jours à l'avance.",
        )
    add(
        "horaires-midi",
        "Pause déjeuner",
        "horaires",
        "Le salon ne ferme pas à midi : nous vous accueillons en continu pendant les heures "
        "d'ouverture.",
    )
    add(
        "horaires-conges",
        "Congés annuels",
        "horaires",
        "Le salon ferme deux semaines en août, en général les deux premières. Les dates "
        "exactes sont annoncées un mois avant sur nos réseaux et dans ce chat.",
    )
    add(
        "horaires-dernier-rdv",
        "Dernier rendez-vous de la journée",
        "horaires",
        "Le dernier rendez-vous est pris 1 heure avant la fermeture pour une coupe, et "
        "2 heures avant pour une coloration ou un balayage.",
    )

    # ── prestations (depuis la base) ──
    brushing = _find(prestas, "brushing")
    brushing_price = fmt_price(brushing["price_cents"]) if brushing else "25 €"
    grid = [
        f"- {p['name']} : {fmt_price(p['price_cents'])} ({fmt_duration(p['duration_minutes'])})"
        for p in prestas
    ]
    if grid:
        add("tarifs-grille", "Grille des tarifs", "tarifs", "Nos tarifs :\n" + "\n".join(grid))
    for p in prestas:
        norm = slugify(p["name"]).replace("-", " ")
        extra = _PRESTA_TEXT.get(norm, (p.get("description") or "").strip())
        extra = extra.format(brushing=brushing_price) if extra else ""
        content = (
            f"{p['name']} : {fmt_price(p['price_cents'])}, environ "
            f"{fmt_duration(p['duration_minutes'])}. {extra}"
        ).strip()
        add(f"presta-{slugify(p['name'])}", p["name"], "prestations", content)

    femme = _find(prestas, "coupe femme")
    homme = _find(prestas, "coupe homme")
    coloration = _find(prestas, "coloration")
    if femme and coloration:
        total = femme["price_cents"] + coloration["price_cents"]
        promo = total - 500
        add(
            "forfait-coupe-couleur",
            "Forfait coupe + couleur",
            "tarifs",
            f"Coupe femme et coloration le même jour : {fmt_price(promo)} au lieu de "
            f"{fmt_price(total)}. Comptez environ "
            f"{fmt_duration(femme['duration_minutes'] + coloration['duration_minutes'])}.",
        )
    if femme or homme:
        parts = []
        if femme:
            parts.append(f"coupe femme {fmt_price(round(femme['price_cents'] * 0.7))}")
        if homme:
            parts.append(f"coupe homme {fmt_price(round(homme['price_cents'] * 0.7))}")
        add(
            "tarif-enfant",
            "Coupe enfant",
            "enfants",
            "Les enfants de moins de 12 ans ont 30 % de réduction sur la coupe : "
            f"{_join_fr(parts)}. Réservez la coupe correspondante, la remise est faite en caisse.",
        )
    add(
        "supplement-cheveux-longs",
        "Supplément cheveux longs",
        "tarifs",
        "Pour les cheveux longs (sous les omoplates) ou très épais, un supplément de 10 € "
        "s'applique sur la coloration, le balayage et le brushing. Il est annoncé avant la "
        "prestation.",
    )
    add(
        "prix-ttc",
        "Prix affichés",
        "tarifs",
        "Tous nos prix sont TTC, en euros. Le prix final est confirmé avant de commencer, "
        "notamment si un supplément cheveux longs s'applique.",
    )
    add(
        "devis",
        "Devis gratuit",
        "tarifs",
        "Pour une prestation sur mesure (mariage, gros changement de couleur), Jenny peut "
        "vous préparer un devis détaillé gratuit, envoyé en PDF.",
    )
    add(
        "soin-olaplex",
        "Soin Olaplex",
        "prestations",
        "Le soin Olaplex répare la fibre abîmée par les couleurs et décolorations. Il "
        "s'ajoute à une coloration ou un balayage pour 15 € de plus.",
    )

    # ── annulation, retard, acompte ──
    add(
        "annulation-delai",
        "Annuler un rendez-vous",
        "politique",
        "Vous pouvez annuler gratuitement jusqu'à 24 heures avant votre rendez-vous, "
        "directement dans ce chat ou par e-mail.",
    )
    add(
        "annulation-tardive",
        "Annulation tardive",
        "politique",
        "En cas d'annulation moins de 24 heures avant le rendez-vous, l'acompte versé est "
        "conservé par le salon. Sans acompte, rien n'est facturé la première fois.",
    )
    add(
        "no-show",
        "Rendez-vous non honoré",
        "politique",
        "Si vous ne venez pas sans prévenir, l'acompte est conservé. Après deux absences non "
        "prévenues, un acompte est demandé pour toute nouvelle réservation.",
    )
    add(
        "report-rdv",
        "Déplacer un rendez-vous",
        "rendez-vous",
        "Pour déplacer votre rendez-vous, écrivez-nous ici : Jenny vous propose les créneaux "
        "libres. Le report est gratuit plus de 24 h à l'avance, et l'acompte suit le nouveau "
        "créneau.",
    )
    add(
        "retard",
        "En cas de retard",
        "politique",
        "En cas de retard, prévenez-nous dès que possible. Jusqu'à 15 minutes de retard, la "
        "prestation est maintenue ; au-delà, elle peut être écourtée ou reportée.",
    )
    if business.get("deposit_enabled"):
        pct = int(business.get("deposit_percent") or 0)
        mini = fmt_price(int(business.get("deposit_min_cents") or 0))
        add(
            "acompte-montant",
            "Acompte à la réservation",
            "politique",
            f"Un acompte de {pct} % du prix de la prestation (minimum {mini}) est demandé pour "
            "confirmer la réservation. Il est déduit du montant à régler le jour du rendez-vous.",
        )
    else:
        add(
            "acompte-montant",
            "Acompte à la réservation",
            "politique",
            "Aucun acompte n'est demandé à la réservation : vous réglez tout au salon.",
        )
    add(
        "acompte-paiement",
        "Payer l'acompte",
        "paiement",
        "L'acompte se règle en ligne par carte bancaire, via le lien sécurisé envoyé après la "
        "réservation. Le rendez-vous est confirmé dès réception du paiement.",
    )
    add(
        "acompte-remboursement",
        "Remboursement de l'acompte",
        "politique",
        "L'acompte est remboursé en totalité si vous annulez plus de 24 heures avant, ou si "
        "le salon doit annuler. Le remboursement arrive sous 5 à 10 jours sur votre carte.",
    )
    day_h = int(business.get("day_reminder_lead_hours") or 0)
    short_m = int(business.get("reminder_lead_minutes") or 0)
    rappels = []
    if day_h:
        rappels.append("la veille (24 h avant)" if day_h == 24 else f"{day_h} h avant")
    if short_m:
        rappels.append("1 heure avant" if short_m == 60 else f"{short_m} minutes avant")
    if rappels:
        add(
            "rappels",
            "Rappels de rendez-vous",
            "rendez-vous",
            f"Vous recevez un rappel {_join_fr(rappels)} votre rendez-vous, par message.",
        )

    # ── réservation ──
    add(
        "reserver",
        "Prendre rendez-vous",
        "rendez-vous",
        "Vous pouvez réserver directement dans ce chat, 7j/7 et 24h/24 : indiquez la "
        "prestation et le jour souhaité, Jenny vérifie l'agenda et propose les créneaux libres.",
    )
    add(
        "confirmation",
        "Confirmation de réservation",
        "rendez-vous",
        "Après chaque réservation, vous recevez une confirmation avec la date, l'heure et la "
        "prestation. Si elle n'arrive pas, regardez vos spams ou redemandez-la ici.",
    )
    add(
        "liste-attente",
        "Liste d'attente",
        "rendez-vous",
        "Si le créneau souhaité est complet, Jenny peut vous inscrire sur la liste d'attente : "
        "vous êtes prévenu dès qu'une place se libère.",
    )
    add(
        "sans-rdv",
        "Venir sans rendez-vous",
        "rendez-vous",
        "Nous travaillons surtout sur rendez-vous. Sans rendez-vous, nous vous prenons si un "
        "coiffeur est libre, plutôt en semaine le matin ; le samedi, c'est rarement possible.",
    )
    add(
        "reserver-avance",
        "Réserver longtemps à l'avance",
        "rendez-vous",
        "Les réservations sont ouvertes jusqu'à 2 mois à l'avance. Pour le samedi et les "
        "veilles de fêtes, réservez au moins une semaine avant.",
    )
    add(
        "rdv-plusieurs",
        "Rendez-vous à plusieurs",
        "rendez-vous",
        "Vous pouvez réserver pour plusieurs personnes à la suite, par exemple un parent et "
        "ses enfants : dites-le à Jenny, elle cherche des créneaux qui se suivent.",
    )
    add(
        "attente",
        "Temps d'attente",
        "rendez-vous",
        "Grâce aux rendez-vous, l'attente au salon dépasse rarement 5 minutes. Merci "
        "d'arriver à l'heure prévue.",
    )

    # ── paiement ──
    add(
        "paiement-moyens",
        "Moyens de paiement",
        "paiement",
        "Nous acceptons la carte bancaire (y compris sans contact), les espèces, Apple Pay et "
        "Google Pay.",
    )
    add(
        "paiement-cheques",
        "Chèques",
        "paiement",
        "Les chèques ne sont plus acceptés au salon depuis janvier 2025.",
    )
    add(
        "paiement-plusieurs-fois",
        "Payer en plusieurs fois",
        "paiement",
        "Le paiement en 3 fois sans frais est possible par carte bancaire à partir de 150 €, "
        "par exemple pour un forfait mariage.",
    )
    add(
        "paiement-quand",
        "Quand régler",
        "paiement",
        "Le règlement se fait au salon à la fin de la prestation, en déduisant l'acompte "
        "éventuellement versé en ligne.",
    )
    add(
        "pourboire",
        "Pourboires",
        "paiement",
        "Les pourboires ne sont jamais obligatoires. Une boîte est à disposition à l'accueil "
        "et tout est partagé entre l'équipe.",
    )
    add(
        "facture",
        "Facture",
        "paiement",
        "Une facture peut vous être remise sur simple demande à l'accueil, ou envoyée par "
        "e-mail après votre passage.",
    )
    add(
        "carte-cadeau",
        "Cartes cadeaux",
        "paiement",
        "Des cartes cadeaux sont disponibles à l'accueil ou par e-mail, du montant de votre "
        "choix dès 20 €. Elles sont valables 12 mois sur toutes les prestations et produits.",
    )
    threshold = int(business.get("loyalty_threshold") or 0)
    if threshold:
        add(
            "fidelite",
            "Programme fidélité",
            "fidelite",
            f"Au bout de {threshold} rendez-vous honorés, un soin profond vous est offert à la "
            "visite suivante. Le compteur est suivi automatiquement, rien à présenter.",
        )

    # ── diagnostic et conseils ──
    add(
        "diagnostic",
        "Diagnostic offert",
        "prestations",
        "Avant une coloration, un balayage ou un gros changement de coupe, nous proposons un "
        "diagnostic gratuit de 15 minutes pour analyser vos cheveux et définir le résultat.",
    )
    add(
        "diagnostic-photos",
        "Préparer son diagnostic",
        "prestations",
        "Le diagnostic se fait sur rendez-vous ou juste avant la prestation. Apportez si "
        "possible des photos de la coupe ou de la couleur qui vous plaît.",
    )
    add(
        "test-tolerance",
        "Test de tolérance",
        "prestations",
        "Pour une première coloration au salon, un test de tolérance est fait derrière "
        "l'oreille 48 heures avant. Il est gratuit et ne prend que quelques minutes.",
    )
    add(
        "allergies",
        "Allergies et cuir chevelu sensible",
        "prestations",
        "Signalez-nous toute allergie (PPD, parfum, latex) ou un cuir chevelu sensible : nous "
        "adaptons les produits et pouvons proposer une coloration végétale.",
    )
    add(
        "grossesse",
        "Couleur pendant la grossesse",
        "prestations",
        "Pendant la grossesse, nous évitons les colorations d'oxydation au premier trimestre "
        "et proposons la coloration végétale ou un balayage sans contact avec le cuir chevelu.",
    )
    add(
        "coloration-vegetale",
        "Coloration végétale",
        "prestations",
        "Notre coloration végétale (henné et plantes) est sans ammoniaque ni oxydant. Même "
        "tarif que la coloration classique, avec environ 30 minutes de pose en plus.",
    )
    add(
        "sans-ammoniaque",
        "Coloration sans ammoniaque",
        "prestations",
        "Nos colorations classiques existent en version sans ammoniaque, plus douces pour le "
        "cuir chevelu, sans supplément.",
    )
    add(
        "cheveux-blancs",
        "Cheveux blancs",
        "prestations",
        "La coloration couvre jusqu'à 100 % des cheveux blancs. Pour un rendu plus naturel, "
        "le balayage permet aussi de les fondre dans la masse.",
    )
    add(
        "decoloration",
        "Décoloration et blond platine",
        "prestations",
        "Les décolorations complètes (blond polaire, platine) se font uniquement après "
        "diagnostic, en une ou plusieurs séances. Le tarif est établi sur devis.",
    )
    add(
        "entretien-couleur",
        "Entretenir sa couleur",
        "conseils",
        "Pour garder une couleur éclatante, utilisez un shampoing pour cheveux colorés et "
        "espacez les lavages. Une retouche des racines est conseillée toutes les 5 à 6 semaines.",
    )
    add(
        "frequence-coupe",
        "Fréquence des coupes",
        "conseils",
        "Nous conseillons une coupe toutes les 6 à 8 semaines pour les cheveux courts, et tous "
        "les 2 à 3 mois pour les cheveux longs, afin d'éliminer les pointes abîmées.",
    )
    add(
        "cheveux-boucles",
        "Cheveux bouclés, frisés et crépus",
        "prestations",
        "Nos coiffeurs sont formés à la coupe des cheveux bouclés, frisés et crépus, avec une "
        "technique adaptée à la texture et des soins hydratants spécifiques.",
    )

    # ── produits ──
    add(
        "produits-marques",
        "Marques utilisées",
        "produits",
        "Nous travaillons avec des marques professionnelles : L'Oréal Professionnel, "
        "Kérastase, et Olaplex pour les soins réparateurs.",
    )
    add(
        "produits-vente",
        "Acheter des produits",
        "produits",
        "Les shampoings, masques et produits coiffants utilisés au salon sont en vente à "
        "l'accueil. Nos coiffeurs vous conseillent ceux adaptés à vos cheveux.",
    )
    add(
        "produits-naturels",
        "Produits naturels et vegan",
        "produits",
        "Nous proposons une gamme de soins vegan d'origine naturelle, sans silicone ni "
        "sulfate, pour les clients qui le souhaitent.",
    )

    # ── enfants ──
    add(
        "enfants-age",
        "Les enfants au salon",
        "enfants",
        "Les enfants sont les bienvenus dès 3 ans. Un rehausseur est prévu pour les plus "
        "petits, et un parent doit rester présent pour les moins de 12 ans.",
    )
    add(
        "enfants-couleur",
        "Couleur pour les enfants",
        "enfants",
        "Nous ne faisons ni coloration ni décoloration avant 16 ans, sauf craies et sprays "
        "temporaires qui partent au shampoing.",
    )
    add(
        "poussette",
        "Poussettes",
        "acces",
        "Les poussettes peuvent entrer dans le salon ; un espace est prévu près de l'accueil.",
    )

    # ── mariage et événements ──
    add(
        "mariage-coiffure",
        "Coiffure de mariée",
        "mariage",
        "Nous réalisons des coiffures de mariée : chignons, attaches, ondulations et pose "
        "d'accessoires (fleurs, voile, peigne).",
    )
    add(
        "mariage-essai",
        "Essai coiffure mariage",
        "mariage",
        "Un essai est fortement conseillé 1 à 2 mois avant le mariage. Il dure environ 1h30 "
        "et coûte 60 €, déduits du forfait si vous réservez le jour J.",
    )
    add(
        "mariage-forfait",
        "Forfait mariée",
        "mariage",
        "Le forfait mariée comprend l'essai, la coiffure du jour J et la pose des accessoires "
        "pour 220 €. Les invitées et demoiselles d'honneur sont coiffées à 45 € par personne.",
    )
    add(
        "mariage-deplacement",
        "Coiffure sur le lieu du mariage",
        "mariage",
        "Le jour du mariage, une coiffeuse peut venir sur le lieu de préparation en "
        "Île-de-France, avec 50 € de frais de déplacement.",
    )
    add(
        "mariage-reserver",
        "Réserver pour un mariage",
        "mariage",
        "Pour un mariage, réservez de préférence 3 à 6 mois avant, surtout de mai à "
        "septembre. L'acompte confirme la date.",
    )
    add(
        "domicile",
        "Coiffure à domicile",
        "prestations",
        "Nous ne nous déplaçons pas à domicile pour les prestations courantes : seules les "
        "coiffures de mariage peuvent se faire sur place.",
    )
    add(
        "soiree",
        "Coiffure de soirée",
        "prestations",
        "Pour une soirée, un gala ou une remise de diplôme, nous proposons des chignons et "
        "coiffages de soirée à partir de 45 €, sur rendez-vous.",
    )

    # ── accessibilité ──
    add(
        "accessibilite",
        "Accessibilité PMR",
        "acces",
        "Le salon est de plain-pied et accessible aux personnes à mobilité réduite : pas de "
        "marche, un fauteuil de coiffage adapté et un bac de lavage réglable.",
    )
    add(
        "malentendants",
        "Clients sourds ou malentendants",
        "acces",
        "Tout peut se faire par écrit avec Jenny, et l'équipe a l'habitude d'échanger par "
        "écrit ou sur tablette pendant la prestation.",
    )
    add(
        "animaux",
        "Animaux",
        "acces",
        "Les animaux ne sont pas admis dans le salon, sauf les chiens guides et d'assistance.",
    )
    add(
        "toilettes",
        "Toilettes",
        "acces",
        "Des toilettes sont à la disposition des clients, accessibles aux personnes à "
        "mobilité réduite.",
    )

    # ── accès ──
    add(
        "adresse",
        "Adresse du salon",
        "acces",
        "Le salon se trouve au 14 rue des Tanneurs, 75011 Paris, au rez-de-chaussée, entre "
        "la boulangerie et la pharmacie.",
    )
    add(
        "transports",
        "Venir en transports en commun",
        "acces",
        "Métro Voltaire (ligne 9) à 3 minutes à pied ; bus 46 et 56, arrêt Voltaire.",
    )
    add(
        "parking",
        "Se garer",
        "acces",
        "Un parking public se trouve à 200 m, boulevard Voltaire (environ 3 € de l'heure). "
        "Le stationnement dans la rue est payant.",
    )
    add(
        "velo",
        "Vélos et trottinettes",
        "acces",
        "Un arceau à vélos est installé devant le salon ; les trottinettes pliables peuvent "
        "rester à l'accueil.",
    )
    email = (business.get("email") or "").strip()
    contact = "Le plus simple est d'écrire ici à Jenny, l'assistante virtuelle du salon, 24h/24."
    if email:
        contact += f" Vous pouvez aussi écrire à {email} ; l'équipe répond aux heures d'ouverture."
    add("contact", "Nous contacter", "acces", contact)

    # ── confort ──
    add(
        "wifi",
        "Wi-Fi",
        "confort",
        "Un Wi-Fi gratuit est disponible pendant la prestation ; demandez le code à l'accueil.",
    )
    add(
        "boissons",
        "Boissons offertes",
        "confort",
        "Café, thé ou eau vous sont offerts pendant votre prestation.",
    )

    # ── équipe ──
    add(
        "equipe",
        "L'équipe",
        "equipe",
        "L'équipe compte quatre coiffeurs : Léa (gérante, coloriste), Sophie (chignons et "
        "mariage), Karim (coupes homme et barbe) et Inès (cheveux bouclés et soins).",
    )
    add(
        "choisir-coiffeur",
        "Choisir son coiffeur",
        "equipe",
        "Vous pouvez demander un coiffeur précis à la réservation : Jenny vérifie ses "
        "disponibilités. Sans préférence, le premier coiffeur libre vous est proposé.",
    )
    add(
        "langues",
        "Langues parlées",
        "equipe",
        "L'équipe parle français et anglais ; Karim parle aussi arabe et Inès espagnol. "
        "Jenny peut vous répondre dans votre langue.",
    )

    # ── hygiène et suivi ──
    add(
        "hygiene",
        "Hygiène",
        "politique",
        "Les outils sont désinfectés après chaque client, les serviettes et peignoirs lavés "
        "à 60 °C, et les capes changées à chaque passage.",
    )
    add(
        "insatisfait",
        "Résultat qui ne plaît pas",
        "politique",
        "Si le résultat ne vous convient pas, prévenez-nous dans les 7 jours : nous proposons "
        "une retouche gratuite de la coupe ou de la couleur.",
    )
    add(
        "avis",
        "Laisser un avis",
        "politique",
        "Après votre rendez-vous, vous recevez un lien pour noter votre visite. Vos avis nous "
        "aident beaucoup.",
    )
    add(
        "donnees",
        "Données personnelles",
        "politique",
        "Vos coordonnées servent uniquement à gérer vos rendez-vous et ne sont jamais "
        "revendues. Vous pouvez demander leur suppression à tout moment par e-mail.",
    )
    add(
        "assistante",
        "Qui répond dans ce chat",
        "politique",
        "Ce chat est tenu par Jenny, l'assistante virtuelle du salon. Elle répond 24h/24 et "
        "transmet à l'équipe les demandes particulières.",
    )
    return entries


# ── jeu réel : rien d'inventé ──

# fiches réelles, rafraîchissables
REAL_TAG = "kb_coiffeur_reel"

# familles de clés du jeu réel
_REAL_FAMILIES = (
    "horaires-",
    "acompte-",
    "no-show",
    "rappels",
    "fidelite",
    "reserver",
    "gerer-rdv",
    "liste-attente",
    "assistante",
    "contact",
    "equipe",
    "choisir-coiffeur",
    "presentation",
)
_PRICE_FAMILIES = ("tarifs-grille", "presta-")

# vieux texte de la route seed
LEGACY_HOURS_TEXT = (
    "Le salon est ouvert du mardi au samedi, de 9h à 19h. Fermé le dimanche et le lundi."
)

# catalogue type d'un salon
DEFAULT_COIFFEUR: list[tuple[str, str, int, int]] = [
    ("Coupe femme", "coupe", 45, 3900),
    ("Coupe homme", "coupe", 30, 2500),
    ("Brushing", "coiffage", 30, 2500),
    ("Coloration", "couleur", 90, 5500),
    ("Balayage", "couleur", 120, 8000),
    ("Soin profond", "soin", 30, 2000),
    ("Barbe", "barbe", 20, 1500),
]

_RESERVER = (
    "Vous pouvez réserver directement dans ce chat, 7j/7 et 24h/24 : indiquez la "
    "prestation et le jour souhaité, Jenny vérifie l'agenda et propose les créneaux libres."
)
_LISTE_ATTENTE = (
    "Si le créneau souhaité est complet, Jenny peut vous inscrire sur la liste d'attente : "
    "vous êtes prévenu dès qu'une place se libère."
)
_ASSISTANTE = (
    "Ce chat est tenu par Jenny, l'assistante virtuelle du salon. Elle répond 24h/24 et "
    "transmet à l'équipe les demandes particulières."
)


def hours_entries(business_hours: dict | None) -> list[dict]:
    """Fiches horaires, depuis business_hours."""
    if not has_hours(business_hours):
        # pas d'horaires : on n'invente pas
        return []
    sentence, closed, open_days = describe_hours(business_hours)
    out = [_entry("horaires-semaine", "Horaires d'ouverture", "horaires", sentence)]
    if closed:
        days = _join_fr([f"le {d}" for d in closed])
        out.append(
            _entry(
                "horaires-fermeture",
                "Jours de fermeture",
                "horaires",
                f"Le salon est fermé {days}.",
            )
        )
    for day, (_a, b) in open_days.items():
        if int(b.split(":")[0]) >= 20:
            out.append(
                _entry(
                    "horaires-nocturne",
                    f"Nocturne du {day}",
                    "horaires",
                    f"Le {day}, le salon reste ouvert jusqu'à {fmt_hour(b)}.",
                )
            )
            break
    if "samedi" in open_days:
        a, b = open_days["samedi"]
        out.append(
            _entry(
                "horaires-samedi",
                "Ouverture le samedi",
                "horaires",
                f"Le samedi, le salon est ouvert de {fmt_hour(a)} à {fmt_hour(b)}.",
            )
        )
    return out


def _entry(key: str, title: str, category: str, content: str) -> dict:
    return {"key": key, "title": title, "category": category, "content": content}


def _deposit_text(business: dict) -> str:
    if business.get("deposit_enabled"):
        pct = int(business.get("deposit_percent") or 0)
        mini = fmt_price(int(business.get("deposit_min_cents") or 0))
        return (
            f"Un acompte de {pct} % du prix de la prestation (minimum {mini}) est demandé pour "
            "confirmer la réservation. Il est déduit du montant à régler le jour du rendez-vous."
        )
    return "Aucun acompte n'est demandé à la réservation : vous réglez tout au salon."


def _reminder_text(business: dict) -> str | None:
    day_h = int(business.get("day_reminder_lead_hours") or 0)
    short_m = int(business.get("reminder_lead_minutes") or 0)
    rappels = []
    if day_h:
        rappels.append("la veille (24 h avant)" if day_h == 24 else f"{day_h} h avant")
    if short_m:
        rappels.append("1 heure avant" if short_m == 60 else f"{short_m} minutes avant")
    if not rappels:
        return None
    return f"Vous recevez un rappel {_join_fr(rappels)} votre rendez-vous, par message."


def _real_entries(
    business: dict,
    prestations: list[dict],
    *,
    include_prices: bool,
    staff: list[str],
) -> list[dict]:
    """Fiches tirées de la base seule."""
    out = hours_entries(business.get("business_hours"))
    prestas = [p for p in prestations if p.get("is_active", True)]
    if include_prices and prestas:
        grid = [
            f"- {p['name']} : {fmt_price(p['price_cents'])} ({fmt_duration(p['duration_minutes'])})"
            for p in prestas
        ]
        out.append(
            _entry(
                "tarifs-grille", "Grille des tarifs", "tarifs", "Nos tarifs :\n" + "\n".join(grid)
            )
        )
        for p in prestas:
            desc = (p.get("description") or "").strip()
            content = (
                f"{p['name']} : {fmt_price(p['price_cents'])}, environ "
                f"{fmt_duration(p['duration_minutes'])}. {desc}"
            ).strip()
            out.append(_entry(f"presta-{slugify(p['name'])}", p["name"], "prestations", content))

    out.append(
        _entry("acompte-montant", "Acompte à la réservation", "politique", _deposit_text(business))
    )
    # règle du moteur (2 lapins)
    out.append(
        _entry(
            "no-show",
            "Rendez-vous non honoré",
            "politique",
            "Après deux rendez-vous non honorés sans prévenir, un acompte est demandé pour "
            "toute nouvelle réservation.",
        )
    )
    rappel = _reminder_text(business)
    if rappel:
        out.append(_entry("rappels", "Rappels de rendez-vous", "rendez-vous", rappel))
    threshold = int(business.get("loyalty_threshold") or 0)
    if threshold:
        out.append(
            _entry(
                "fidelite",
                "Programme fidélité",
                "fidelite",
                f"Chaque rendez-vous honoré compte pour la fidélité : au bout de {threshold} "
                "rendez-vous, une récompense est débloquée. Le détail est donné au salon.",
            )
        )
    out.append(_entry("reserver", "Prendre rendez-vous", "rendez-vous", _RESERVER))
    out.append(
        _entry(
            "gerer-rdv",
            "Annuler ou déplacer un rendez-vous",
            "rendez-vous",
            "Pour annuler ou déplacer votre rendez-vous, écrivez-le simplement ici : Jenny "
            "retrouve votre réservation et vous propose d'autres créneaux.",
        )
    )
    out.append(_entry("liste-attente", "Liste d'attente", "rendez-vous", _LISTE_ATTENTE))
    out.append(_entry("assistante", "Qui répond dans ce chat", "politique", _ASSISTANTE))

    contact = "Le plus simple est d'écrire ici à Jenny, l'assistante virtuelle du salon, 24h/24."
    email = (business.get("email") or "").strip()
    phone = (business.get("phone") or "").strip()
    if email:
        contact += f" Vous pouvez aussi écrire à {email}."
    if phone:
        contact += f" Téléphone du salon : {phone}."
    out.append(_entry("contact", "Nous contacter", "acces", contact))

    names = [n.strip() for n in staff if n and n.strip()]
    if names:
        out.append(
            _entry("equipe", "L'équipe", "equipe", f"L'équipe du salon : {_join_fr(names)}.")
        )
        out.append(
            _entry(
                "choisir-coiffeur",
                "Choisir son coiffeur",
                "equipe",
                "Vous pouvez demander un coiffeur précis en réservant : Jenny vérifie ses "
                "disponibilités.",
            )
        )
    desc = (business.get("description") or "").strip()
    if desc:
        # texte du gérant
        out.append(_entry("presentation", "Présentation du salon", "general", desc))
    return out


def build_entries(
    business: dict,
    prestations: list[dict],
    *,
    demo: bool,
    include_prices: bool = True,
    staff: list[str] | None = None,
) -> list[dict]:
    """Fiches KB {key, title, category, content}."""
    if demo:
        return _demo_entries(business, prestations)
    return _real_entries(business, prestations, include_prices=include_prices, staff=staff or [])


def real_families(include_prices: bool = True) -> tuple[str, ...]:
    """Clés gérées par le jeu réel."""
    return _REAL_FAMILIES + (_PRICE_FAMILIES if include_prices else ())


def _managed(key: str, families: tuple[str, ...]) -> bool:
    return any(key.startswith(f) for f in families)


def _norm_title(title: str) -> str:
    return slugify(title or "")


async def sync_real_entries(kb, entries: list[dict], *, families: tuple[str, ...]) -> dict:
    """Ajoute, met à jour ou retire nos fiches."""
    stats = {"added": 0, "updated": 0, "removed": 0, "kept_owner": 0}
    ours: dict[str, object] = {}
    legacy: list = []
    owner_titles: set[str] = set()
    for e in await kb.list_entries():
        meta = getattr(e, "metadata", None) or {}
        key = meta.get("kb_key")
        if meta.get("seed") == REAL_TAG and key:
            ours[key] = e
        elif (e.content or "").strip() == LEGACY_HOURS_TEXT:
            # ancienne fiche codée en dur
            legacy.append(e)
        else:
            owner_titles.add(_norm_title(e.title))
    if legacy and "horaires-semaine" not in ours:
        ours["horaires-semaine"] = legacy.pop(0)
    for old in legacy:
        # horaires inventés en trop
        await kb.delete_entry(old.id)
        stats["removed"] += 1
    wanted = {e["key"] for e in entries}
    for e in entries:
        meta = {"kb_key": e["key"], "seed": REAL_TAG}
        old = ours.get(e["key"])
        if old is not None:
            same = (
                old.content == e["content"]
                and old.title == e["title"]
                and old.category == e["category"]
                and (getattr(old, "metadata", None) or {}).get("seed") == REAL_TAG
            )
            if not same:
                await kb.update_text_entry(
                    old.id, e["content"], title=e["title"], category=e["category"], metadata=meta
                )
                stats["updated"] += 1
            continue
        if _norm_title(e["title"]) in owner_titles:
            # fiche du gérant : on garde
            stats["kept_owner"] += 1
            continue
        await kb.add_text(
            content=e["content"], title=e["title"], category=e["category"], metadata=meta
        )
        stats["added"] += 1
    for key, old in ours.items():
        if key not in wanted and _managed(key, families):
            # fait qui n'existe plus
            await kb.delete_entry(old.id)
            stats["removed"] += 1
    return stats


async def refresh_hours(session, business_id, kb=None) -> dict | None:
    """Fiches horaires après un changement."""
    if session.get_bind().dialect.name != "postgresql":
        return None
    if kb is None:
        from jenny.rag.knowledge_base import KnowledgeBase

        kb = KnowledgeBase(business_id=business_id, session=session)
    business, _prestas, _staff = await load_salon(session, business_id)
    existing = await kb.list_entries()
    # salon jamais seedé : rien
    seeded = any(
        (getattr(e, "metadata", None) or {}).get("seed") == REAL_TAG
        or (e.content or "").strip() == LEGACY_HOURS_TEXT
        for e in existing
    )
    if not seeded:
        return None
    entries = hours_entries(business.get("business_hours"))
    return await sync_real_entries(kb, entries, families=("horaires-",))


async def load_salon(session, business_id) -> tuple[dict, list[dict], list[str]]:
    """Salon, prestations et équipe en base."""
    from sqlalchemy import select

    from jenny.domain.models.business import Business
    from jenny.domain.models.prestation import Prestation
    from jenny.domain.models.staff import Staff

    if not isinstance(business_id, UUID):
        business_id = UUID(str(business_id))
    biz = await session.get(Business, business_id)
    if biz is None:
        raise LookupError(f"business introuvable : {business_id}")
    business = {
        k: getattr(biz, k, None)
        for k in (
            "id",
            "name",
            "slug",
            "email",
            "phone",
            "description",
            "business_hours",
            "deposit_enabled",
            "deposit_percent",
            "deposit_min_cents",
            "reminder_lead_minutes",
            "day_reminder_lead_hours",
            "loyalty_threshold",
        )
    }
    rows = (
        (
            await session.execute(
                select(Prestation)
                .where(Prestation.business_id == biz.id)
                .order_by(Prestation.sort_order.asc(), Prestation.name.asc())
            )
        )
        .scalars()
        .all()
    )
    prestas = [
        {
            "name": p.name,
            "category": p.category,
            "duration_minutes": p.duration_minutes,
            "price_cents": p.price_cents,
            "description": p.description,
            "is_active": p.is_active,
        }
        for p in rows
    ]
    staff = (
        (
            await session.execute(
                select(Staff.display_name)
                .where(Staff.business_id == biz.id, Staff.is_active.is_(True))
                .order_by(Staff.display_name.asc())
            )
        )
        .scalars()
        .all()
    )
    return business, prestas, list(staff)
