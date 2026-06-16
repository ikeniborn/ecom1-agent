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


# Approx glyph advance at fontSize 16 (Virgil-ish), plus L/R padding. Used to
# grow a node so its bound label never overflows the shape.
_CHAR_PX = 9
_LABEL_PAD = 40


def _node_size(kind: str, label: str = "") -> tuple[int, int]:
    """Shape (w, h), grown to fit `label`. Width snaps to GRID; never below the
    per-shape default. The fill factors account for usable text area: a diamond
    only exposes ~half its width at mid-height; an ellipse ~70%."""
    shape = KIND[kind]["shape"]
    need = len(label) * _CHAR_PX + _LABEL_PAD
    if shape == "diamond":
        return max(DIAMOND, int(snap(need / 0.5))), DIAMOND
    if shape == "ellipse":
        return max(ELLIPSE_W, int(snap(need / 0.72))), ELLIPSE_H
    return max(NODE_W, int(snap(need))), NODE_H


def make_node(node: Node, x: float, y: float, frame_id: str) -> tuple[dict, dict]:
    """Build a shape element and its bound text label (top-left at x, y)."""
    spec = KIND[node.kind]
    w, h = _node_size(node.kind, node.label)
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


def make_arrow(a: dict, b: dict, dashed: bool = False, label: str = "",
               points_abs: list[tuple[float, float]] | None = None) -> list[dict]:
    """Bound arrow from shape a to shape b, with reciprocal boundElements.

    `points_abs` is an optional absolute polyline (orthogonal route computed by
    `render_diagram`); without it the arrow is a straight center-to-edge segment.
    """
    if points_abs is None:
        points_abs = [_anchor(a, b), _anchor(b, a)]
    ox, oy = snap(points_abs[0][0]), snap(points_abs[0][1])
    rel = [[float(px - ox), float(py - oy)] for px, py in points_abs]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    aid = f"e-{a['id']}-{b['id']}"
    arrow = _base(aid, "arrow", ox, oy,
                  (max(xs) - min(xs)) or 1.0, (max(ys) - min(ys)) or 1.0,
                  a.get("frameId"))
    arrow.update({
        "points": rel,
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
        i = len(points_abs) // 2                       # midpoint of the middle segment
        mx = (points_abs[i - 1][0] + points_abs[i][0]) / 2
        my = (points_abs[i - 1][1] + points_abs[i][1]) / 2
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

    row_w = [sum(_node_size(n.kind, n.label)[0] for n in r) + COL_GAP * (len(r) - 1)
             for r in d.rows]
    content_w = max(row_w) if row_w else NODE_W

    row_of: dict[str, int] = {}
    y = snap(origin_y + FRAME_PAD + TITLE_BAND)
    for ri, row in enumerate(d.rows):
        row_h = max(_node_size(n.kind, n.label)[1] for n in row)
        x = FRAME_X + FRAME_PAD + (content_w - row_w[ri]) / 2
        for n in row:
            w, h = _node_size(n.kind, n.label)
            shape, text = make_node(n, x, y + (row_h - h) / 2, frame_id)
            shapes.append(shape)
            texts.append(text)
            by_id[n.id] = shape
            row_of[n.id] = ri
            x += w + COL_GAP
        y = snap(y + row_h + ROW_GAP)

    # ── Orthogonal edge routing ───────────────────────────────────────────
    # Adjacent rows (tr == sr+1): elbow through the inter-row gap (no boxes
    # live there). Everything else (forward skips, back/feedback edges): a
    # right-side gutter lane, entering the target from the gap above its row.
    # Both keep arrow polylines clear of every non-endpoint node box.
    minx = min(s["x"] for s in shapes)
    content_right = max(s["x"] + s["width"] for s in shapes)
    gutter0 = snap(content_right + COL_GAP)
    half_gap = ROW_GAP / 2

    def _cx(s: dict) -> float:
        return s["x"] + s["width"] / 2

    routes: list[tuple[Edge, list[tuple[float, float]]]] = []
    lane_i = 0
    for e in d.edges:
        a, b = by_id[e.src], by_id[e.dst]
        sr, tr = row_of[e.src], row_of[e.dst]
        acx, bcx = _cx(a), _cx(b)
        if tr == sr + 1:                                    # adjacent: gap elbow
            sy_b = a["y"] + a["height"]
            ty_t = b["y"]
            if abs(acx - bcx) < 1:
                pts = [(acx, sy_b), (bcx, ty_t)]
            else:
                mid = (sy_b + ty_t) / 2
                pts = [(acx, sy_b), (acx, mid), (bcx, mid), (bcx, ty_t)]
        else:                                               # skip / back: gutter
            lane = gutter0 + lane_i * COL_GAP
            lane_i += 1
            s_right = a["x"] + a["width"]
            scy = a["y"] + a["height"] / 2
            approach = b["y"] - half_gap
            pts = [(s_right, scy), (lane, scy),
                   (lane, approach), (bcx, approach), (bcx, b["y"])]
        routes.append((e, pts))

    max_lane = gutter0 + (lane_i - 1) * COL_GAP if lane_i else content_right

    maxb = max(s["y"] + s["height"] for s in shapes)
    fx = snap(minx - FRAME_PAD)
    fy = snap(origin_y)
    fw = snap(max(content_right, max_lane) + FRAME_PAD - fx)
    fh = snap(maxb + FRAME_PAD - fy)
    frame = _frame(frame_id, fx, fy, fw, fh, d.name)

    edges: list[dict] = []
    for e, pts in routes:
        edges += make_arrow(by_id[e.src], by_id[e.dst], e.dashed, e.label, pts)

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
    """Harness -> orchestrator -> IR-only pipeline, with the TRAIN_MAX_CYCLES edge."""
    rows = [
        [Node("d1-start", "main.py: StartRun", "gate")],
        [Node("d1-trial", "StartTrial -> run_agent", "gate")],
        [Node("d1-open", "open VM + read /AGENTS.MD", "gate")],
        [Node("d1-schema", "schema discovery", "gate"),
         Node("d1-samples", "sample rows", "gate"),
         Node("d1-docs", "docs inventory", "gate"),
         Node("d1-deepread", "prephase_deep_read", "gate")],
        [Node("d1-pipeline", "run_pipeline (IR-only)", "gate")],
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
        Edge("d1-pipeline", "d1-endtrial"),
        Edge("d1-endtrial", "d1-submit"),
        Edge("d1-submit", "d1-learn"),
        # dashed training-loop feedback: distil grader feedback, re-run next cycle
        Edge("d1-learn", "d1-start", dashed=True, label="TRAIN_MAX_CYCLES"),
    ]
    return Diagram("Diagram 1 — End-to-end flow (harness -> pipeline)", rows, edges)


def diagram2() -> Diagram:
    """IR-only pipeline: INTENT (frozen) then PLAN -> lint -> interpret -> verify
    cycle, LEARN between cycles, one vm.answer at the end."""
    rows = [
        [Node("d2-intent", "INTENT — run_intent (frozen, retried)", "llm")],
        [Node("d2-plan", "PLAN — run_plan (+learn_ctx +atoms +observed)", "llm")],
        [Node("d2-lint", "lint_security_first", "gate")],
        [Node("d2-ident", "identical plan?", "branch")],
        [Node("d2-interpret", "interpret() — deterministic, no LLM", "gate")],
        [Node("d2-verify", "verify() — invariants + criteria", "gate")],
        [Node("d2-answer", "vm.answer once (+persist +distill)", "gate")],
        [Node("d2-learn", "_ilearn (LEARN between cycles)", "llm")],
        [Node("d2-ok", "OUTCOME_OK", "terminal"),
         Node("d2-clar", "OUTCOME_NONE_CLARIFICATION", "terminal"),
         Node("d2-unsup", "OUTCOME_NONE_UNSUPPORTED", "terminal"),
         Node("d2-deny", "OUTCOME_DENIED_SECURITY", "terminal")],
    ]
    edges = [
        Edge("d2-intent", "d2-plan"),
        Edge("d2-plan", "d2-lint"),
        Edge("d2-lint", "d2-ident"),
        Edge("d2-ident", "d2-interpret", label="new"),
        Edge("d2-ident", "d2-clar", label="identical"),
        Edge("d2-interpret", "d2-verify"),
        # verify ok -> single answer carrying the plan-chosen outcome
        Edge("d2-verify", "d2-answer", label="ok"),
        Edge("d2-answer", "d2-ok"),
        Edge("d2-answer", "d2-clar"),
        Edge("d2-answer", "d2-unsup"),
        Edge("d2-answer", "d2-deny"),
        # dashed feedback: plan/lint err, interpret err, verify fail -> LEARN -> re-plan
        Edge("d2-lint", "d2-learn", dashed=True, label="plan/lint err"),
        Edge("d2-interpret", "d2-learn", dashed=True, label="interpret err"),
        Edge("d2-verify", "d2-learn", dashed=True, label="verify fail"),
        Edge("d2-learn", "d2-plan", dashed=True, label="re-plan next cycle"),
        Edge("d2-learn", "d2-clar", dashed=True, label="cycles exhausted"),
    ]
    return Diagram("Diagram 2 — IR pipeline cycle + gates", rows, edges)


def diagram3() -> Diagram:
    """Zoom into interpret() + verify(): how one PlanIR is executed deterministically."""
    rows = [
        [Node("d3-plan", "PlanIR (ops, steps, answer)", "gate")],
        [Node("d3-resolve", "resolve columns (ColResolve)", "gate")],
        [Node("d3-steps", "run steps + RPC ops (RowSet / ComputeStep)", "gate")],
        [Node("d3-classify", "classify outcome (OutcomeFromExit)", "gate")],
        [Node("d3-project", "project required_refs[outcome]", "gate")],
        [Node("d3-captured", "CapturedAnswer (message, outcome, refs)", "gate")],
        [Node("d3-verify", "verify() — I1 refs / I3 security / criteria", "gate")],
        [Node("d3-ok", "ok -> vm.answer", "terminal"),
         Node("d3-refuse", "_refuse -> InterpretError", "terminal")],
    ]
    edges = [
        Edge("d3-plan", "d3-resolve"),
        Edge("d3-resolve", "d3-steps"),
        Edge("d3-steps", "d3-classify"),
        Edge("d3-classify", "d3-project"),
        Edge("d3-project", "d3-captured"),
        Edge("d3-captured", "d3-verify"),
        Edge("d3-verify", "d3-ok", label="pass"),
        Edge("d3-verify", "d3-refuse", label="fail"),
        # an unresolved required ref on an OK answer refuses inside interpret()
        Edge("d3-project", "d3-refuse", dashed=True, label="unresolved ref"),
    ]
    return Diagram("Diagram 3 — interpret() + verify() internals", rows, edges)


def diagram4() -> Diagram:
    """Cross-cutting subsystems: LEARN store, knowledge oracle (read + write-back),
    LLM routing + trace."""
    rows = [
        [Node("d4-learn", "LEARN _ilearn (pipeline.py)", "llm"),
         Node("d4-oracle", "oracle.retrieve + distill", "llm"),
         Node("d4-route", "LLM routing (llm.py)", "gate")],
        [Node("d4-yaml", "data/learned/{tid}.yaml", "store"),
         Node("d4-atoms", "data/oracle/atoms.yaml", "store"),
         Node("d4-trace", "trace JSONL (trace.py)", "store")],
        [Node("d4-plan", "PLAN / interpret (run_pipeline)", "gate")],
    ]
    edges = [
        Edge("d4-learn", "d4-yaml"),
        Edge("d4-oracle", "d4-atoms"),
        Edge("d4-route", "d4-trace"),
        Edge("d4-yaml", "d4-plan", dashed=True, label="active rules"),
        Edge("d4-atoms", "d4-plan", dashed=True, label="K atoms"),
        Edge("d4-route", "d4-plan", label="tier + fallback"),
        # on success the validated plan distils a new atom back into the bank
        Edge("d4-plan", "d4-atoms", dashed=True, label="distill->validate->promote"),
    ]
    return Diagram("Diagram 4 — Cross-cutting subsystems", rows, edges)


def legend() -> Diagram:
    """Shape/color vocabulary, one swatch per legend row."""
    rows = [
        [Node("lg-llm", "Blue rectangle = LLM call", "llm")],
        [Node("lg-gate", "Grey rectangle = deterministic step / gate", "gate")],
        [Node("lg-store", "Green ellipse = storage (yaml / json / atoms)", "store")],
        [Node("lg-branch", "Yellow diamond = branch / condition", "branch")],
        [Node("lg-term", "Red rounded = terminal outcome", "terminal")],
        [Node("lg-solid", "-> solid arrow = control flow", "gate")],
        [Node("lg-dashed", "--> dashed arrow = feedback / learning", "gate")],
    ]
    return Diagram("Legend", rows, edges=[])


OUT_PATH = (Path(__file__).resolve().parent.parent
            / "docs" / "architecture" / "agent-architecture.excalidraw")


def assemble() -> dict:
    """Stack all diagrams + legend into one schema-valid document."""
    diagrams = [diagram1(), diagram2(), diagram3(), diagram4(), legend()]
    elements: list[dict] = []
    y = 0.0
    for i, d in enumerate(diagrams, start=1):
        elems, bottom = render_diagram(d, y, f"frame-{i}")
        elements += elems
        y = bottom + FRAME_VGAP
    return build_document(elements)


def main(out: Path = OUT_PATH) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = assemble()
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out


if __name__ == "__main__":
    written = main()
    print(f"wrote {written}")
