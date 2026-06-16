---
review:
  plan_hash: e6d11e1c0436c896
  spec_hash: efdb8ce5d2e45fc4
  last_run: 2026-06-15
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings: []
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-15-agent-architecture-guide-design.md
---
# Agent Architecture Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a deterministic Python generator that emits one schema-valid Excalidraw canvas (four stacked diagram frames + a legend strip) describing the agent runtime architecture, plus a dense Markdown companion guide with verified `file:line` references — both under `docs/architecture/`.

**Architecture:** A small declarative layout engine in `tools/gen_excalidraw.py` turns compact `Diagram` specs (rows of typed `Node`s + `Edge`s) into Excalidraw element dicts. The engine owns all coordinate math, grid-snapping, frame bounding-box computation, and arrow bindings, so layout stays clean and re-runnable (no randomness, no `Date.now`). Each diagram is self-contained inside its own frame (no cross-frame arrows). A pytest suite enforces schema validity, id uniqueness, arrow-binding integrity, the measurable layout rules from the spec, and `file:line` ref resolution for the Markdown guide.

**Tech Stack:** Python 3.12, stdlib only (`json`, `dataclasses`, `pathlib`, `re`), pytest, `uv run`. No browser/node tooling.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tools/__init__.py` | Make `tools` an importable package (mirrors `scripts/__init__.py`) so tests can `import tools.gen_excalidraw`. |
| `tools/gen_excalidraw.py` | All generator logic: layout constants, legend palette, deterministic element builders, declarative layout engine, the four diagram specs + legend, document envelope, integrity helpers, `main()` writer. |
| `docs/architecture/agent-architecture.excalidraw` | **Generated** output canvas (committed deliverable). |
| `docs/architecture/agent-architecture-guide.md` | Hand-authored Markdown guide: one section per diagram, legend table, "where to change what" map, with `file:line` references. |
| `tests/test_gen_excalidraw.py` | Unit + structural tests for the generator (primitives, schema, uniqueness, bindings, layout rules, determinism). |
| `tests/test_architecture_guide_refs.py` | Parses `file:line` tokens from the Markdown guide and asserts each resolves to a real location. |

**Design rationale (decisions locked here):**

- **One Excalidraw primitive per logical node.** Each node is exactly one shape element (`rectangle` / `diamond` / `ellipse`) plus one *bound* text child (`containerId` → shape). This keeps the bounding-box overlap check unambiguous (one box per node) and renders cleanly in excalidraw.app.
- **Storage glyph = green `ellipse`.** Excalidraw has no native `cylinder` primitive. The spec legend says "green cylinder"; we render storage as a single green `ellipse` (the canonical single-primitive storage glyph used by mermaid-to-excalidraw converters) and say so in the Markdown legend. This is an explicit, documented substitution — not a silent deviation.
- **Diagrams are self-contained.** Every `Edge` connects two nodes in the *same* diagram, so no arrow crosses a frame boundary. The layout test still guards the spec rule ("an arrow crosses a frame boundary only when it is an explicitly labeled cross-diagram reference") so it stays correct if someone later adds a cross-ref.
- **Determinism.** Element `id`s are author-given (diagram-prefixed) or derived by suffix; `seed`/`versionNonce` are derived from the id via a pure function; `updated` is the constant `1`. No `random`, no time. `assemble()` called twice yields byte-identical JSON.

---

## Excalidraw schema cheat-sheet (reference while implementing)

Top-level document:
```json
{ "type": "excalidraw", "version": 2, "source": "...", "elements": [ ... ], "appState": { "gridSize": 20, "viewBackgroundColor": "#ffffff" }, "files": {} }
```

Every element shares a base shape (the generator fills all of these). A `text` element adds `text` / `fontSize` / `containerId` / `originalText`; an `arrow` adds `points` / `startBinding` / `endBinding` / `endArrowhead`; a `frame` adds `name`. Bound text reciprocity: the container's `boundElements` lists `{"type":"text","id":<textId>}` and the text's `containerId` is the container id. Arrow binding reciprocity: each connected shape's `boundElements` also lists `{"type":"arrow","id":<arrowId>}`.

---

## Task 1: Package scaffold + layout constants + legend palette

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Create the package marker**

Create `tools/__init__.py` with a single docstring line:

```python
"""Developer tooling (re-runnable generators). Not imported by the agent runtime."""
```

- [ ] **Step 2: Write the failing test for constants + palette**

Create `tests/test_gen_excalidraw.py`:

```python
"""Structural tests for the deterministic Excalidraw generator."""
import json

import pytest

import tools.gen_excalidraw as gx


def test_grid_and_gaps_are_positive_and_grid_snapped():
    assert gx.GRID == 20
    # spec: adjacent boxes keep a gap of at least 40px
    assert gx.ROW_GAP >= 40
    assert gx.COL_GAP >= 40
    assert gx.FRAME_PAD >= 40
    # all spacing is a multiple of the grid step (snap is a no-op on them)
    for v in (gx.ROW_GAP, gx.COL_GAP, gx.FRAME_PAD, gx.FRAME_VGAP, gx.NODE_W, gx.NODE_H):
        assert gx.snap(v) == v


def test_palette_covers_every_legend_kind():
    assert set(gx.KIND) == {"llm", "gate", "store", "branch", "terminal"}
    for kind, spec in gx.KIND.items():
        assert spec["shape"] in {"rectangle", "diamond", "ellipse"}
        assert spec["bg"].startswith("#")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.gen_excalidraw'` (or `AttributeError` once the file exists but constants are missing).

- [ ] **Step 4: Write the module header, constants, palette, and `snap`**

Create `tools/gen_excalidraw.py`:

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add tools/__init__.py tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): scaffold deterministic excalidraw generator (constants + palette)"
```

---

## Task 2: Element primitive builders

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing test for the base element + shape builder**

Append to `tests/test_gen_excalidraw.py`:

```python
def test_base_element_has_required_excalidraw_keys():
    e = gx._base("el-1", "rectangle", 0, 0, 240, 60)
    for key in ("id", "type", "x", "y", "width", "height", "angle",
                "strokeColor", "backgroundColor", "fillStyle", "strokeWidth",
                "strokeStyle", "roughness", "opacity", "groupIds", "frameId",
                "roundness", "seed", "version", "versionNonce", "isDeleted",
                "boundElements", "updated", "link", "locked"):
        assert key in e, f"missing base key {key}"
    assert e["isDeleted"] is False
    assert e["updated"] == 1   # constant -> deterministic


def test_stable_seed_is_pure():
    assert gx._stable_seed("el-1") == gx._stable_seed("el-1")
    assert gx._stable_seed("el-1") != gx._stable_seed("el-2")


def test_make_node_emits_shape_and_bound_text_with_reciprocal_refs():
    node = gx.Node(id="d1-x", label="hello", kind="llm")
    shape, text = gx.make_node(node, x=0, y=0, frame_id="frame-1")
    assert shape["type"] == "rectangle"
    assert shape["backgroundColor"] == "#a5d8ff"
    assert text["type"] == "text" and text["text"] == "hello"
    # reciprocity: text -> container, container -> text
    assert text["containerId"] == shape["id"]
    assert {"type": "text", "id": text["id"]} in shape["boundElements"]
    assert shape["frameId"] == "frame-1" and text["frameId"] == "frame-1"


def test_make_node_shapes_match_kind():
    assert gx.make_node(gx.Node("a", "x", "branch"), 0, 0, "f")[0]["type"] == "diamond"
    assert gx.make_node(gx.Node("b", "x", "store"), 0, 0, "f")[0]["type"] == "ellipse"
    term = gx.make_node(gx.Node("c", "x", "terminal"), 0, 0, "f")[0]
    assert term["roundness"] == {"type": 3}


def test_make_arrow_binds_both_ends_and_back_references_shapes():
    a = gx.make_node(gx.Node("src", "A", "gate"), 0, 0, "f")[0]
    b = gx.make_node(gx.Node("dst", "B", "gate"), 0, 200, "f")[0]
    arrows = gx.make_arrow(a, b, dashed=True, label="retry")
    arrow = arrows[0]
    assert arrow["type"] == "arrow"
    assert arrow["strokeStyle"] == "dashed"
    assert arrow["startBinding"]["elementId"] == "src"
    assert arrow["endBinding"]["elementId"] == "dst"
    # connected shapes back-reference the arrow
    assert {"type": "arrow", "id": arrow["id"]} in a["boundElements"]
    assert {"type": "arrow", "id": arrow["id"]} in b["boundElements"]
    # labeled arrow produces a bound label text element
    assert any(el["type"] == "text" and el.get("containerId") == arrow["id"]
               for el in arrows)


def test_frame_builder():
    f = gx._frame("frame-1", 0, 0, 400, 300, "Diagram 1 — x")
    assert f["type"] == "frame"
    assert f["name"] == "Diagram 1 — x"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: FAIL with `AttributeError: module 'tools.gen_excalidraw' has no attribute '_base'`.

- [ ] **Step 3: Implement the builders**

Append to `tools/gen_excalidraw.py`:

```python
# ── Deterministic ids ──────────────────────────────────────────────────────
def _stable_seed(eid: str) -> int:
    """Pure pseudo-seed derived from the element id (no randomness)."""
    h = 2166136261
    for ch in eid:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _base(eid, etype, x, y, w, h, frame_id=None):
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all tests so far green).

- [ ] **Step 5: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): excalidraw element primitives (node/arrow/frame) with bindings"
```

---

## Task 3: Declarative layout engine (`render_diagram`)

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing test for `render_diagram`**

Append to `tests/test_gen_excalidraw.py`:

```python
def _bbox(e):
    return e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]


def _overlap(a, b):
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def test_render_diagram_wraps_nodes_in_frame_and_returns_bottom():
    d = gx.Diagram(
        name="Diagram T — test",
        rows=[[gx.Node("t-a", "A", "gate")],
              [gx.Node("t-b", "B", "llm"), gx.Node("t-c", "C", "store")]],
        edges=[gx.Edge("t-a", "t-b")],
    )
    elems, bottom = gx.render_diagram(d, origin_y=0, frame_id="frame-T")
    frame = next(e for e in elems if e["type"] == "frame")
    shapes = [e for e in elems if e["type"] in ("rectangle", "diamond", "ellipse")]
    # every node shape sits fully inside the frame box
    fx0, fy0, fx1, fy1 = _bbox(frame)
    for s in shapes:
        sx0, sy0, sx1, sy1 = _bbox(s)
        assert fx0 <= sx0 and sx1 <= fx1 and fy0 <= sy0 and sy1 <= fy1
    # no two node shapes overlap
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert not _overlap(shapes[i], shapes[j])
    assert bottom == frame["y"] + frame["height"]


def test_render_diagram_frame_first_in_array():
    d = gx.Diagram("D", rows=[[gx.Node("z", "Z", "gate")]], edges=[])
    elems, _ = gx.render_diagram(d, 0, "frame-Z")
    assert elems[0]["type"] == "frame"   # drawn behind its children
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py::test_render_diagram_wraps_nodes_in_frame_and_returns_bottom -v`
Expected: FAIL with `AttributeError: ... has no attribute 'Diagram'`.

- [ ] **Step 3: Implement `Diagram` + `render_diagram`**

Append to `tools/gen_excalidraw.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): declarative layout engine (rows -> framed, bbox-derived)"
```

---

## Task 4: Document envelope + integrity helpers

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing test for the envelope + integrity helpers**

Append to `tests/test_gen_excalidraw.py`:

```python
def test_build_document_envelope():
    d = gx.Diagram("D", rows=[[gx.Node("only", "X", "llm")]], edges=[])
    elems, _ = gx.render_diagram(d, 0, "frame-1")
    doc = gx.build_document(elems)
    assert doc["type"] == "excalidraw"
    assert doc["version"] == 2
    assert isinstance(doc["elements"], list) and doc["elements"]
    assert "appState" in doc
    # serializes as valid JSON
    json.loads(json.dumps(doc))


def test_unique_ids_helper():
    good = {"elements": [{"id": "a"}, {"id": "b"}]}
    bad = {"elements": [{"id": "a"}, {"id": "a"}]}
    assert gx.unique_ids(good) is True
    assert gx.unique_ids(bad) is False


def test_arrow_bindings_valid_helper():
    a = gx.make_node(gx.Node("s", "A", "gate"), 0, 0, "f")[0]
    b = gx.make_node(gx.Node("d", "B", "gate"), 0, 200, "f")[0]
    arrow = gx.make_arrow(a, b)[0]
    ok = {"elements": [a, b, arrow]}
    assert gx.arrow_bindings_valid(ok) is True
    arrow_bad = dict(arrow, startBinding={"elementId": "ghost", "focus": 0, "gap": 8})
    assert gx.arrow_bindings_valid({"elements": [a, b, arrow_bad]}) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py::test_build_document_envelope -v`
Expected: FAIL with `AttributeError: ... has no attribute 'build_document'`.

- [ ] **Step 3: Implement the envelope + helpers**

Append to `tools/gen_excalidraw.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): excalidraw document envelope + integrity helpers"
```

---

## Task 5: Diagram 1 — end-to-end flow (harness → pipeline)

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing test for `diagram1`**

Append to `tests/test_gen_excalidraw.py`:

```python
def test_diagram1_structure():
    d = gx.diagram1()
    assert isinstance(d, gx.Diagram)
    assert "End-to-end" in d.name
    ids = {n.id for row in d.rows for n in row}
    # every edge references nodes that exist in the diagram (no cross-diagram leak)
    for e in d.edges:
        assert e.src in ids and e.dst in ids
    # the training feedback edge is dashed
    assert any(e.dashed for e in d.edges)
    # prephase is expanded into sub-steps
    assert {"d1-schema", "d1-samples", "d1-docs", "d1-deepread"} <= ids
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py::test_diagram1_structure -v`
Expected: FAIL with `AttributeError: ... has no attribute 'diagram1'`.

- [ ] **Step 3: Implement `diagram1`**

Append to `tools/gen_excalidraw.py`:

```python
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
        # all four prephase facts converge into run_pipeline
        Edge("d1-schema", "d1-pipeline"),
        Edge("d1-samples", "d1-pipeline"),
        Edge("d1-docs", "d1-pipeline"),
        Edge("d1-deepread", "d1-pipeline"),
        Edge("d1-pipeline", "d1-branch"),
        # EndTrial is per-trial; SubmitRun runs once after the pool closes
        Edge("d1-branch", "d1-endtrial"),
        Edge("d1-endtrial", "d1-submit"),
        Edge("d1-submit", "d1-learn"),
        # dashed training-loop feedback: distil grader feedback, re-run next cycle
        Edge("d1-learn", "d1-start", dashed=True, label="TRAIN_MAX_CYCLES"),
    ]
    return Diagram("Diagram 1 — End-to-end flow (harness -> pipeline)", rows, edges)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): diagram 1 — end-to-end harness->pipeline flow"
```

---

## Task 6: Diagram 2 — legacy pipeline loop + gates

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing test for `diagram2`**

Append to `tests/test_gen_excalidraw.py`:

```python
def test_diagram2_structure():
    d = gx.diagram2()
    assert "loop" in d.name.lower()
    ids = {n.id for row in d.rows for n in row}
    for e in d.edges:
        assert e.src in ids and e.dst in ids
    # the four in-loop gates are present
    assert {"d2-codegen", "d2-lint", "d2-retry", "d2-fidelity"} <= ids
    # three terminal outcomes
    kinds = {n.id: n.kind for row in d.rows for n in row}
    terminals = [i for i, k in kinds.items() if k == "terminal"]
    assert len(terminals) >= 3
    # LEARN feedback edges are dashed
    assert any(e.dashed and e.dst == "d2-learn" for e in d.edges)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py::test_diagram2_structure -v`
Expected: FAIL with `AttributeError: ... has no attribute 'diagram2'`.

- [ ] **Step 3: Implement `diagram2`**

Append to `tools/gen_excalidraw.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): diagram 2 — legacy pipeline loop + gates"
```

---

## Task 7: Diagram 3 — deterministic interpreter branch

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing test for `diagram3`**

Append to `tests/test_gen_excalidraw.py`:

```python
def test_diagram3_structure():
    d = gx.diagram3()
    assert "interpreter" in d.name.lower()
    ids = {n.id for row in d.rows for n in row}
    for e in d.edges:
        assert e.src in ids and e.dst in ids
    # Plan-IR path landmarks
    assert {"d3-planir", "d3-lint", "d3-interpret", "d3-captured"} <= ids
    # no free-form CODEGEN retry loop: interpret is a deterministic (grey) gate
    kinds = {n.id: n.kind for row in d.rows for n in row}
    assert kinds["d3-interpret"] == "gate"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py::test_diagram3_structure -v`
Expected: FAIL with `AttributeError: ... has no attribute 'diagram3'`.

- [ ] **Step 3: Implement `diagram3`**

Append to `tools/gen_excalidraw.py`:

```python
def diagram3() -> Diagram:
    """INTERPRETER_ENABLED branch: INTENT/PLAN -> lint -> deterministic interpret."""
    rows = [
        [Node("d3-deepread", "prephase facts + deep_read", "gate")],
        [Node("d3-intent", "run_intent (LLM -> IntentSpec)", "llm")],
        [Node("d3-plan", "run_plan (LLM -> PlanIR)", "llm")],
        [Node("d3-planir", "PlanIR (run_plan output)", "gate")],
        [Node("d3-lint", "lint_security_first", "gate")],
        [Node("d3-interpret", "interpret() — no LLM in loop", "gate")],
        [Node("d3-captured", "CapturedAnswer", "gate")],
        [Node("d3-ok", "OUTCOME_OK", "terminal"),
         Node("d3-clar", "OUTCOME_NONE_CLARIFICATION", "terminal"),
         Node("d3-unsupported", "OUTCOME_NONE_UNSUPPORTED", "terminal"),
         Node("d3-deny", "OUTCOME_DENIED_SECURITY", "terminal")],
    ]
    edges = [
        Edge("d3-deepread", "d3-intent"),
        Edge("d3-intent", "d3-plan"),
        Edge("d3-plan", "d3-planir"),
        Edge("d3-planir", "d3-lint"),
        Edge("d3-lint", "d3-interpret"),
        Edge("d3-interpret", "d3-captured"),
        # CapturedAnswer carries the plan-chosen outcome; verify() forwards it
        Edge("d3-captured", "d3-ok"),
        Edge("d3-captured", "d3-clar"),
        Edge("d3-captured", "d3-unsupported"),
        Edge("d3-captured", "d3-deny"),
        Edge("d3-interpret", "d3-plan", dashed=True, label="re-plan next cycle"),
    ]
    return Diagram("Diagram 3 — Deterministic interpreter (INTERPRETER_ENABLED)", rows, edges)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): diagram 3 — deterministic interpreter branch"
```

---

## Task 8: Diagram 4 + legend

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing test for `diagram4` + `legend`**

Append to `tests/test_gen_excalidraw.py`:

```python
def test_diagram4_structure():
    d = gx.diagram4()
    assert "cross-cutting" in d.name.lower()
    ids = {n.id for row in d.rows for n in row}
    for e in d.edges:
        assert e.src in ids and e.dst in ids
    # three subsystems each have a storage node
    kinds = {n.id: n.kind for row in d.rows for n in row}
    assert sum(1 for k in kinds.values() if k == "store") >= 3


def test_legend_covers_all_five_kinds():
    d = gx.legend()
    assert "Legend" in d.name
    kinds = {n.kind for row in d.rows for n in row}
    assert {"llm", "gate", "store", "branch", "terminal"} <= kinds
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py::test_legend_covers_all_five_kinds -v`
Expected: FAIL with `AttributeError: ... has no attribute 'legend'`.

- [ ] **Step 3: Implement `diagram4` + `legend`**

Append to `tools/gen_excalidraw.py`:

```python
def diagram4() -> Diagram:
    """Cross-cutting subsystems: LEARN store, knowledge oracle, LLM routing."""
    rows = [
        [Node("d4-learn", "LEARN phase (pipeline.py)", "llm"),
         Node("d4-oracle", "Knowledge oracle (oracle.py)", "llm"),
         Node("d4-route", "LLM routing (llm.py)", "gate")],
        [Node("d4-yaml", "data/learned/{tid}.yaml", "store"),
         Node("d4-atoms", "data/oracle/atoms.yaml", "store"),
         Node("d4-trace", "trace JSONL (trace.py)", "store")],
        [Node("d4-pipeline", "pipeline (CODEGEN / interpret)", "gate")],
    ]
    edges = [
        Edge("d4-learn", "d4-yaml"),
        Edge("d4-oracle", "d4-atoms"),
        Edge("d4-route", "d4-trace"),
        Edge("d4-yaml", "d4-pipeline", dashed=True, label="active rules"),
        Edge("d4-atoms", "d4-pipeline", dashed=True, label="K atoms"),
        Edge("d4-route", "d4-pipeline", label="tier + fallback"),
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py
git commit -m "feat(docs): diagram 4 cross-cutting subsystems + legend strip"
```

---

## Task 9: Assemble canvas + `main()` writer + generate the file

**Files:**
- Modify: `tools/gen_excalidraw.py`
- Test: `tests/test_gen_excalidraw.py`
- Generate: `docs/architecture/agent-architecture.excalidraw`

- [ ] **Step 1: Write the failing test for `assemble` + determinism + writer**

Append to `tests/test_gen_excalidraw.py`:

```python
def test_assemble_has_five_frames_and_valid_bindings():
    doc = gx.assemble()
    frame_names = [e["name"] for e in doc["elements"] if e["type"] == "frame"]
    assert len(frame_names) == 5                       # 4 diagrams + legend
    assert any("Diagram 1" in n for n in frame_names)
    assert any("Diagram 4" in n for n in frame_names)
    assert any("Legend" in n for n in frame_names)
    assert gx.unique_ids(doc)
    assert gx.arrow_bindings_valid(doc)


def test_assemble_is_deterministic():
    a = json.dumps(gx.assemble(), sort_keys=True)
    b = json.dumps(gx.assemble(), sort_keys=True)
    assert a == b


def test_main_writes_parseable_file(tmp_path):
    out = tmp_path / "out.excalidraw"
    gx.main(out=out)
    doc = json.loads(out.read_text())
    assert doc["type"] == "excalidraw" and doc["elements"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_gen_excalidraw.py::test_assemble_has_five_frames_and_valid_bindings -v`
Expected: FAIL with `AttributeError: ... has no attribute 'assemble'`.

- [ ] **Step 3: Implement `assemble` + `main` + the `__main__` guard**

Append to `tools/gen_excalidraw.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all green).

- [ ] **Step 5: Generate the committed canvas**

Run: `uv run python tools/gen_excalidraw.py`
Expected stdout: `wrote .../docs/architecture/agent-architecture.excalidraw`

Verify it parses and reports element/frame counts:

Run: `uv run python -c "import json,pathlib; d=json.loads(pathlib.Path('docs/architecture/agent-architecture.excalidraw').read_text()); print('elements', len(d['elements']), 'frames', sum(1 for e in d['elements'] if e['type']=='frame'))"`
Expected: `elements <N> frames 5`

- [ ] **Step 6: Commit**

```bash
git add tools/gen_excalidraw.py tests/test_gen_excalidraw.py docs/architecture/agent-architecture.excalidraw
git commit -m "feat(docs): assemble + generate agent-architecture.excalidraw canvas"
```

---

## Task 10: Measurable layout verification test

This task encodes the spec's "Layout quality is measurable" rules as a single end-to-end test over the assembled document. It is separate from the per-builder tests so a layout regression fails loudly with a clear message.

**Files:**
- Test: `tests/test_gen_excalidraw.py`

- [ ] **Step 1: Write the failing layout-rule test**

Append to `tests/test_gen_excalidraw.py`:

```python
def _shapes_by_frame(doc):
    """Map frameId -> list of node shape elements (excludes text, arrows, frames)."""
    out = {}
    for e in doc["elements"]:
        if e["type"] in ("rectangle", "diamond", "ellipse") and e.get("frameId"):
            out.setdefault(e["frameId"], []).append(e)
    return out


def _gap(a, b):
    """Minimum axis gap between two non-overlapping boxes (0 if they touch/overlap)."""
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    dx = max(bx0 - ax1, ax0 - bx1)   # >0 if separated on x
    dy = max(by0 - ay1, ay0 - by1)   # >0 if separated on y
    return max(dx, dy)


def test_layout_no_overlap_and_min_gap_within_frame():
    doc = gx.assemble()
    for fid, shapes in _shapes_by_frame(doc).items():
        for i in range(len(shapes)):
            for j in range(i + 1, len(shapes)):
                a, b = shapes[i], shapes[j]
                assert not _overlap(a, b), f"{a['id']} overlaps {b['id']} in {fid}"
                assert _gap(a, b) >= 40, f"{a['id']}/{b['id']} gap < 40 in {fid}"


def test_layout_everything_grid_snapped():
    doc = gx.assemble()
    for e in doc["elements"]:
        for key in ("x", "y"):
            assert e[key] == gx.snap(e[key]), f"{e['id']}.{key} not grid-snapped"


def test_layout_nodes_inside_their_frame():
    doc = gx.assemble()
    frames = {e["id"]: e for e in doc["elements"] if e["type"] == "frame"}
    for fid, shapes in _shapes_by_frame(doc).items():
        fx0, fy0, fx1, fy1 = _bbox(frames[fid])
        for s in shapes:
            sx0, sy0, sx1, sy1 = _bbox(s)
            assert fx0 <= sx0 and sx1 <= fx1, f"{s['id']} exceeds frame {fid} on x"
            assert fy0 <= sy0 and sy1 <= fy1, f"{s['id']} exceeds frame {fid} on y"


def test_layout_arrows_do_not_cross_frames_unless_labeled():
    doc = gx.assemble()
    shape_frame = {e["id"]: e.get("frameId")
                   for e in doc["elements"]
                   if e["type"] in ("rectangle", "diamond", "ellipse")}
    labeled = set()
    for e in doc["elements"]:
        if e["type"] == "text" and e.get("containerId", "").startswith("e-"):
            labeled.add(e["containerId"])
    for e in doc["elements"]:
        if e["type"] != "arrow":
            continue
        sf = shape_frame.get(e["startBinding"]["elementId"])
        ef = shape_frame.get(e["endBinding"]["elementId"])
        if sf != ef:
            assert e["id"] in labeled, f"unlabeled cross-frame arrow {e['id']}"
```

- [ ] **Step 2: Run the layout tests**

Run: `uv run pytest tests/test_gen_excalidraw.py -k layout -v`
Expected: PASS (4 layout tests). If any FAIL, the message names the offending element ids — adjust `ROW_GAP`/`COL_GAP`/`FRAME_PAD` or node sizing in `tools/gen_excalidraw.py` (re-run `python tools/gen_excalidraw.py` afterward to refresh the committed canvas) until green. Do not weaken the thresholds in the test.

- [ ] **Step 3: Run the full generator suite**

Run: `uv run pytest tests/test_gen_excalidraw.py -v`
Expected: PASS (all tests green).

- [ ] **Step 4: Regenerate the canvas if any constant changed, then commit**

```bash
uv run python tools/gen_excalidraw.py
git add tests/test_gen_excalidraw.py docs/architecture/agent-architecture.excalidraw
git commit -m "test(docs): enforce measurable excalidraw layout rules"
```

---

## Task 11: Markdown companion guide

**Files:**
- Create: `docs/architecture/agent-architecture-guide.md`

The `file:line` references below were captured against the working tree on 2026-06-15. Task 12 adds a test that fails if any drift; if any reference is stale at implementation time, fix the number in the guide before that test runs (do not change the test).

- [ ] **Step 1: Write the full guide**

Create `docs/architecture/agent-architecture-guide.md`:

```markdown
# Agent Architecture Guide

Dense, reference-style companion to `agent-architecture.excalidraw`. One section
per diagram region on the canvas, plus a shape legend and a module map. Audience:
project developers who already know the domain. References are `path:line` into
the working tree; regenerate the canvas with `uv run python tools/gen_excalidraw.py`
when the architecture changes.

## Overview

Each benchmark task runs `main.py` harness → `agent/orchestrator.py:run_agent`
→ `agent/pipeline.py:run_pipeline`, which forks on `INTERPRETER_ENABLED` between
the legacy DESIGN→CODEGEN loop (Diagram 2) and the deterministic Plan-IR
interpreter (Diagram 3). LLM-call budget per task: **1** (hard-stop), **2** (best
happy path), **7** (worst, `MAX_STEPS=3`).

## Diagram 1 — End-to-end flow (harness → pipeline)

The harness drives a `StartRun → trials-loop → SubmitRun → EndTrial` cycle; the
`TRAIN_MAX_CYCLES` outer training loop feeds grader feedback back through
`learn_from_grader` (dashed edge). The orchestrator opens the VM, reads
`/AGENTS.MD`, and gathers pre-phase facts (schema, sample rows, docs inventory,
learned deep-read paths) before dispatching the pipeline.

- `main.py:286` — `main()` entry; training loop at `main.py:306`, `TRAIN_MAX_CYCLES` at `main.py:109`
- `main.py:241` — `run_once`: `StartRun` at `main.py:245`, `SubmitRun` at `main.py:280`, `EndTrial` at `main.py:141`
- `main.py:326` — `learn_from_grader` call between cycles
- `agent/orchestrator.py:548` — `run_agent`; reads `/AGENTS.MD` at `agent/orchestrator.py:21`
- `agent/orchestrator.py:393` — `gather_prephase_facts`
- `agent/orchestrator.py:112` — `_discover_schema`; sample rows at `agent/orchestrator.py:130`; relevance gate at `agent/orchestrator.py:153`
- `agent/orchestrator.py:404` — learned `prephase_deep_read` load; docs inventory at `agent/orchestrator.py:440`
- `agent/pipeline.py:928` — `run_pipeline`; branch on `INTERPRETER_ENABLED` at `agent/pipeline.py:943`

## Diagram 2 — Pipeline loop + gates (legacy, default branch)

`DESIGN` is a single frozen LLM call; `outcome_override` short-circuits to a
terminal answer. The loop (`cycle = 1..MAX_STEPS`) runs CODEGEN, then three gates
— AST lint, `check_retry_loop`, fidelity (subprocess) — before the terminal
`ANSWER` one-shot via `_AnswerGuard`. Gate failures route through
`LEARN + CONSOLIDATE` (dashed) into the next cycle.

- `agent/pipeline.py:973` — DESIGN call; `outcome_override` exit at `agent/pipeline.py:1010`
- `agent/pipeline.py:1052` — CODEGEN + ANSWER retry loop (`MAX_STEPS` counter)
- `agent/pipeline.py:1073` — AST lint (`ast.parse`)
- `agent/pipeline.py:1096` — `check_retry_loop` break
- `agent/pipeline.py:1102` — `generate_fidelity_test`; subprocess exec at `agent/pipeline.py:1103`
- `agent/fidelity.py:52` — `generate_fidelity_test`; `agent/fidelity.py:90` — `exec_fidelity_in_subprocess`
- `agent/pipeline.py:676` — `_AnswerGuard` terminal one-shot proxy
- `agent/pipeline.py:271` — `_learn_consolidate` (LEARN + CONSOLIDATE)

## Diagram 3 — Deterministic interpreter (INTERPRETER_ENABLED)

The interpreter branch emits *data*, not code: `run_intent` → `run_plan` build a
`PlanIR`, which is linted security-first and then executed by a deterministic
`interpret()` (no LLM inside the loop). The result is a `CapturedAnswer` the
pipeline submits after verification.

- `agent/pipeline.py:338` — `_run_interpreted`; dispatched from `agent/pipeline.py:944`
- `agent/reason.py:60` — `run_intent`; `agent/reason.py:77` — `run_plan`
- `agent/ir_models.py:81` — `IntentSpec`; `agent/ir_models.py:171` — `PlanIR`
- `agent/interpreter.py:191` — `lint_security_first`
- `agent/interpreter.py:209` — `interpret`; `agent/interpreter.py:53` — `CapturedAnswer`

## Diagram 4 — Cross-cutting subsystems

- **LEARN / learned_store** → `data/learned/{tid}.yaml` (active rules + `prephase_deep_read` + `last_run`): `agent/learned_store.py:64` `load_entries`, `agent/learned_store.py:79` `apply_learn_diff`, `agent/learned_store.py:113` `save_last_run`, `agent/learned_store.py:147` `load_prephase_deep_read`
- **Knowledge oracle** (`agent/oracle.py:90` `retrieve`): cosine top-N at `agent/oracle.py:63` → LLM re-rank → K atoms injected into CODEGEN; bank at `data/oracle/atoms.yaml`
- **LLM routing** (`agent/llm.py:529` `call_llm_raw`): tiers anthropic / openrouter / ollama / claude-code (`agent/llm.py:270`) with `MODEL_FALLBACK` (`agent/llm.py:250`), driven by `models.json`; trace JSONL via `agent/trace.py:43` `TraceLogger` (`agent/trace.py:90` `log_llm_call`)

## Legend

| Shape / color | Meaning |
|---------------|---------|
| Blue rectangle | LLM call (DESIGN / CODEGEN / LEARN / oracle re-rank) |
| Grey rectangle | Deterministic step / gate (AST lint, retry-guard, fidelity, interpret) |
| Green ellipse | Storage (yaml / json / atoms) — the spec's "cylinder", rendered as a single-primitive ellipse |
| Yellow diamond | Branch / condition |
| Red rounded rectangle | Terminal outcome |
| Solid arrow | Control flow |
| Dashed arrow | Feedback / learning (LEARN, training loop) |

## Where to change what

| Module | Responsibility |
|--------|----------------|
| `main.py` | Harness driver; training loop (`TRAIN_MAX_CYCLES`) |
| `agent/orchestrator.py` | VM open, `/AGENTS.MD` read, pre-phase fact gathering |
| `agent/pipeline.py` | DESIGN, CODEGEN loop + gates, `_AnswerGuard`, interpreter dispatch, `learn_from_grader` |
| `agent/reason.py` + `agent/ir_models.py` + `agent/interpreter.py` | Plan-IR branch (INTENT/PLAN → lint → interpret) |
| `agent/fidelity.py` | Fidelity gate test generation + subprocess exec |
| `agent/learned_store.py` | Per-task learned rules + `prephase_deep_read` + `last_run` |
| `agent/oracle.py` | Knowledge-atom retrieval (cosine → re-rank → inject) |
| `agent/llm.py` + `agent/trace.py` + `models.json` | Provider routing, fallback, JSONL traces |
| `data/prompts/*.md` | Phase guides (general structural rules only — never task-specific) |
```

- [ ] **Step 2: Sanity-check the guide renders and references look right**

Run: `uv run python -c "import pathlib; print(pathlib.Path('docs/architecture/agent-architecture-guide.md').read_text()[:200])"`
Expected: prints the guide header.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/agent-architecture-guide.md
git commit -m "docs(architecture): markdown companion guide with file:line refs"
```

---

## Task 12: `file:line` reference-resolution test + final verification

**Files:**
- Test: `tests/test_architecture_guide_refs.py`

- [ ] **Step 1: Write the failing ref-resolution test**

Create `tests/test_architecture_guide_refs.py`:

```python
"""Verify every `path:line` reference in the architecture guide resolves."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "architecture" / "agent-architecture-guide.md"

# matches `agent/pipeline.py:928` and `agent/pipeline.py:1052-1098` inside backticks
REF = re.compile(r"`([\w./]+\.py):(\d+)(?:-(\d+))?`")


def _refs():
    text = GUIDE.read_text(encoding="utf-8")
    for m in REF.finditer(text):
        path, lo, hi = m.group(1), int(m.group(2)), m.group(3)
        yield path, lo, int(hi) if hi else lo


def test_guide_exists():
    assert GUIDE.exists()


def test_every_reference_resolves():
    missing = []
    for path, lo, hi in _refs():
        f = ROOT / path
        if not f.exists():
            missing.append(f"{path} (no such file)")
            continue
        n = len(f.read_text(encoding="utf-8").splitlines())
        if hi > n:
            missing.append(f"{path}:{hi} exceeds file length {n}")
    assert not missing, "stale references:\n" + "\n".join(missing)


def test_guide_has_some_references():
    assert sum(1 for _ in _refs()) >= 20   # guard against an empty/garbled guide
```

- [ ] **Step 2: Run the ref-resolution test**

Run: `uv run pytest tests/test_architecture_guide_refs.py -v`
Expected: PASS. If `test_every_reference_resolves` FAILS, it lists each stale `path:line`; fix those numbers in `docs/architecture/agent-architecture-guide.md` (the code has moved since 2026-06-15) and re-run. Do not relax the test.

- [ ] **Step 3: Run the entire suite to confirm no regressions**

Run: `uv run pytest tests/test_gen_excalidraw.py tests/test_architecture_guide_refs.py -v`
Expected: PASS (all generator + guide tests green).

- [ ] **Step 4: Final spec verification — confirm all five deliverables**

Run:
```bash
uv run python tools/gen_excalidraw.py
uv run python -c "import json,pathlib; d=json.loads(pathlib.Path('docs/architecture/agent-architecture.excalidraw').read_text()); assert d['type']=='excalidraw' and d['version']==2; ids=[e['id'] for e in d['elements']]; assert len(ids)==len(set(ids)); frames=[e['name'] for e in d['elements'] if e['type']=='frame']; print('OK frames:', frames)"
```
Expected: `OK frames: ['Diagram 1 — ...', 'Diagram 2 — ...', 'Diagram 3 — ...', 'Diagram 4 — ...', 'Legend']`

- [ ] **Step 5: Commit**

```bash
git add tests/test_architecture_guide_refs.py docs/architecture/agent-architecture.excalidraw
git commit -m "test(docs): verify architecture guide file:line references resolve"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Excalidraw canvas, 4 frames + legend → Tasks 5–9, verified Task 9/10.
- `tools/gen_excalidraw.py` deterministic, re-runnable, schema-valid → Tasks 1–4, 9; determinism test Task 9.
- Markdown guide (overview + LLM budget, per-diagram sections, legend, module map) → Task 11.
- Schema check (`type`/`version`/`elements`/unique ids/valid arrow bindings) → Tasks 4, 9, 12.
- Every `file:line` resolves → Task 12.
- Measurable layout (no overlap, ≥40px gap, grid-snap, in-frame, labeled cross-frame arrows) → Task 10.

**Placeholder scan:** No "TBD"/"add appropriate"/"similar to". Every code step shows complete code.

**Type consistency:** `Node(id,label,kind)`, `Edge(src,dst,dashed,label)`, `Diagram(name,rows,edges)`, `make_node→(shape,text)`, `make_arrow→list[dict]`, `render_diagram→(elements,bottom)`, `build_document→dict`, `assemble→dict`, `main(out=...)→Path` used consistently across all tasks. KIND keys `{llm,gate,store,branch,terminal}` match diagrams, legend, and tests. Frame ids `frame-1..5` match `assemble`.
