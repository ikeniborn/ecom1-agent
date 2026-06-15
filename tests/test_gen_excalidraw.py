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
