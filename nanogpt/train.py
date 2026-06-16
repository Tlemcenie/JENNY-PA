"""Entraînement NanoGPT **from scratch** (aucun fine-tune, poids initialisés au hasard).

Boucle complète :
- Données tokenisées (data/processed/{train,val}.bin) via nanogpt.data
- Optimiseur AdamW + LR schedule (warmup linéaire → cosine decay)
- Éval périodique train/val + sauvegarde du meilleur checkpoint
- Journalisation des métriques → var/nanogpt/metrics.jsonl (pour les graphes)
- Reprise possible (--resume) depuis last.pt
- Device auto : CUDA > MPS (Apple Silicon) > CPU

Usage :
    python -m nanogpt.train --max-steps 3000 --batch-size 24 --eval-interval 100
    python -m nanogpt.train --resume            # reprend l'entraînement
"""

from __future__ import annotations

import argparse
import json
import math
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
from torch.optim import AdamW

from nanogpt.config import NanoGPTConfig
from nanogpt.model import NanoGPT

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
CKPT_DIR = ROOT / "checkpoints" / "nanogpt"
RUN_DIR = ROOT / "var" / "nanogpt"
METRICS = RUN_DIR / "metrics.jsonl"
STATUS = RUN_DIR / "status.json"


def _log(msg: str) -> None:
    print(f"[train] {msg}", flush=True)


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def get_lr(step: int, base_lr: float, warmup: int, max_steps: int) -> float:
    """Warmup linéaire puis décroissance cosine (plancher 10%)."""
    if step < warmup:
        return base_lr * (step + 1) / max(warmup, 1)
    ratio = (step - warmup) / max(max_steps - warmup, 1)
    return base_lr * max(0.1, 0.5 * (1.0 + math.cos(math.pi * ratio)))


def get_batch(data: np.ndarray, block_size: int, batch_size: int, device: str) -> tuple[torch.Tensor, torch.Tensor]:
    ix = torch.randint(len(data) - block_size - 1, (batch_size,))
    x = torch.stack([torch.from_numpy(data[i : i + block_size].astype(np.int64)) for i in ix])
    y = torch.stack([torch.from_numpy(data[i + 1 : i + 1 + block_size].astype(np.int64)) for i in ix])
    if device == "cuda":
        return x.pin_memory().to(device, non_blocking=True), y.pin_memory().to(device, non_blocking=True)
    return x.to(device), y.to(device)


@torch.no_grad()
def estimate_loss(model: NanoGPT, splits: dict, block_size: int, batch_size: int, device: str, iters: int) -> dict:
    model.eval()
    out = {}
    for name, data in splits.items():
        losses = torch.zeros(iters)
        for k in range(iters):
            x, y = get_batch(data, block_size, batch_size, device)
            _, loss = model(x, y)
            losses[k] = loss.item()
        out[name] = float(losses.mean())
    model.train()
    return out


def _write_status(**kw) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(kw, indent=2), encoding="utf-8")


def train(args: argparse.Namespace) -> None:
    # ── Données + vocab réel (depuis meta.json) ──
    meta_path = PROC / "meta.json"
    if not meta_path.exists():
        raise SystemExit("data/processed/meta.json introuvable — lance d'abord `python -m nanogpt.data`.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    train_data = np.memmap(PROC / "train.bin", dtype=np.uint16, mode="r")
    val_data = np.memmap(PROC / "val.bin", dtype=np.uint16, mode="r")
    splits = {"train": train_data, "val": val_data}

    device = args.device or pick_device()
    config = NanoGPTConfig(
        vocab_size=int(meta["vocab_size"]),
        block_size=args.block_size,
        n_layer=args.n_layer,
        n_head=args.n_head,
        n_embd=args.n_embd,
        dropout=args.dropout,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        device=device,
    )
    torch.manual_seed(config.seed)

    model = NanoGPT(config).to(device)
    n_params = model.count_parameters()
    optimizer = AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay,
                      betas=(0.9, 0.95))

    # ── Mixed precision (fp16) + accumulation de gradient ──
    # Gros gain vitesse/VRAM sur GPU (idéal Tesla T4). Désactivés hors CUDA
    # (MPS/CPU) : GradScaler en no-op, le code reste strictement identique.
    use_amp = device == "cuda" and args.amp
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    grad_accum = max(1, args.grad_accum)

    def amp_ctx():
        return torch.amp.autocast("cuda", dtype=torch.float16) if use_amp else nullcontext()

    # ── Reprise éventuelle ──
    start_step = 0
    best_val = float("inf")
    last_ckpt = CKPT_DIR / "last.pt"
    if args.resume and last_ckpt.exists():
        ckpt = torch.load(last_ckpt, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"])
        if "optimizer_state_dict" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        start_step = int(ckpt.get("step", 0))
        best_val = float(ckpt.get("best_val_loss", best_val))
        _log(f"reprise depuis step {start_step} (best_val={best_val:.4f})")

    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if start_step == 0:
        METRICS.write_text("", encoding="utf-8")  # repart à zéro la courbe

    _log(f"device={device} | params={n_params:,} | vocab={config.vocab_size} | "
         f"tokens train={meta['train_tokens']:,} | steps={args.max_steps} | "
         f"amp={use_amp} | grad_accum={grad_accum} | batch_eff={config.batch_size * grad_accum}")
    _write_status(state="running", step=start_step, max_steps=args.max_steps, device=device,
                  params=n_params, vocab_size=config.vocab_size, best_val_loss=best_val,
                  total_tokens=meta.get("total_tokens"), model={
                      "n_layer": config.n_layer, "n_head": config.n_head,
                      "n_embd": config.n_embd, "block_size": config.block_size})

    t0 = time.time()
    tokens_seen = start_step * config.batch_size * config.block_size
    model.train()
    for step in range(start_step, args.max_steps + 1):
        lr = get_lr(step, config.learning_rate, args.warmup, args.max_steps)
        for g in optimizer.param_groups:
            g["lr"] = lr

        # ── Éval + log + checkpoint ──
        if step % args.eval_interval == 0 or step == args.max_steps:
            losses = estimate_loss(model, splits, config.block_size, config.batch_size, device, args.eval_iters)
            elapsed = time.time() - t0
            rec = {
                "step": step, "train_loss": round(losses["train"], 4), "val_loss": round(losses["val"], 4),
                "lr": round(lr, 6), "tokens_seen": tokens_seen, "elapsed_s": round(elapsed, 1),
                "ts": int(time.time()),
            }
            with METRICS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            _log(f"step {step:>5} | train {losses['train']:.4f} | val {losses['val']:.4f} | lr {lr:.2e} | {elapsed:.0f}s")
            _write_status(state="running", step=step, max_steps=args.max_steps, device=device,
                          params=n_params, vocab_size=config.vocab_size,
                          train_loss=round(losses["train"], 4), val_loss=round(losses["val"], 4),
                          best_val_loss=round(min(best_val, losses["val"]), 4),
                          tokens_seen=tokens_seen, elapsed_s=round(elapsed, 1),
                          total_tokens=meta.get("total_tokens"),
                          model={"n_layer": config.n_layer, "n_head": config.n_head,
                                 "n_embd": config.n_embd, "block_size": config.block_size})

            # Sauvegarde best + last
            payload = {"model_state_dict": model.state_dict(), "config": config, "step": step,
                       "best_val_loss": min(best_val, losses["val"]),
                       "optimizer_state_dict": optimizer.state_dict(), "meta": meta}
            torch.save(payload, last_ckpt)
            if losses["val"] < best_val:
                best_val = losses["val"]
                torch.save(payload, CKPT_DIR / "best_model.pt")

        if step == args.max_steps:
            break

        # ── Pas d'optimisation (accumulation de gradient + AMP) ──
        optimizer.zero_grad(set_to_none=True)
        for _ in range(grad_accum):
            x, y = get_batch(train_data, config.block_size, config.batch_size, device)
            with amp_ctx():
                _, loss = model(x, y)
                loss = loss / grad_accum
            scaler.scale(loss).backward()
            tokens_seen += config.batch_size * config.block_size
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optimizer)
        scaler.update()

    _write_status(state="done", step=args.max_steps, max_steps=args.max_steps, device=device,
                  params=n_params, vocab_size=config.vocab_size, best_val_loss=round(best_val, 4),
                  tokens_seen=tokens_seen, elapsed_s=round(time.time() - t0, 1),
                  total_tokens=meta.get("total_tokens"),
                  model={"n_layer": config.n_layer, "n_head": config.n_head,
                         "n_embd": config.n_embd, "block_size": config.block_size})
    _log(f"✓ terminé. best_val={best_val:.4f} | best → {CKPT_DIR / 'best_model.pt'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Entraîne NanoGPT from scratch.")
    ap.add_argument("--max-steps", type=int, default=3000)
    ap.add_argument("--batch-size", type=int, default=24)
    ap.add_argument("--block-size", type=int, default=256)
    ap.add_argument("--n-layer", type=int, default=6)
    ap.add_argument("--n-head", type=int, default=6)
    ap.add_argument("--n-embd", type=int, default=384)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--eval-interval", type=int, default=100)
    ap.add_argument("--eval-iters", type=int, default=40)
    ap.add_argument("--device", type=str, default=None, help="cuda|mps|cpu (auto si omis)")
    ap.add_argument("--amp", action="store_true", help="Mixed precision fp16 (recommandé sur GPU/T4).")
    ap.add_argument("--grad-accum", type=int, default=1, help="Accumulation de gradient (batch effectif = batch fois grad_accum).")
    ap.add_argument("--resume", action="store_true")
    train(ap.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
