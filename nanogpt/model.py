"""Architecture Transformer NanoGPT.

Implémentation minimaliste d'un GPT decoder-only :
- Multi-Head Self-Attention (causale)
- Feed-Forward Network
- Layer Normalization (pre-norm)
- Positional + Token Embeddings

Inspiré de Karpathy's nanoGPT, adapté pour Jenny.
"""

import math

import torch
import torch.nn as nn
import torch.nn.functional as nn_functional

from nanogpt.config import NanoGPTConfig


class CausalSelfAttention(nn.Module):
    """Multi-Head Causal Self-Attention."""

    def __init__(self, config: NanoGPTConfig) -> None:
        super().__init__()
        assert config.n_embd % config.n_head == 0

        # Projections Q, K, V en une seule matrice
        self.c_attn = nn.Linear(config.n_embd, 3 * config.n_embd)
        self.c_proj = nn.Linear(config.n_embd, config.n_embd)
        self.attn_dropout = nn.Dropout(config.dropout)
        self.resid_dropout = nn.Dropout(config.dropout)

        self.n_head = config.n_head
        self.n_embd = config.n_embd

        # Masque causal
        self.register_buffer(
            "bias",
            torch.tril(torch.ones(config.block_size, config.block_size)).view(
                1, 1, config.block_size, config.block_size
            ),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch, seq_len, n_embd = x.size()  # batch, sequence, embedding

        # Calcul Q, K, V
        q, k, v = self.c_attn(x).split(self.n_embd, dim=2)
        head_dim = n_embd // self.n_head
        q = q.view(batch, seq_len, self.n_head, head_dim).transpose(1, 2)
        k = k.view(batch, seq_len, self.n_head, head_dim).transpose(1, 2)
        v = v.view(batch, seq_len, self.n_head, head_dim).transpose(1, 2)

        # Attention causale
        att = (q @ k.transpose(-2, -1)) * (1.0 / math.sqrt(k.size(-1)))
        att = att.masked_fill(self.bias[:, :, :seq_len, :seq_len] == 0, float("-inf"))
        att = nn_functional.softmax(att, dim=-1)
        att = self.attn_dropout(att)

        y = att @ v
        y = y.transpose(1, 2).contiguous().view(batch, seq_len, n_embd)
        y = self.resid_dropout(self.c_proj(y))
        return y


class FeedForward(nn.Module):
    """Feed-Forward Network (MLP) avec GELU."""

    def __init__(self, config: NanoGPTConfig) -> None:
        super().__init__()
        self.c_fc = nn.Linear(config.n_embd, 4 * config.n_embd)
        self.c_proj = nn.Linear(4 * config.n_embd, config.n_embd)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.c_fc(x)
        x = nn_functional.gelu(x)
        x = self.c_proj(x)
        x = self.dropout(x)
        return x


class TransformerBlock(nn.Module):
    """Bloc Transformer (pre-norm) : Attention + FFN."""

    def __init__(self, config: NanoGPTConfig) -> None:
        super().__init__()
        self.ln_1 = nn.LayerNorm(config.n_embd)
        self.attn = CausalSelfAttention(config)
        self.ln_2 = nn.LayerNorm(config.n_embd)
        self.ffn = FeedForward(config)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.ln_1(x))
        x = x + self.ffn(self.ln_2(x))
        return x


class NanoGPT(nn.Module):
    """Modèle NanoGPT complet (decoder-only Transformer).

    Architecture :
    - Token Embedding + Positional Embedding
    - N blocs TransformerBlock (pre-norm)
    - LayerNorm finale
    - Projection vers vocabulaire (weight tying)
    """

    def __init__(self, config: NanoGPTConfig) -> None:
        super().__init__()
        self.config = config

        self.transformer = nn.ModuleDict(
            {
                "wte": nn.Embedding(config.vocab_size, config.n_embd),
                "wpe": nn.Embedding(config.block_size, config.n_embd),
                "drop": nn.Dropout(config.dropout),
                "blocks": nn.ModuleList([TransformerBlock(config) for _ in range(config.n_layer)]),
                "ln_f": nn.LayerNorm(config.n_embd),
            }
        )
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)

        # Weight tying (embeddings ↔ output)
        self.transformer["wte"].weight = self.lm_head.weight

        # Initialisation des poids
        self.apply(self._init_weights)

    def _init_weights(self, module: nn.Module) -> None:
        """Initialisation Xavier/He standard."""
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(
        self, idx: torch.Tensor, targets: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        """Forward pass.

        Args:
            idx: Indices de tokens (B, T).
            targets: Cibles pour le calcul de la loss (B, T) ou None.

        Returns:
            (logits, loss) — loss est None si targets est None.
        """
        _, seq_len = idx.size()
        assert self.config.block_size >= seq_len, (
            f"Séquence trop longue ({seq_len} > {self.config.block_size})"
        )

        pos = torch.arange(0, seq_len, dtype=torch.long, device=idx.device)
        tok_emb = self.transformer["wte"](idx)
        pos_emb = self.transformer["wpe"](pos)
        x = self.transformer["drop"](tok_emb + pos_emb)

        for block in self.transformer["blocks"]:
            x = block(x)

        x = self.transformer["ln_f"](x)
        logits = self.lm_head(x)

        loss = None
        if targets is not None:
            loss = nn_functional.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))

        return logits, loss

    def count_parameters(self) -> int:
        """Retourne le nombre total de paramètres entraînables."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
