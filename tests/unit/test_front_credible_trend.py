"""Tendance du volume : jamais de hausse inventée."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_TREND = Path(__file__).resolve().parents[2] / "frontend/src/components/analytics/trend.ts"

_NODE = shutil.which("node")


def _node_strips_types() -> bool:
    """Node lit le TS tout seul ?"""
    if not _NODE:
        return False
    out = subprocess.run([_NODE, "--version"], capture_output=True, text=True).stdout
    major, minor = (int(x) for x in out.strip().lstrip("v").split(".")[:2])
    return (major, minor) >= (22, 6)


pytestmark = pytest.mark.skipif(not _node_strips_types(), reason="node >= 22.6 requis")


def _trend(counts: list[int]) -> dict | None:
    """Appelle computeTrend via node."""
    script = (
        f"const m = await import({json.dumps(_TREND.as_uri())});"
        f"const days = {json.dumps(counts)}.map((count) => ({{ count }}));"
        "const r = m.computeTrend(days);"
        # garde le signe de -0
        "if (r && Object.is(r.pct, -0)) r.pct = '-0';"
        "console.log(JSON.stringify(r));"
    )
    res = subprocess.run(
        [_NODE, "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_flat_week_shows_no_trend() -> None:
    """7 j plats : pas de faux +33 %."""
    assert _trend([10] * 7) is None


def test_flat_month_is_zero() -> None:
    """30 j plats : 0 %."""
    t = _trend([10] * 30)
    assert t == {"pct": 0, "span": 14}


def test_partial_edges_ignored() -> None:
    """Jours tronqués aux bords ignorés."""
    # 1er jour coupé, aujourd'hui pas fini
    counts = [3] + [10] * 28 + [2]
    assert _trend(counts) == {"pct": 0, "span": 14}


def test_real_growth_and_drop() -> None:
    """Vraie hausse et vraie baisse."""
    up = [0] + [10] * 14 + [20] * 14 + [0]
    assert _trend(up) == {"pct": 100, "span": 14}
    down = [0] + [20] * 14 + [10] * 14 + [0]
    assert _trend(down) == {"pct": -50, "span": 14}


def test_quarter_uses_whole_weeks() -> None:
    """90 j : blocs de 6 semaines."""
    t = _trend([5] * 90)
    assert t == {"pct": 0, "span": 42}


def test_tiny_drop_is_not_minus_zero() -> None:
    """Petite baisse : 0 %, pas -0."""
    counts = [0] + [1000] * 14 + [1000] * 13 + [999] + [0]
    assert _trend(counts) == {"pct": 0, "span": 14}


def test_empty_start_gives_nothing() -> None:
    """Début vide : pas de pourcentage."""
    assert _trend([0] * 15 + [10] * 15) is None
