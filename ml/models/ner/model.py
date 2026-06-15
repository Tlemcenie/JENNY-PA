"""Modèle BiGRU pour l'extraction d'entités (NER).

Architecture :
- Embedding → BiGRU → FC → tags BIO

Le BiGRU bidirectionnel capture le contexte dans les deux sens.
La couche FC produit un tag BIO pour chaque token.

Schéma BIO :
- B-ORDER_NUMBER : début d'un numéro de commande
- I-ORDER_NUMBER : suite d'un numéro de commande
- O : token hors entité
"""

import torch
import torch.nn as nn

from ml.models.ner.config import NERModelConfig


class BiGRUNER(nn.Module):
    """Modèle BiGRU pour le Named Entity Recognition.

    Pipeline :
    1. Embedding des tokens
    2. BiGRU bidirectionnel (contexte gauche + droit)
    3. FC par token → tag BIO
    """

    def __init__(self, config: NERModelConfig) -> None:
        super().__init__()
        self.config = config

        self.embedding = nn.Embedding(
            config.vocab_size,
            config.embedding_dim,
            padding_idx=0,
        )

        self.gru = nn.GRU(
            input_size=config.embedding_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
        )

        self.dropout = nn.Dropout(config.dropout)

        # BiGRU → hidden_dim * 2 (bidirectionnel)
        self.fc = nn.Linear(config.hidden_dim * 2, config.num_tags)

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Forward pass.

        Args:
            input_ids: (batch, seq_len) — indices de tokens
            attention_mask: (batch, seq_len) — masque de padding

        Returns:
            logits: (batch, seq_len, num_tags)
        """
        embedded = self.embedding(input_ids)  # (batch, seq, emb_dim)
        embedded = self.dropout(embedded)

        gru_out, _ = self.gru(embedded)  # (batch, seq, hidden*2)
        gru_out = self.dropout(gru_out)

        logits = self.fc(gru_out)  # (batch, seq, num_tags)
        return logits

    def predict_tags(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Prédit les tags pour chaque token.

        Returns:
            predicted_tags: (batch, seq_len)
        """
        logits = self.forward(input_ids, attention_mask)
        return logits.argmax(dim=-1)

    def count_parameters(self) -> int:
        """Nombre de paramètres entraînables."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
