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
    assert gx._stable_seed("el-1") == 4265279278   # pins FNV-1a, guards byte-identical output


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
    assert f.get("frameId") is None


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


# ---------------------------------------------------------------------------
# Task 10: Measurable layout verification tests
# ---------------------------------------------------------------------------

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
