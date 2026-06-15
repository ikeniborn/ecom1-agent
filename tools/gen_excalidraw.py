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


@dataclass
class Diagram:
    name: str
    rows: list[list[Node]]
    edges: list[Edge] = field(default_factory=list)


def render_diagram(d: Diagram, origin_y: float, frame_id: str) -> tuple[list[dict], float]:
    """Place rows top->down, wrap them in a frame, wire edges.

    Returns (elements, frame_bottom_y). Frame element is first in the list so it
    renders behind its children. The frame box is derived from the actual placed
    node extents + FRAME_PAD, guaranteeing every node fits inside the frame.
    """
    shapes: list[dict] = []
    texts: list[dict] = []
    by_id: dict[str, dict] = {}

    row_w = [sum(_node_size(n.kind)[0] for n in r) + COL_GAP * (len(r) - 1)
             for r in d.rows]
    content_w = max(row_w) if row_w else NODE_W

    y = snap(origin_y + FRAME_PAD + TITLE_BAND)
    for ri, row in enumerate(d.rows):
        row_h = max(_node_size(n.kind)[1] for n in row)
        x = FRAME_X + FRAME_PAD + (content_w - row_w[ri]) / 2
        for n in row:
            w, h = _node_size(n.kind)
            shape, text = make_node(n, x, y + (row_h - h) / 2, frame_id)
            shapes.append(shape)
            texts.append(text)
            by_id[n.id] = shape
            x += w + COL_GAP
        y = snap(y + row_h + ROW_GAP)

    minx = min(s["x"] for s in shapes)
    maxr = max(s["x"] + s["width"] for s in shapes)
    maxb = max(s["y"] + s["height"] for s in shapes)
    fx = snap(minx - FRAME_PAD)
    fy = snap(origin_y)
    fw = snap(maxr + FRAME_PAD - fx)
    fh = snap(maxb + FRAME_PAD - fy)
    frame = _frame(frame_id, fx, fy, fw, fh, d.name)

    edges: list[dict] = []
    for e in d.edges:
        edges += make_arrow(by_id[e.src], by_id[e.dst], e.dashed, e.label)

    return [frame, *shapes, *texts, *edges], fy + fh


def build_document(elements: list[dict]) -> dict:
    """Wrap elements in a schema-valid Excalidraw document envelope."""
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "tools/gen_excalidraw.py",
        "elements": elements,
        "appState": {"gridSize": GRID, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }


def unique_ids(doc: dict) -> bool:
    ids = [e["id"] for e in doc["elements"]]
    return len(ids) == len(set(ids))


def arrow_bindings_valid(doc: dict) -> bool:
    ids = {e["id"] for e in doc["elements"]}
    for e in doc["elements"]:
        if e["type"] != "arrow":
            continue
        for b in (e.get("startBinding"), e.get("endBinding")):
            if b and b["elementId"] not in ids:
                return False
    return True


def diagram1() -> Diagram:
    """Harness -> orchestrator -> pipeline, with the TRAIN_MAX_CYCLES feedback edge."""
    rows = [
        [Node("d1-start", "main.py: StartRun", "gate")],
        [Node("d1-trial", "StartTrial -> run_agent", "gate")],
        [Node("d1-open", "open VM + read /AGENTS.MD", "gate")],
        [Node("d1-schema", "schema discovery", "gate"),
         Node("d1-samples", "sample rows", "gate"),
         Node("d1-docs", "docs inventory", "gate"),
         Node("d1-deepread", "prephase_deep_read", "gate")],
        [Node("d1-pipeline", "run_pipeline", "gate")],
        [Node("d1-branch", "INTERPRETER_ENABLED?", "branch")],
        [Node("d1-endtrial", "EndTrial (per trial)", "gate")],
        [Node("d1-submit", "SubmitRun (after pool)", "gate")],
        [Node("d1-learn", "learn_from_grader", "llm")],
    ]
    edges = [
        Edge("d1-start", "d1-trial"),
        Edge("d1-trial", "d1-open"),
        Edge("d1-open", "d1-schema"),
        Edge("d1-open", "d1-samples"),
        Edge("d1-open", "d1-docs"),
        Edge("d1-open", "d1-deepread"),
        Edge("d1-schema", "d1-pipeline"),
        Edge("d1-samples", "d1-pipeline"),
        Edge("d1-docs", "d1-pipeline"),
        Edge("d1-deepread", "d1-pipeline"),
        Edge("d1-pipeline", "d1-branch"),
        Edge("d1-branch", "d1-endtrial"),
        Edge("d1-endtrial", "d1-submit"),
        Edge("d1-submit", "d1-learn"),
        # dashed training-loop feedback: distil grader feedback, re-run next cycle
        Edge("d1-learn", "d1-start", dashed=True, label="TRAIN_MAX_CYCLES"),
    ]
    return Diagram("Diagram 1 — End-to-end flow (harness -> pipeline)", rows, edges)


def diagram2() -> Diagram:
    """Legacy default branch: DESIGN -> CODEGEN/gates loop -> ANSWER -> outcomes."""
    rows = [
        [Node("d2-design", "DESIGN (1 LLM call, frozen)", "llm")],
        [Node("d2-override", "outcome_override?", "branch")],
        [Node("d2-codegen", "CODEGEN (LLM)", "llm")],
        [Node("d2-lint", "AST lint (ast.parse)", "gate")],
        [Node("d2-retry", "check_retry_loop", "gate")],
        [Node("d2-fidelity", "fidelity gate (subprocess)", "gate")],
        [Node("d2-answer", "ANSWER one-shot (_AnswerGuard)", "gate")],
        [Node("d2-learn", "LEARN + CONSOLIDATE", "llm")],
        [Node("d2-ok", "OUTCOME_OK", "terminal"),
         Node("d2-clar", "OUTCOME_NONE_CLARIFICATION", "terminal"),
         Node("d2-unsupported", "OUTCOME_NONE_UNSUPPORTED", "terminal"),
         Node("d2-deny", "OUTCOME_DENIED_SECURITY", "terminal")],
    ]
    edges = [
        Edge("d2-design", "d2-override"),
        Edge("d2-override", "d2-codegen"),
        Edge("d2-codegen", "d2-lint"),
        Edge("d2-lint", "d2-retry"),
        Edge("d2-retry", "d2-fidelity"),
        Edge("d2-fidelity", "d2-answer"),
        # ANSWER script may emit any outcome; OUTCOME_OK is the happy path
        Edge("d2-answer", "d2-ok"),
        Edge("d2-answer", "d2-clar"),
        Edge("d2-answer", "d2-unsupported"),
        Edge("d2-answer", "d2-deny"),
        # DESIGN's outcome_override short-circuits to any of the three non-OK terminals
        Edge("d2-override", "d2-clar"),
        Edge("d2-override", "d2-unsupported"),
        Edge("d2-override", "d2-deny"),
        # dashed feedback: codegen-fail / lint / fidelity -> LEARN -> next cycle
        Edge("d2-codegen", "d2-learn", dashed=True),
        Edge("d2-lint", "d2-learn", dashed=True),
        Edge("d2-fidelity", "d2-learn", dashed=True),
        Edge("d2-learn", "d2-codegen", dashed=True, label="next cycle"),
    ]
    return Diagram("Diagram 2 — Pipeline loop + gates (legacy, default branch)", rows, edges)


def diagram3() -> Diagram:
    """INTERPRETER_ENABLED branch: INTENT/PLAN -> lint -> deterministic interpret."""
    rows = [
        [Node("d3-deepread", "prephase facts + deep_read", "gate")],
        [Node("d3-intent", "run_intent (LLM -> IntentSpec)", "llm")],
        [Node("d3-plan", "run_plan (LLM -> PlanIR)", "llm")],
        [Node("d3-planir", "ir_models.PlanIR", "gate")],
        [Node("d3-lint", "lint_security_first", "gate")],
        [Node("d3-interpret", "interpret() — no LLM in loop", "gate")],
        [Node("d3-captured", "CapturedAnswer", "gate")],
        [Node("d3-ok", "OUTCOME_OK", "terminal"),
         Node("d3-clar", "OUTCOME_NONE_CLARIFICATION", "terminal")],
    ]
    edges = [
        Edge("d3-deepread", "d3-intent"),
        Edge("d3-intent", "d3-plan"),
        Edge("d3-plan", "d3-planir"),
        Edge("d3-planir", "d3-lint"),
        Edge("d3-lint", "d3-interpret"),
        Edge("d3-interpret", "d3-captured"),
        Edge("d3-captured", "d3-ok"),
        Edge("d3-captured", "d3-clar"),
        Edge("d3-interpret", "d3-plan", dashed=True, label="re-plan next cycle"),
    ]
    return Diagram("Diagram 3 — Deterministic interpreter (INTERPRETER_ENABLED)", rows, edges)
