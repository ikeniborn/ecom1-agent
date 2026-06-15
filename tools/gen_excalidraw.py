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


# ── Deterministic ids ──────────────────────────────────────────────────────
def _stable_seed(eid: str) -> int:
    """Pure pseudo-seed derived from the element id (no randomness)."""
    h = 2166136261
    for ch in eid:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _base(eid: str, etype: str, x: float, y: float,
          w: float, h: float, frame_id: str | None = None) -> dict:
    """Common Excalidraw element fields shared by every element type."""
    return {
        "id": eid,
        "type": etype,
        "x": float(snap(x)),
        "y": float(snap(y)),
        "width": float(w),
        "height": float(h),
        "angle": 0,
        "strokeColor": STROKE,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": frame_id,
        "roundness": None,
        "seed": _stable_seed(eid),
        "version": 1,
        "versionNonce": _stable_seed(eid + "#n"),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }


# ── Declarative node/edge specs ────────────────────────────────────────────
@dataclass
class Node:
    id: str          # unique across the whole document
    label: str
    kind: str        # one of KIND


@dataclass
class Edge:
    src: str
    dst: str
    dashed: bool = False
    label: str = ""


def _node_size(kind: str) -> tuple[int, int]:
    shape = KIND[kind]["shape"]
    if shape == "diamond":
        return DIAMOND, DIAMOND
    if shape == "ellipse":
        return ELLIPSE_W, ELLIPSE_H
    return NODE_W, NODE_H


def make_node(node: Node, x: float, y: float, frame_id: str) -> tuple[dict, dict]:
    """Build a shape element and its bound text label (top-left at x, y)."""
    spec = KIND[node.kind]
    w, h = _node_size(node.kind)
    shape = _base(node.id, spec["shape"], x, y, w, h, frame_id)
    shape["backgroundColor"] = spec["bg"]
    if spec.get("round"):
        shape["roundness"] = {"type": 3}

    tid = f"{node.id}-t"
    text = _base(tid, "text", x, y, w, h, frame_id)
    text.update({
        "text": node.label,
        "fontSize": 16,
        "fontFamily": 1,
        "textAlign": "center",
        "verticalAlign": "middle",
        "containerId": node.id,
        "originalText": node.label,
        "lineHeight": 1.25,
        "baseline": 12,
        "autoResize": True,
    })
    shape["boundElements"] = [{"type": "text", "id": tid}]
    return shape, text


def _center(e: dict) -> tuple[float, float]:
    return e["x"] + e["width"] / 2, e["y"] + e["height"] / 2


def _anchor(a: dict, b: dict) -> tuple[float, float]:
    """Point on a's bounding box facing b's center (orthogonal exit)."""
    ax, ay = _center(a)
    bx, by = _center(b)
    if abs(by - ay) >= abs(bx - ax):                      # mostly vertical
        return ax, (a["y"] + a["height"] if by > ay else a["y"])
    return (a["x"] + a["width"] if bx > ax else a["x"]), ay   # mostly horizontal


def make_arrow(a: dict, b: dict, dashed: bool = False, label: str = "") -> list[dict]:
    """Bound arrow from shape a to shape b, with reciprocal boundElements."""
    sx, sy = _anchor(a, b)
    ex, ey = _anchor(b, a)
    aid = f"e-{a['id']}-{b['id']}"
    arrow = _base(aid, "arrow", sx, sy, abs(ex - sx) or 1.0, abs(ey - sy) or 1.0,
                  a.get("frameId"))
    arrow.update({
        "points": [[0.0, 0.0], [float(ex - sx), float(ey - sy)]],
        "lastCommittedPoint": None,
        "startBinding": {"elementId": a["id"], "focus": 0, "gap": 8},
        "endBinding": {"elementId": b["id"], "focus": 0, "gap": 8},
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "strokeStyle": "dashed" if dashed else "solid",
    })
    a["boundElements"].append({"type": "arrow", "id": aid})
    b["boundElements"].append({"type": "arrow", "id": aid})
    out = [arrow]
    if label:
        lid = f"{aid}-lbl"
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        lt = _base(lid, "text", mx, my, max(40, len(label) * 9), 20, a.get("frameId"))
        lt.update({
            "text": label, "fontSize": 14, "fontFamily": 1,
            "textAlign": "center", "verticalAlign": "middle",
            "containerId": aid, "originalText": label,
            "lineHeight": 1.25, "baseline": 12, "autoResize": True,
        })
        arrow["boundElements"] = [{"type": "text", "id": lid}]
        out.append(lt)
    return out


def _frame(fid: str, x: float, y: float, w: float, h: float, name: str) -> dict:
    f = _base(fid, "frame", x, y, w, h, None)
    f["name"] = name
    return f
