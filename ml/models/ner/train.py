"""entraîne le NER BiGRU."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch
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
from torch import nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, random_split

from jenny.core.logging import get_logger, setup_logging
from ml.models.ner.config import ENTITY_TYPES, ID_TO_TAG, NERModelConfig
from ml.models.ner.dataset import NERDataset, generate_sample_data
from ml.models.ner.model import BiGRUNER

logger = get_logger(__name__)
console = Console()


def train_ner_model(
    config: NERModelConfig | None = None,
    data_path: str | None = None,
    output_dir: str = "checkpoints/ner",
) -> BiGRUNER:
    """entraîne le modèle."""
    setup_logging()
    config = config or NERModelConfig()
    torch.manual_seed(config.seed)

    console.print(
        Panel.fit(
            "[bold blue]🏷️ JENNY — Entraînement NER BiGRU[/bold blue]\n"
            f"[dim]Device: {config.device} • Epochs: {config.epochs} • Entités: {len(ENTITY_TYPES)}[/dim]",
            border_style="blue",
        )
    )

    # 1. charge les données
    if data_path and Path(data_path).exists():
        dataset = NERDataset.from_jsonl(data_path, config=config)
        console.print(
            f"  📂 Données chargées : [green]{data_path}[/green] ({len(dataset):,} exemples)"
        )
    else:
        token_seqs, tag_seqs = generate_sample_data()
        dataset = NERDataset(token_seqs, tag_seqs, config=config)
        console.print(f"  📂 Données sample : [yellow]{len(dataset):,} exemples[/yellow]")

    # 2. split train/val/test
    total = len(dataset)
    train_size = int(0.70 * total)
    val_size = int(0.15 * total)
    test_size = total - train_size - val_size

    train_dataset, val_dataset, test_dataset = random_split(
        dataset,
        [train_size, val_size, test_size],
        generator=torch.Generator().manual_seed(config.seed),
    )

    train_loader = DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=config.batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=config.batch_size, shuffle=False)

    split_table = Table(title="📊 Dataset Split")
    split_table.add_column("Split", style="cyan")
    split_table.add_column("Exemples", style="green", justify="right")
    split_table.add_column("Ratio", style="dim", justify="right")
    split_table.add_row("Train", f"{train_size:,}", "70%")
    split_table.add_row("Validation", f"{val_size:,}", "15%")
    split_table.add_row("Test", f"{test_size:,}", "15%")
    split_table.add_row("[bold]Total[/bold]", f"[bold]{total:,}[/bold]", "100%")
    console.print(split_table)

    # 3. modèle
    config.vocab_size = len(dataset.vocab)
    model = BiGRUNER(config)
    model = model.to(config.device)

    model_table = Table(title="🏗️ Architecture")
    model_table.add_column("Param", style="cyan")
    model_table.add_column("Valeur", style="green")
    model_table.add_row("Paramètres", f"{model.count_parameters():,}")
    model_table.add_row("Vocab", f"{config.vocab_size:,}")
    model_table.add_row("Device", config.device)
    model_table.add_row("Tags BIO", f"{config.num_tags}")
    model_table.add_row("Entités", f"{len(ENTITY_TYPES)} ({', '.join(ENTITY_TYPES[:5])}...)")
    console.print(model_table)

    # 4. optim, loss, scheduler
    optimizer = AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    scheduler = ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=0.5,
        patience=5,
    )

    # ignore le padding (-100)
    criterion = nn.CrossEntropyLoss(ignore_index=-100)
    console.print("  📉 Loss : [cyan]CrossEntropyLoss[/cyan] (ignore_index=-100)")

    # 5. boucle d'entraînement
    best_f1 = 0.0
    patience_counter = 0
    max_patience = 10
    history: list[dict] = []

    console.print(
        f"\n[bold]🚀 Entraînement ({config.epochs} epochs, patience={max_patience})[/bold]\n"
    )

    epoch_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=50),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    with epoch_progress:
        task_epoch = epoch_progress.add_task("[blue]Epochs", total=config.epochs)

        for epoch in range(config.epochs):
            epoch_start = time.time()
            model.train()
            total_loss = 0.0

            for batch in train_loader:
                input_ids = batch["input_ids"].to(config.device)
                attention_mask = batch["attention_mask"].to(config.device)
                labels = batch["labels"].to(config.device)

                optimizer.zero_grad()
                logits = model(input_ids, attention_mask)

                logits_flat = logits.view(-1, config.num_tags)
                labels_flat = labels.view(-1)

                loss = criterion(logits_flat, labels_flat)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                total_loss += loss.item()

            avg_loss = total_loss / max(len(train_loader), 1)

            # éval validation
            val_f1 = _evaluate(model, val_loader, config)
            scheduler.step(val_f1)
            current_lr = optimizer.param_groups[0]["lr"]

            epoch_time = time.time() - epoch_start

            history.append(
                {
                    "epoch": epoch + 1,
                    "loss": avg_loss,
                    "val_f1": val_f1,
                    "lr": current_lr,
                    "time": epoch_time,
                }
            )

            epoch_progress.update(
                task_epoch,
                description=(
                    f"[blue]Epoch {epoch + 1:3d}/{config.epochs} │ "
                    f"Loss: {avg_loss:.4f} │ "
                    f"Val F1: {val_f1:.1%} │ "
                    f"LR: {current_lr:.1e}"
                ),
            )
            epoch_progress.advance(task_epoch)

            # garde le meilleur
            if val_f1 > best_f1:
                best_f1 = val_f1
                patience_counter = 0
                _save_checkpoint(model, dataset.vocab, config, output_dir)
                console.print(
                    f"  [green]✨ Nouveau best: Val F1={val_f1:.2%} (epoch {epoch + 1})[/green]"
                )
            else:
                patience_counter += 1

            # early stopping
            if patience_counter >= max_patience:
                console.print(
                    f"\n  [yellow]⏹ Early stopping à l'epoch {epoch + 1} (patience={max_patience})[/yellow]"
                )
                break

    # 6. éval finale test
    console.print("\n[bold cyan]📋 Évaluation sur le Test Set[/bold cyan]")

    # recharge le meilleur
    best_path = Path(output_dir) / "best_model.pt"
    if best_path.exists():
        checkpoint = torch.load(best_path, map_location=config.device, weights_only=False)
        model.load_state_dict(checkpoint["model_state_dict"])
        console.print("  📦 Meilleur modèle rechargé")

    test_f1, test_details = _evaluate_detailed(model, test_loader, config)

    results_table = Table(title="🎯 Résultats Finaux")
    results_table.add_column("Métrique", style="cyan")
    results_table.add_column("Valeur", style="green", justify="right")
    results_table.add_row("Best Val F1", f"{best_f1:.2%}")
    results_table.add_row("[bold]Test F1[/bold]", f"[bold]{test_f1:.2%}[/bold]")
    results_table.add_row("Test Precision", f"{test_details.get('precision', 0):.2%}")
    results_table.add_row("Test Recall", f"{test_details.get('recall', 0):.2%}")
    results_table.add_row("Epochs effectués", str(len(history)))
    results_table.add_row("Checkpoint", str(best_path))
    console.print(results_table)

    # métriques par entité
    if test_details.get("per_entity"):
        entity_table = Table(title="📊 F1 par type d'entité")
        entity_table.add_column("Entité", style="cyan")
        entity_table.add_column("F1", style="green", justify="right")
        entity_table.add_column("Support", style="dim", justify="right")
        for entity_name, metrics in sorted(
            test_details["per_entity"].items(),
            key=lambda x: x[1]["f1"],
            reverse=True,
        ):
            f1 = metrics["f1"]
            support = metrics["support"]
            color = "green" if f1 > 0.7 else ("yellow" if f1 > 0.4 else "red")
            entity_table.add_row(entity_name, f"[{color}]{f1:.2%}[/{color}]", str(support))
        console.print(entity_table)

    console.print(
        Panel.fit(
            f"[bold green]✅ Entraînement NER terminé — Test F1: {test_f1:.2%}[/bold green]",
            border_style="green",
        )
    )

    return model


def _evaluate(
    model: BiGRUNER,
    loader: DataLoader,
    config: NERModelConfig,
) -> float:
    """f1 token-level."""
    model.eval()
    correct_entities = 0
    predicted_entities = 0
    true_entities = 0

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(config.device)
            attention_mask = batch["attention_mask"].to(config.device)
            labels = batch["labels"].to(config.device)

            preds = model.predict_tags(input_ids, attention_mask)

            for i in range(labels.size(0)):
                mask = attention_mask[i].bool()
                pred_tags = preds[i][mask].cpu().tolist()
                true_tags = labels[i][mask].cpu().tolist()

                for p, t in zip(pred_tags, true_tags, strict=False):
                    if t != 0:
                        true_entities += 1
                        if p == t:
                            correct_entities += 1
                    if p != 0:
                        predicted_entities += 1

    precision = correct_entities / max(predicted_entities, 1)
    recall = correct_entities / max(true_entities, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)

    return f1


def _evaluate_detailed(
    model: BiGRUNER,
    loader: DataLoader,
    config: NERModelConfig,
) -> tuple[float, dict]:
    """métriques détaillées par entité."""
    model.eval()

    # compteurs par entité
    entity_tp: dict[str, int] = {}
    entity_fp: dict[str, int] = {}
    entity_fn: dict[str, int] = {}

    for ent_type in ENTITY_TYPES:
        entity_tp[ent_type] = 0
        entity_fp[ent_type] = 0
        entity_fn[ent_type] = 0

    total_tp = 0
    total_fp = 0
    total_fn = 0

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(config.device)
            attention_mask = batch["attention_mask"].to(config.device)
            labels = batch["labels"].to(config.device)

            preds = model.predict_tags(input_ids, attention_mask)

            for i in range(labels.size(0)):
                mask = attention_mask[i].bool()
                pred_tags = preds[i][mask].cpu().tolist()
                true_tags = labels[i][mask].cpu().tolist()

                for p, t in zip(pred_tags, true_tags, strict=False):
                    p_tag = ID_TO_TAG.get(p, "O")
                    t_tag = ID_TO_TAG.get(t, "O")

                    # extrait le type
                    p_entity = p_tag.split("-", 1)[1] if "-" in p_tag else None
                    t_entity = t_tag.split("-", 1)[1] if "-" in t_tag else None

                    if t != 0:  # vraie entité
                        total_fn += 1 if p != t else 0
                        total_tp += 1 if p == t else 0
                        if t_entity:
                            if p == t:
                                entity_tp[t_entity] = entity_tp.get(t_entity, 0) + 1
                            else:
                                entity_fn[t_entity] = entity_fn.get(t_entity, 0) + 1
                    if p != 0 and p != t:  # faux positif
                        total_fp += 1
                        if p_entity:
                            entity_fp[p_entity] = entity_fp.get(p_entity, 0) + 1

    precision = total_tp / max(total_tp + total_fp, 1)
    recall = total_tp / max(total_tp + total_fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)

    per_entity = {}
    for ent_type in ENTITY_TYPES:
        tp = entity_tp.get(ent_type, 0)
        fp = entity_fp.get(ent_type, 0)
        fn = entity_fn.get(ent_type, 0)
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        ef1 = 2 * p * r / max(p + r, 1e-8)
        per_entity[ent_type] = {"f1": ef1, "precision": p, "recall": r, "support": tp + fn}

    return f1, {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "per_entity": per_entity,
    }


def _save_checkpoint(
    model: BiGRUNER,
    vocab: dict[str, int],
    config: NERModelConfig,
    output_dir: str,
) -> None:
    """sauvegarde le modèle."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "config": config,
            "vocab": vocab,
        },
        path / "best_model.pt",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entraîner le modèle NER BiGRU")
    parser.add_argument("--data", type=str, default=None, help="Chemin JSONL")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--output", type=str, default="checkpoints/ner")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    cfg = NERModelConfig(epochs=args.epochs, batch_size=args.batch_size)
    train_ner_model(config=cfg, data_path=args.data, output_dir=args.output)
