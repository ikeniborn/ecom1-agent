"""Deterministic Excalidraw generator for the agent architecture guide.

Emits a single .excalidraw canvas with four stacked frame regions (one per
diagram) plus a legend strip. Re-runnable: same input -> byte-identical output
(no time, no randomness). All layout math lives here so the canvas stays clean.

Run:  uv run python tools/gen_excalidraw.py
Out:  docs/architecture/agent-architecture.excalidraw
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ── Layout constants (every coordinate snaps to GRID) ──────────────────────
GRID = 20
NODE_W = 240          # default rectangle width
NODE_H = 60           # default rectangle height
DIAMOND = 100         # branch diamond side
ELLIPSE_W, ELLIPSE_H = 220, 80   # storage ellipse
ROW_GAP = 80          # vertical gap between rows  (>= 40)
COL_GAP = 60          # horizontal gap between cols (>= 40)
FRAME_PAD = 40        # padding inside a frame      (>= 40)
FRAME_VGAP = 120      # vertical gap between stacked frames
FRAME_X = 0           # all frames left-aligned
TITLE_BAND = 40       # blank band under the frame title before the first row

# ── Legend palette (kind -> shape + fill) ──────────────────────────────────
# blue=LLM call, grey=deterministic step/gate, green=storage,
# yellow=branch/condition, red(rounded)=terminal outcome.
KIND = {
    "llm":      {"shape": "rectangle", "bg": "#a5d8ff"},
    "gate":     {"shape": "rectangle", "bg": "#e9ecef"},
    "store":    {"shape": "ellipse",   "bg": "#b2f2bb"},
    "branch":   {"shape": "diamond",   "bg": "#ffec99"},
    "terminal": {"shape": "rectangle", "bg": "#ffc9c9", "round": True},
}
STROKE = "#1e1e1e"


def snap(v: float) -> float:
    """Snap a coordinate to the nearest grid step."""
    return round(v / GRID) * GRID
