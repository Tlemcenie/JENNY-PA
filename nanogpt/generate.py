"""Génération de texte avec NanoGPT.

Fournit des fonctions pour générer du texte
à partir d'un modèle NanoGPT entraîné.
"""

import torch
import torch.nn.functional as nn_functional

from nanogpt.config import NanoGPTConfig
from nanogpt.model import NanoGPT


@torch.no_grad()
def generate(
    model: NanoGPT,
    idx: torch.Tensor,
    max_new_tokens: int = 200,
    temperature: float = 0.8,
    top_k: int | None = 40,
) -> torch.Tensor:
    """Génère des tokens de manière autoregressive.

    Args:
        model: Modèle NanoGPT entraîné.
        idx: Tokens de contexte initial (B, T).
        max_new_tokens: Nombre de tokens à générer.
        temperature: Contrôle la créativité (1.0 = neutre).
        top_k: Limite le sampling aux top_k tokens les plus probables.

    Returns:
        Séquence complète (contexte + tokens générés).
    """
    model.eval()
    block_size = model.config.block_size

    for _ in range(max_new_tokens):
        # Tronquer au block_size si nécessaire
        idx_cond = idx if idx.size(1) <= block_size else idx[:, -block_size:]

        # Forward pass
        logits, _ = model(idx_cond)
        logits = logits[:, -1, :] / temperature

        # Top-k filtering
        if top_k is not None:
            v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
            logits[logits < v[:, [-1]]] = float("-inf")

        # Sampling
        probs = nn_functional.softmax(logits, dim=-1)
        idx_next = torch.multinomial(probs, num_samples=1)
        idx = torch.cat((idx, idx_next), dim=1)

    return idx


def generate_text(
    model: NanoGPT,
    prompt_tokens: list[int],
    config: NanoGPTConfig | None = None,
) -> list[int]:
    """Génère du texte à partir d'un prompt tokenizé.

    Args:
        model: Modèle NanoGPT.
        prompt_tokens: Tokens du prompt.
        config: Configuration (utilise les défauts si None).

    Returns:
        Liste de tokens générés (prompt inclus).
    """
    config = config or model.config
    device = next(model.parameters()).device

    idx = torch.tensor([prompt_tokens], dtype=torch.long, device=device)
    output = generate(
        model,
        idx,
        max_new_tokens=config.max_new_tokens,
        temperature=config.temperature,
        top_k=config.top_k,
    )
    return output[0].tolist()
