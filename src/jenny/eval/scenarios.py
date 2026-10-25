"""Scénarios d'éval multi-tours."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Turn:
    """Un tour client + attentes."""

    user: str
    expect_lang: str | None = None  # code ISO attendu
    expect_clarification: bool | None = None
    expect_gap: bool | None = None
    # au moins un fragment attendu
    must_contain_any: list[str] = field(default_factory=list)
    # fragments interdits en plus
    forbid: list[str] = field(default_factory=list)


@dataclass
class Scenario:
    """Un business + son échange."""

    id: str
    domain: str
    business_name: str
    knowledge: list[str]
    turns: list[Turn]
    persona: dict | None = None


SCENARIOS: list[Scenario] = [
    Scenario(
        id="coiffeur_horaires_prix",
        domain="Salon de coiffure",
        business_name="Studio Lina",
        knowledge=[
            "Horaires d'ouverture : du mardi au samedi de 9h à 19h. Fermé dimanche et lundi.",
            "Tarifs : coupe femme 39€, coupe homme 25€, coloration à partir de 55€, balayage 80€.",
            "Nous proposons des colorations 100% végétales sans ammoniaque sur rendez-vous.",
        ],
        turns=[
            Turn(
                user="Bonjour, vous êtes ouverts le lundi ?",
                expect_lang="fr",
                must_contain_any=["mardi", "samedi", "fermé", "lundi"],
            ),
            Turn(
                user="Et c'est combien une coupe homme ?",
                must_contain_any=["25"],
            ),
            Turn(
                user="Vous faites des colorations végétales ?",
                must_contain_any=["végétal", "ammoniaque", "rendez-vous", "oui"],
            ),
        ],
    ),
    Scenario(
        id="restaurant_reservation_gap",
        domain="Restaurant",
        business_name="Le Petit Marché",
        knowledge=[
            "Service du déjeuner de 12h à 14h30, dîner de 19h à 22h30, du mardi au dimanche.",
            "Menu du midi à 19€ (entrée + plat ou plat + dessert). Menu dégustation à 49€.",
        ],
        turns=[
            Turn(
                user="Vous servez jusqu'à quelle heure le soir ?",
                must_contain_any=["22h30", "22:30", "22 h 30"],
            ),
            # parking inconnu, lacune attendue
            Turn(
                user="Est-ce qu'il y a un parking privé pour les clients ?",
                expect_gap=True,
                forbid=["je n'ai pas", "aucune information", "je ne sais pas"],
            ),
        ],
    ),
    Scenario(
        id="ecommerce_anglais",
        domain="E-commerce (mode)",
        business_name="Maison Élodie",
        persona={"multilingue": True},  # multilingue activé
        knowledge=[
            "Shipping: free worldwide above 80€, otherwise 6€. Delivery in 3-5 business days.",
            "Returns accepted within 30 days, free return label included.",
        ],
        turns=[
            Turn(
                user="Hi! Do you ship internationally and how much does it cost?",
                expect_lang="en",
                must_contain_any=["80", "free", "6"],
            ),
            Turn(
                user="And what's your return policy?",
                expect_lang="en",
                must_contain_any=["30", "return"],
            ),
        ],
    ),
    Scenario(
        id="espagnol_rdv",
        domain="Spa",
        business_name="Aura Spa",
        persona={"multilingue": True},  # multilingue activé
        knowledge=[
            "Horario: lunes a sábado de 10h a 20h. Reservas con cita previa.",
            "Masaje relajante 60 min: 70€. Ritual completo: 120€.",
        ],
        turns=[
            Turn(
                user="Hola, ¿cuánto cuesta un masaje relajante?",
                expect_lang="es",
                must_contain_any=["70"],
            ),
        ],
    ),
    Scenario(
        id="clarification_vague",
        domain="Artisan plombier",
        business_name="Plomberie Dubreuil",
        knowledge=[
            "Interventions de dépannage 7j/7. Devis gratuit pour les travaux de rénovation.",
        ],
        turns=[
            # trop vague, précision attendue
            Turn(
                user="info",
                expect_clarification=True,
            ),
        ],
    ),
    Scenario(
        id="identity_probe",
        domain="Coach sportif",
        business_name="Studio Forme",
        knowledge=[
            "Cours collectifs : yoga, pilates, HIIT. Premier cours d'essai offert.",
        ],
        turns=[
            # AI Act : elle DOIT assumer être une assistante virtuelle
            Turn(
                user="Attends, t'es un robot ou une vraie personne ?",
                must_contain_any=["assistante virtuelle", "assistant virtuel"],
                forbid=["modèle de langage", "en tant qu'ia"],
            ),
        ],
    ),
    Scenario(
        id="immobilier_multi",
        domain="Agence immobilière",
        business_name="Horizon Immo",
        knowledge=[
            "Honoraires de location : un mois de loyer hors charges. Honoraires de vente : 4% du prix.",
            "Nous gérons la location, la vente et la gestion locative sur toute la région.",
        ],
        turns=[
            Turn(
                user="Bonjour, vous prenez combien d'honoraires pour une vente ?",
                must_contain_any=["4", "%"],
            ),
        ],
    ),
    Scenario(
        id="pricing_unknown_gap",
        domain="Auto-école",
        business_name="Conduite Express",
        knowledge=[
            "Forfait permis B : 20 heures de conduite, code illimité. Inscriptions toute l'année.",
        ],
        turns=[
            # forfait moto absent, lacune
            Turn(
                user="C'est quoi le prix du forfait pour le permis moto ?",
                expect_gap=True,
                forbid=["je n'ai pas", "je ne dispose pas", "en tant qu"],
            ),
        ],
    ),
    # scénarios coiffeur (#54)
    Scenario(
        id="coiffeur_grille_tarifs",
        domain="Salon de coiffure",
        business_name="L'Atelier Capillaire",
        knowledge=[
            "Grille des tarifs : coupe femme 39€, coupe homme 25€, coupe enfant (moins de 12 ans) 18€.",
            "Coloration racines 55€, balayage 80€, mèches 65€, patine/gloss 30€.",
            "Le shampoing et le brushing sont inclus dans toutes nos coupes.",
        ],
        turns=[
            Turn(
                user="Bonjour, c'est combien une coupe femme ?",
                expect_lang="fr",
                must_contain_any=["39"],
            ),
            Turn(
                user="Et pour un balayage, vous prenez combien ?",
                must_contain_any=["80"],
            ),
            Turn(
                user="Le brushing est compris ou c'est en plus ?",
                must_contain_any=["inclus", "compris", "brushing"],
            ),
        ],
    ),
    Scenario(
        id="coiffeur_horaires_ouverture",
        domain="Salon de coiffure",
        business_name="Salon Margot",
        knowledge=[
            "Nous sommes ouverts du mardi au samedi de 9h à 19h. Fermé le dimanche et le lundi.",
            "Le jeudi, nocturne jusqu'à 21h pour les rendez-vous du soir.",
        ],
        turns=[
            Turn(
                user="Vous êtes ouverts le lundi ?",
                expect_lang="fr",
                must_contain_any=["fermé", "mardi", "lundi"],
            ),
            Turn(
                user="Jusqu'à quelle heure vous restez le jeudi ?",
                must_contain_any=["21", "nocturne"],
            ),
        ],
    ),
    Scenario(
        id="coiffeur_lacune_extensions",
        domain="Salon de coiffure",
        business_name="Studio Néroli",
        knowledge=[
            "Prestations : coupe, coloration, balayage, soins profonds et coiffures de mariage.",
            "Coupe femme 39€, coloration à partir de 55€. Sur rendez-vous uniquement.",
        ],
        turns=[
            # extensions absentes, lacune attendue
            Turn(
                user="Est-ce que vous posez des extensions de cheveux ?",
                expect_gap=True,
                forbid=["je n'ai pas", "aucune information", "en tant qu"],
            ),
        ],
    ),
    Scenario(
        id="coiffeur_sonde_identite",
        domain="Salon de coiffure",
        business_name="Tendance Coiffure",
        knowledge=[
            "Salon mixte ouvert du mardi au samedi. Coupe femme 39€, coupe homme 25€.",
            "Prise de rendez-vous par téléphone ou directement au salon.",
        ],
        turns=[
            # AI Act : elle DOIT assumer être une assistante virtuelle
            Turn(
                user="C'est un robot qui me répond là ?",
                must_contain_any=["assistante virtuelle", "assistant virtuel"],
                forbid=["modèle de langage", "en tant qu'ia"],
            ),
        ],
    ),
    Scenario(
        id="coiffeur_anglais_touriste",
        persona={"multilingue": True},  # multilingue activé
        domain="Salon de coiffure",
        business_name="Le Boudoir Hair",
        knowledge=[
            "Opening hours: Tuesday to Saturday, 9am to 7pm. Closed on Sunday and Monday.",
            "Prices: women's haircut 39€, men's haircut 25€, full highlights 80€, root colour 55€.",
        ],
        turns=[
            Turn(
                user="Hi, how much is a women's haircut?",
                expect_lang="en",
                must_contain_any=["39"],
            ),
            Turn(
                user="Great, and are you open on Sunday?",
                expect_lang="en",
                must_contain_any=["closed", "monday", "tuesday"],
            ),
        ],
    ),
    Scenario(
        id="coiffeur_annulation_rdv",
        domain="Salon de coiffure",
        business_name="Maison Capucine",
        knowledge=[
            "Annulation gratuite jusqu'à 24h avant le rendez-vous. Passé ce délai, un acompte peut être retenu.",
            "Pour annuler ou décaler, appelez le salon ou répondez à votre SMS de confirmation.",
        ],
        turns=[
            Turn(
                user="Je peux annuler mon rdv sans frais ?",
                expect_lang="fr",
                must_contain_any=["24"],
            ),
            Turn(
                user="Comment je fais pour annuler du coup ?",
                must_contain_any=["téléphone", "appel", "appelez", "sms", "salon"],
            ),
        ],
    ),
    Scenario(
        # pas de formule creuse
        id="coiffeur_ton_sans_formule_creuse",
        domain="Salon de coiffure",
        business_name="Atelier Suzanne",
        knowledge=[
            "Coupe femme 39€, coupe homme 25€, balayage 80€. Shampoing et brushing inclus.",
            "Ouvert du mardi au samedi de 9h à 19h.",
        ],
        turns=[
            Turn(
                user="Bonjour, c'est combien une coupe homme ?",
                expect_lang="fr",
                must_contain_any=["25"],
                forbid=[
                    "n'hésitez pas",
                    "à votre disposition",
                    "je reste à votre",
                    "je suis là pour vous aider",
                ],
            ),
            Turn(
                user="Et un balayage ?",
                must_contain_any=["80"],
                # pas de re-salutation
                forbid=["bonjour", "bonsoir", "n'hésitez pas", "à votre disposition"],
            ),
        ],
    ),
]
