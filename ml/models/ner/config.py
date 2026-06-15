"""Configuration du modèle NER (Named Entity Recognition).

Hyperparamètres pour le BiGRU qui étiquette chaque mot
avec un tag BIO pour extraire les entités clés.

Entités ajoutées pour le contexte coiffeur :
- TIME : heure (14h, 10h30, vers midi)
- SERVICE : prestation (coupe homme, coloration, lissage)
- DURATION : durée (30 min, 1h30)
"""

from dataclasses import dataclass, field

import torch


def _get_device() -> str:
    """Détecte le meilleur device disponible (CUDA > MPS > CPU)."""
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# Types d'entités reconnus par Jenny
ENTITY_TYPES: list[str] = [
    "ORDER_NUMBER",  # Numéro de commande
    "DATE",  # Date
    "TIME",  # Heure (ajouté)
    "PHONE",  # Numéro de téléphone
    "EMAIL",  # Adresse email
    "PRODUCT",  # Nom de produit
    "AMOUNT",  # Montant / prix
    "NAME",  # Nom de personne
    "LOCATION",  # Lieu / adresse
    "SERVICE",  # Type de prestation (ajouté — coiffure, etc.)
    "DURATION",  # Durée (ajouté — 30 min, 1h)
]

# Tags BIO : O + B-TYPE + I-TYPE pour chaque type d'entité
BIO_TAGS: list[str] = ["O"]  # Outside
for entity_type in ENTITY_TYPES:
    BIO_TAGS.append(f"B-{entity_type}")  # Begin
    BIO_TAGS.append(f"I-{entity_type}")  # Inside

TAG_TO_ID: dict[str, int] = {tag: i for i, tag in enumerate(BIO_TAGS)}
ID_TO_TAG: dict[int, str] = {i: tag for tag, i in TAG_TO_ID.items()}


@dataclass
class NERModelConfig:
    """Hyperparamètres du modèle BiGRU pour le NER."""

    # ── Architecture ──
    vocab_size: int = 30000
    embedding_dim: int = 128
    hidden_dim: int = 256
    num_layers: int = 2
    num_tags: int = len(BIO_TAGS)
    dropout: float = 0.3
    max_seq_length: int = 128

    # ── Entraînement ──
    batch_size: int = 64
    learning_rate: float = 1e-3
    epochs: int = 40
    weight_decay: float = 1e-4

    # ── Système ──
    device: str = field(default_factory=_get_device)
    seed: int = 42

    # ── Tags ──
    tags: list[str] = field(default_factory=lambda: BIO_TAGS.copy())
