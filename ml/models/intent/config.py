"""Configuration du modèle de détection d'intention (multi-label).

Hyperparamètres pour le classifieur LSTM qui analyse
les messages clients et prédit UNE ou PLUSIEURS intentions.

Inclut :
- small_talk : bavardage informel ("ça va ?", "quoi de neuf ?")
- payment_question : questions sur les moyens de paiement
"""

from dataclasses import dataclass, field

import torch


def _get_device() -> str:
    """Détecte le meilleur device disponible (CUDA > MPS > CPU).

    MPS = Metal Performance Shaders (Apple Silicon M1/M2/M3).
    """
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# Intentions supportées par Jenny
INTENT_LABELS: list[str] = [
    "greeting",  # Salutations
    "order_status",  # Suivi de commande / livraison
    "pricing",  # Question sur les prix / devis
    "appointment",  # Prise de rendez-vous
    "complaint",  # Réclamation / problème
    "faq",  # Question générale
    "closing",  # Fin de conversation
    "escalation",  # Demande de transfert humain
    "payment",  # Paiement / facturation
    "quote",  # Demande de devis
    "planning",  # Consultation planning / disponibilités
    "general",  # Autre / non classifié
    "small_talk",  # Bavardage informel (ça va ?, quoi de neuf)
    "payment_question",  # Question sur les moyens de paiement (carte, CB, espèces)
]

LABEL_TO_ID: dict[str, int] = {label: i for i, label in enumerate(INTENT_LABELS)}
ID_TO_LABEL: dict[int, str] = {i: label for label, i in LABEL_TO_ID.items()}


@dataclass
class IntentModelConfig:
    """Hyperparamètres du modèle LSTM de détection d'intention."""

    # ── Architecture ──
    vocab_size: int = 30000
    embedding_dim: int = 128
    hidden_dim: int = 256
    num_layers: int = 2
    num_classes: int = len(INTENT_LABELS)
    dropout: float = 0.3
    bidirectional: bool = True
    max_seq_length: int = 128

    # ── Multi-label ──
    multi_label: bool = True  # Active le mode multi-label (sigmoid + BCE)
    multi_label_threshold: float = 0.35  # Seuil pour considérer une intention active
    max_intents: int = 3  # Nombre max d'intentions simultanées

    # ── Entraînement ──
    batch_size: int = 64
    learning_rate: float = 1e-3
    epochs: int = 40
    weight_decay: float = 1e-4

    # ── Système ──
    device: str = field(default_factory=_get_device)
    seed: int = 42

    # ── Labels ──
    labels: list[str] = field(default_factory=lambda: INTENT_LABELS.copy())
