"""Configuration des hyperparamètres NanoGPT.

Paramètres du modèle, de l'entraînement et de la génération,
centralisés et typés.
"""

from dataclasses import dataclass

import torch


@dataclass
class NanoGPTConfig:
    """Hyperparamètres du modèle NanoGPT."""

    # ── Architecture ──
    vocab_size: int = 50257  # GPT-2 tokenizer par défaut
    block_size: int = 256  # Longueur de contexte max
    n_layer: int = 6  # Nombre de couches Transformer
    n_head: int = 6  # Nombre de têtes d'attention
    n_embd: int = 384  # Dimension des embeddings
    dropout: float = 0.1

    # ── Entraînement ──
    batch_size: int = 32
    learning_rate: float = 3e-4
    max_epochs: int = 50
    weight_decay: float = 0.01
    warmup_steps: int = 100

    # ── Génération ──
    max_new_tokens: int = 200
    temperature: float = 0.8
    top_k: int = 40

    # ── Système ──
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    seed: int = 42
    compile_model: bool = False  # torch.compile (PyTorch 2.x)

    @property
    def head_size(self) -> int:
        """Dimension par tête d'attention."""
        return self.n_embd // self.n_head
