#!/usr/bin/env python3
"""Génération massive de données NER via Groq LLM.

Génère 5000+ exemples diversifiés pour l'entraînement
du modèle BiGRU NER (Named Entity Recognition).

Usage :
    PYTHONPATH=src:. python ml/data_generation/generate_ner_data.py
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path

from groq import Groq
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("JENNY_GROQ_API_KEY", "")

# Entités supportées par Jenny NER (aligné avec ml/models/ner/config.py)
ENTITY_TYPES = [
    "NAME",  # Nom de personne
    "DATE",  # Date / jour
    "TIME",  # Heure
    "SERVICE",  # Type de prestation
    "PHONE",  # Numéro de téléphone
    "EMAIL",  # Adresse email
    "LOCATION",  # Lieu / adresse
    "AMOUNT",  # Montant / prix
    "ORDER_NUMBER",  # Numéro de commande
    "PRODUCT",  # Produit
    "DURATION",  # Durée
]

# Templates pour générer des phrases avec entités annotées
# Le format est : "{texte}" avec des marqueurs [ENTITY_TYPE:valeur]
ENTITY_TEMPLATES = {
    "appointment": [
        "Je voudrais un rendez-vous [DATE:{date}] à [TIME:{time}] pour [SERVICE:{service}]",
        "Bonjour, c'est [NAME:{person}], je veux un rdv [DATE:{date}]",
        "RDV [DATE:{date}] [TIME:{time}] svp",
        "[NAME:{person}] réservation [DATE:{date}] à [TIME:{time}] pour [SERVICE:{service}]",
        "Pouvez-vous me prendre [DATE:{date}] pour une [SERVICE:{service}] ?",
        "Je suis dispo [DATE:{date}] vers [TIME:{time}]",
        "Rdv [SERVICE:{service}] pour [NAME:{person}] [DATE:{date}]",
    ],
    "pricing": [
        "Combien coûte [SERVICE:{service}] ?",
        "C'est quoi le tarif pour [SERVICE:{service}] ?",
        "Prix de [SERVICE:{service}] svp",
        "[SERVICE:{service}], combien ça fait ?",
        "Le prix d'une [SERVICE:{service}] c'est combien ?",
    ],
    "order_status": [
        "Où en est ma commande [ORDER_NUMBER:{order_id}] ?",
        "Suivi de la commande numéro [ORDER_NUMBER:{order_id}]",
        "J'ai commandé [PRODUCT:{product}] le [DATE:{date}], toujours rien",
        "Mon colis [ORDER_NUMBER:{order_id}] est où ?",
    ],
    "contact": [
        "Mon numéro c'est [PHONE:{phone}]",
        "Contactez-moi au [PHONE:{phone}]",
        "Mon email : [EMAIL:{email}]",
        "Appelez-moi, [NAME:{person}], au [PHONE:{phone}]",
        "Je suis [NAME:{person}], joignable à [EMAIL:{email}]",
    ],
    "payment": [
        "Je voudrais payer [AMOUNT:{amount}]",
        "Facture de [AMOUNT:{amount}] à régler",
        "Paiement de [AMOUNT:{amount}] pour [SERVICE:{service}]",
    ],
    "location": [
        "Vous êtes à [LOCATION:{location}] ?",
        "C'est au [LOCATION:{location}] votre salon ?",
        "Je viendrai à votre adresse [LOCATION:{location}]",
    ],
}

# Valeurs possibles pour chaque entité
ENTITY_VALUES = {
    "person": [
        "Marie Dupont",
        "Jean-Pierre",
        "Sophie",
        "Mohamed Ali",
        "Lucas",
        "Camille Martin",
        "Pierre",
        "Aminata",
        "Hugo",
        "Léa",
        "Thomas",
        "Emma",
        "Mehdi",
        "Chloé",
        "Antoine",
        "Sarah",
        "Julie",
        "Nicolas",
        "Fatima",
        "Alex",
        "Manon",
        "Karim",
        "Nathalie",
        "Paul",
        "Inès",
        "Romain",
    ],
    "date": [
        "lundi",
        "mardi",
        "mercredi prochain",
        "jeudi 15",
        "vendredi",
        "samedi matin",
        "demain",
        "après-demain",
        "la semaine prochaine",
        "le 20 mars",
        "le 25 janvier",
        "ce weekend",
        "dimanche",
        "lundi prochain",
        "dans 2 jours",
        "le 3 avril",
        "le 10 février",
        "cette semaine",
        "le 15",
        "le 8 mai",
        "début juin",
        "fin de semaine",
    ],
    "time": [
        "9h",
        "10h30",
        "14h",
        "15h",
        "16h30",
        "11h",
        "9h30",
        "midi",
        "13h",
        "17h",
        "8h30",
        "10h",
        "14h30",
        "15h30",
        "11h30",
        "16h",
        "18h",
        "vers 10h",
        "entre 14h et 15h",
        "en fin de matinée",
    ],
    "service": [
        "coupe homme",
        "coupe femme",
        "coupe enfant",
        "coloration",
        "mèches",
        "balayage",
        "lissage brésilien",
        "permanente",
        "brushing",
        "coiffure mariage",
        "coupe + barbe",
        "shampoing + coupe",
        "décoloration",
        "extension",
        "coupe + couleur",
        "soin capillaire",
        "défrisage",
        "tresse",
        "chignon",
        "barbe",
        "coupe dégradé",
        "coupe au carré",
        "ombré hair",
        "traitement kératine",
        "coupe rasé",
    ],
    "phone": [
        "06 12 34 56 78",
        "0612345678",
        "07 98 76 54 32",
        "+33 6 12 34 56 78",
        "06.12.34.56.78",
        "0712345678",
        "06 11 22 33 44",
        "07 55 66 77 88",
    ],
    "email": [
        "marie@gmail.com",
        "jean.dupont@yahoo.fr",
        "sophie@outlook.com",
        "contact@test.fr",
        "lucas.m@live.fr",
        "aminata@hotmail.fr",
    ],
    "location": [
        "Paris 11ème",
        "Lyon 3ème",
        "Marseille",
        "Toulouse centre",
        "Bordeaux",
        "Nice",
        "15 rue de la Paix",
        "Place de la République",
        "Nantes",
        "Strasbourg",
        "52 avenue des Champs-Élysées",
    ],
    "amount": [
        "25€",
        "30 euros",
        "45€",
        "50€",
        "15,90€",
        "35.00€",
        "80 euros",
        "120€",
        "75€",
        "22€",
    ],
    "order_id": [
        "CMD-12345",
        "CMD-67890",
        "#A4521",
        "REF-2024-001",
        "N°56789",
        "CMD12345",
        "REF987",
        "CMD-00123",
    ],
    "product": [
        "shampoing Kérastase",
        "lisseur GHD",
        "brosse ronde",
        "coloration Wella",
        "soin Olaplex",
        "ciseaux pro",
        "gel coiffant",
        "laque fixation forte",
    ],
    "duration": [
        "30 minutes",
        "1 heure",
        "1h30",
        "45 min",
        "2 heures",
        "20 min",
        "1h",
        "2h",
    ],
}


def fill_template(template: str) -> tuple[str, list[dict]]:
    """Remplit un template avec des valeurs aléatoires et extrait les entités BIO."""

    entities_found = []
    filled = template

    # Trouver tous les placeholders [TYPE:valeur]
    pattern = r"\[([A-Z_]+):\{(\w+)\}\]"
    matches = list(re.finditer(pattern, filled))

    # Remplacer en sens inverse pour garder les positions
    for match in reversed(matches):
        entity_type = match.group(1)
        value_key = match.group(2)
        values = ENTITY_VALUES.get(value_key, ["UNKNOWN"])
        value = random.choice(values)
        filled = filled[: match.start()] + value + filled[match.end() :]
        entities_found.insert(
            0,
            {
                "type": entity_type,
                "value": value,
            },
        )

    return filled, entities_found


def text_to_bio(text: str, entities: list[dict]) -> list[tuple[str, str]]:
    """Convertit un texte + entités en format BIO."""

    words = text.split()
    tags = ["O"] * len(words)

    for entity in entities:
        entity_words = entity["value"].split()
        entity_type = entity["type"]

        # Trouver la position de l'entité dans le texte
        for i in range(len(words) - len(entity_words) + 1):
            if words[i : i + len(entity_words)] == entity_words:
                tags[i] = f"B-{entity_type}"
                for j in range(1, len(entity_words)):
                    tags[i + j] = f"I-{entity_type}"
                break

    return list(zip(words, tags, strict=False))


def generate_ner_batch_llm(
    client: Groq,
    entity_focus: str,
    batch_size: int = 40,
) -> list[dict]:
    """Génère des phrases avec entités annotées via LLM."""

    entity_desc = {
        "NAME": "noms de personnes (prénom, nom complet)",
        "DATE": "dates et jours (lundi, demain, le 15 mars, semaine prochaine)",
        "TIME": "heures (9h, 14h30, midi, vers 10h)",
        "SERVICE": "types de prestations de coiffure (coupe, coloration, brushing, lissage)",
        "PHONE": "numéros de téléphone (06, 07, +33)",
        "EMAIL": "adresses email",
        "LOCATION": "lieux et adresses",
        "AMOUNT": "montants et prix (25€, 30 euros)",
        "ORDER_NUMBER": "numéros de commande (CMD-xxxx, REF-xxxx)",
        "PRODUCT": "noms de produits (shampoing, lisseur, gel)",
        "DURATION": "durées (30 min, 1h, 2 heures)",
    }

    prompt = f"""Tu es un générateur de données NER (Named Entity Recognition) pour un chatbot de salon de coiffure.

Génère exactement {batch_size} phrases de clients qui contiennent des entités de type {entity_focus}.

L'entité {entity_focus} correspond à : {entity_desc.get(entity_focus, entity_focus)}

Format STRICT pour chaque ligne :
phrase ||| entité1:valeur1 ; entité2:valeur2

Exemples :
Je voudrais un rdv mardi à 10h pour une coupe homme ||| DATE:mardi ; TIME:10h ; SERVICE:coupe homme
Bonjour, c'est Marie Dupont ||| NAME:Marie Dupont
Mon numéro c'est 06 12 34 56 78 ||| PHONE:06 12 34 56 78

RÈGLES :
1. Chaque phrase doit être naturelle (client de salon de coiffure)
2. Les entités doivent être EXACTEMENT comme dans la phrase (même forme)
3. Varier le style : formel, informel, SMS
4. FRANÇAIS uniquement
5. La valeur de l'entité doit apparaître TEXTUELLEMENT dans la phrase

Génère UNIQUEMENT les lignes au format demandé :"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=4000,
        )
        text = response.choices[0].message.content.strip()
        examples = []

        for line in text.split("\n"):
            line = line.strip()
            if "|||" not in line:
                continue

            parts = line.split("|||")
            if len(parts) != 2:
                continue

            sentence = parts[0].strip()
            entities_str = parts[1].strip()

            # Enlever numérotation
            sentence = re.sub(r"^\d+[\.\)]\s*", "", sentence)

            entities = []
            for ent_str in entities_str.split(";"):
                ent_str = ent_str.strip()
                if ":" in ent_str:
                    ent_type, ent_val = ent_str.split(":", 1)
                    ent_type = ent_type.strip()
                    ent_val = ent_val.strip()
                    if ent_val in sentence:
                        entities.append(
                            {
                                "type": ent_type,
                                "value": ent_val,
                            }
                        )

            if sentence and entities:
                bio_tags = text_to_bio(sentence, entities)
                examples.append(
                    {
                        "text": sentence,
                        "tokens": [w for w, _ in bio_tags],
                        "tags": [t for _, t in bio_tags],
                        "entities": entities,
                    }
                )

        return examples[:batch_size]

    except Exception as e:
        console.print(f"[red]Erreur API NER : {e}[/red]")
        return []


def generate_template_examples(count_per_template: int = 20) -> list[dict]:
    """Génère des exemples à partir des templates."""
    examples = []

    for _category, templates in ENTITY_TEMPLATES.items():
        for template in templates:
            for _ in range(count_per_template):
                text, entities = fill_template(template)
                if entities:
                    bio_tags = text_to_bio(text, entities)
                    examples.append(
                        {
                            "text": text,
                            "tokens": [w for w, _ in bio_tags],
                            "tags": [t for _, t in bio_tags],
                            "entities": entities,
                        }
                    )

    return examples


def generate_no_entity_examples(client: Groq, count: int = 300) -> list[dict]:
    """Génère des phrases SANS entités (label tout 'O')."""

    prompt = f"""Génère {count} phrases de clients d'un salon de coiffure qui NE contiennent PAS d'informations personnelles.

Pas de nom, pas de date, pas d'heure, pas de téléphone, pas de prix.
Juste des questions générales ou du bavardage.

Exemples :
- Bonjour !
- Merci beaucoup
- C'est possible de venir sans rendez-vous ?
- Vous faites des soins ?

Un message par ligne, sans numérotation :"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=3000,
        )
        text = response.choices[0].message.content.strip()
        examples = []
        for line in text.split("\n"):
            line = re.sub(r"^\d+[\.\)]\s*", "", line.strip().lstrip("- "))
            if line and len(line) > 1:
                words = line.split()
                examples.append(
                    {
                        "text": line,
                        "tokens": words,
                        "tags": ["O"] * len(words),
                        "entities": [],
                    }
                )
        return examples[:count]
    except Exception as e:
        console.print(f"[red]Erreur : {e}[/red]")
        return []


def main():
    console.print(
        Panel.fit(
            "[bold blue]🏷️ JENNY — Génération de données NER (5000+)[/bold blue]\n"
            "[dim]Via Groq LLM (llama-3.3-70b-versatile) + Templates[/dim]",
            border_style="blue",
        )
    )

    client = Groq(api_key=GROQ_API_KEY)
    output_path = Path("data/generated/ner.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_examples: list[dict] = []

    # ══════════════════════════════════════════════
    # Phase 1 : Exemples via templates (rapide, fiable)
    # ══════════════════════════════════════════════
    console.print("\n[bold cyan]📊 Phase 1 : Données via templates[/bold cyan]")

    template_examples = generate_template_examples(count_per_template=30)
    all_examples.extend(template_examples)
    console.print(f"  ✅ [green]{len(template_examples)} exemples générés via templates[/green]")

    # ══════════════════════════════════════════════
    # Phase 2 : Exemples via LLM (par type d'entité)
    # ══════════════════════════════════════════════
    console.print("\n[bold cyan]📊 Phase 2 : Données via LLM[/bold cyan]")

    batches_per_entity = 8

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_entities = progress.add_task("[blue]Entités...", total=len(ENTITY_TYPES))

        for entity_type in ENTITY_TYPES:
            entity_count = 0
            task_batch = progress.add_task(f"  [dim]{entity_type}[/dim]", total=batches_per_entity)

            for _ in range(batches_per_entity):
                examples = generate_ner_batch_llm(client, entity_type, batch_size=50)
                all_examples.extend(examples)
                entity_count += len(examples)
                progress.advance(task_batch)
                time.sleep(0.3)

            progress.remove_task(task_batch)
            progress.advance(task_entities)
            console.print(f"  ✅ [green]{entity_type:12s}[/green] → {entity_count:4d} exemples LLM")

    # ══════════════════════════════════════════════
    # Phase 3 : Phrases sans entités (classe O)
    # ══════════════════════════════════════════════
    console.print("\n[bold cyan]📊 Phase 3 : Phrases sans entités[/bold cyan]")

    for _ in range(5):
        no_ent = generate_no_entity_examples(client, count=100)
        all_examples.extend(no_ent)
        time.sleep(0.3)
    console.print("  ✅ [green]~500 exemples sans entités[/green]")

    # ══════════════════════════════════════════════
    # Shuffle et sauvegarde
    # ══════════════════════════════════════════════
    random.shuffle(all_examples)

    with open(output_path, "w", encoding="utf-8") as f:
        for example in all_examples:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")

    console.print(f"\n[bold green]✅ Dataset NER sauvegardé : {output_path}[/bold green]")

    # Stats
    table = Table(title="📊 Statistiques NER")
    table.add_column("Métrique", style="cyan")
    table.add_column("Valeur", style="green", justify="right")
    table.add_row("Total exemples", f"{len(all_examples):,}")

    tag_counts: dict[str, int] = {}
    for ex in all_examples:
        for tag in ex["tags"]:
            if tag != "O":
                base = tag.split("-", 1)[1] if "-" in tag else tag
                tag_counts[base] = tag_counts.get(base, 0) + 1

    for tag in sorted(tag_counts, key=tag_counts.get, reverse=True):
        table.add_row(f"  {tag}", f"{tag_counts[tag]:,}")

    no_ent_count = sum(1 for ex in all_examples if not ex["entities"])
    table.add_row("Sans entités", f"{no_ent_count:,}")

    console.print(table)


if __name__ == "__main__":
    main()
