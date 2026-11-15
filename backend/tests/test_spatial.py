import math

import pytest

from app.services.capacity import capacity
from app.services.geometry import Rect, door_access_zone, front_aisle
from app.services.grid import compute_cells, grid_dimensions, grid_to_physical, physical_to_grid
from app.services.layout import RackConfig, RackIn, generate_layouts, validate_layout
from app.services.spatial import build_context
from app.services.units import from_m, to_m

FT = 0.3048


# ------------------------------------------------------------------ units
@pytest.mark.parametrize("v,u,m", [(1, "ft", 0.3048), (12, "in", 0.3048), (100, "cm", 1.0), (2.5, "m", 2.5)])
def test_unit_conversion(v, u, m):
    assert to_m(v, u) == pytest.approx(m)
    assert from_m(m, u) == pytest.approx(v)


def test_unit_rejects_unknown():
    with pytest.raises(ValueError):
        to_m(1, "yd")


# ------------------------------------------------------------------ grid
def test_grid_reference_room_80_cells():
    g = grid_dimensions(to_m(10, "ft"), to_m(8, "ft"), to_m(1, "ft"))
    assert (g["columns"], g["rows"], g["full_cells"]) == (10, 8, 80)
    assert g["remainder_x_m"] == pytest.approx(0, abs=1e-6)


def test_grid_partial_edges_not_counted():
    g = grid_dimensions(3.5, 2.2, 1.0)
    assert (g["columns"], g["rows"], g["full_cells"]) == (3, 2, 6)
    assert g["remainder_x_m"] == pytest.approx(0.5)
    assert g["remainder_y_m"] == pytest.approx(0.2)


def test_grid_invalid_cell():
    with pytest.raises(ValueError):
        grid_dimensions(3, 3, 0)


def test_grid_coordinate_mapping_roundtrip():
    x, y = grid_to_physical(2, 5, 0.5)
    assert (x, y) == (2.75, 1.25)
    assert physical_to_grid(x, y, 0.5) == (2, 5)


def test_obstacle_mapping_to_cells():
    ctx = build_context(3.0, 2.0, 2.5, [{"kind": "PILLAR", "x": 1.0, "y": 0.5, "w": 0.5, "d": 0.5, "id": 1},
                                        {"kind": "RESTRICTED", "x": 0, "y": 1.5, "w": 0.5, "d": 0.5, "id": 2}])
    g = compute_cells(ctx, 0.5)
    assert g["states"][1][2] == "OBSTACLE"   # cell (row 1, col 2) = x 1.0–1.5, y 0.5–1.0
    assert g["states"][3][0] == "RESTRICTED"
    assert g["counts"]["OBSTACLE"] == 1 and g["counts"]["FREE"] == 22


def test_partially_overlapping_obstacle_marks_every_touched_cell():
    ctx = build_context(2.0, 2.0, 2.5, [{"kind": "PILLAR", "x": 0.4, "y": 0.4, "w": 0.2, "d": 0.2, "id": 1}])
    g = compute_cells(ctx, 0.5)
    assert g["counts"]["OBSTACLE"] == 4


def test_unconfirmed_obstacle_is_uncertain():
    ctx = build_context(2.0, 2.0, 2.5, [{"kind": "FURNITURE", "x": 0, "y": 0, "w": 0.5, "d": 0.5, "id": 1, "confirmed": False}])
    assert compute_cells(ctx, 0.5)["states"][0][0] == "UNCERTAIN"


# ------------------------------------------------------------------ geometry
def test_rect_collision_and_touching():
    a = Rect(0, 0, 1, 1)
    assert a.intersects(Rect(0.5, 0.5, 1, 1))
    assert not a.intersects(Rect(1, 0, 1, 1))  # touching edge is not overlap
    assert a.gap_to(Rect(1.3, 0, 1, 1)) == pytest.approx(0.3)
    assert a.gap_to(Rect(1.3, 1.4, 1, 1)) == pytest.approx(0.5)


def test_door_zone_extends_into_room():
    room = Rect(0, 0, 3, 2)
    z = door_access_zone(Rect(1, 0, 0.8, 0.05), 0.9, room)
    assert (z.y, z.d) == (0, pytest.approx(0.95))
    z = door_access_zone(Rect(2.95, 0.5, 0.05, 0.8), 0.9, room)
    assert z.x == pytest.approx(2.05) and z.x2 == pytest.approx(3.0)


def test_front_aisle():
    a = front_aisle(Rect(0, 0, 1.2, 0.45), "S", 0.75)
    assert (a.y, a.d, a.w) == (0.45, 0.75, 1.2)


# ------------------------------------------------------------------ validation
def ctx_ref(extra=()):
    return build_context(10 * FT, 8 * FT, 9 * FT, [{"kind": "DOOR", "x": 1.2, "y": 0, "w": 0.8, "d": 0.05, "clearance_m": 0.8,
                                                    "id": 1, "label": "Door"}, *extra])


CFG = RackConfig()


def codes(res):
    return {v["code"] for v in res.violations}


def test_valid_single_rack():
    res = validate_layout(ctx_ref(), CFG, [RackIn("R1", 0, 2.438 - 0.45, 1.2, 0.45)])
    assert res.valid, res.violations
    assert res.aisles["R1"]["side"] == "N"


def test_rack_out_of_bounds():
    assert "OUT_OF_BOUNDS" in codes(validate_layout(ctx_ref(), CFG, [RackIn("R1", 2.5, 1.9, 1.2, 0.45)]))


def test_rack_overlap():
    res = validate_layout(ctx_ref(), CFG, [RackIn("R1", 0, 1.98, 1.2, 0.45), RackIn("R2", 0.5, 1.98, 1.2, 0.45)])
    assert "RACK_OVERLAP" in codes(res)


def test_rack_gap_clearance():
    res = validate_layout(ctx_ref(), CFG, [RackIn("R1", 0, 1.98, 1.2, 0.45), RackIn("R2", 1.21, 1.98, 1.2, 0.45)])
    assert "RACK_CLEARANCE" in codes(res)


def test_door_zone_blocked():
    assert "DOOR_ZONE" in codes(validate_layout(ctx_ref(), CFG, [RackIn("R1", 1.0, 0.3, 1.2, 0.45)]))


def test_obstacle_overlap_and_clearance():
    pillar = {"kind": "PILLAR", "x": 2.0, "y": 1.9, "w": 0.3, "d": 0.3, "id": 2, "label": "Pillar"}
    assert "OBSTACLE_OVERLAP" in codes(validate_layout(ctx_ref([pillar]), CFG, [RackIn("R1", 1.0, 1.98, 1.2, 0.45)]))
    near = validate_layout(ctx_ref([pillar]), CFG, [RackIn("R1", 0.75, 1.98, 1.2, 0.45)])
    assert "OBSTACLE_CLEARANCE" in codes(near)


def test_walkway_required():
    # two racks facing each other with only 0.3 m between them: neither has a 0.75 m aisle on that side,
    # and their other sides are walls / each other
    res = validate_layout(ctx_ref(), RackConfig(walkway_m=2.0), [RackIn("R1", 0, 1.98, 1.2, 0.45)])
    assert "NO_ACCESS_AISLE" in codes(res)


def test_walkway_blocked_by_obstacle():
    box = {"kind": "FURNITURE", "x": 0.0, "y": 1.4, "w": 1.4, "d": 0.4, "id": 3, "label": "Desk"}
    res = validate_layout(ctx_ref([box]), RackConfig(obstacle_clearance_m=0.1), [RackIn("R1", 0, 1.98, 1.2, 0.45)])
    assert "NO_ACCESS_AISLE" in codes(res)


def test_height_constraint():
    res = validate_layout(ctx_ref(), RackConfig(rack_height_m=2.6), [RackIn("R1", 0, 1.98, 1.2, 0.45)])
    assert "HEIGHT" in codes(res)


def test_unreachable_rack():
    # wall of furniture separates the room; rack behind it cannot be reached from the door
    wall = {"kind": "FIXED", "x": 0, "y": 1.0, "w": 10 * FT, "d": 0.1, "id": 4, "label": "Partition"}
    res = validate_layout(ctx_ref([wall]), RackConfig(obstacle_clearance_m=0.05), [RackIn("R1", 0, 1.98, 1.2, 0.45)])
    assert "UNREACHABLE" in codes(res)


def test_footprint_must_match_config():
    assert "FOOTPRINT_MISMATCH" in codes(validate_layout(ctx_ref(), CFG, [RackIn("R1", 0, 1.9, 1.0, 0.45)]))


# ------------------------------------------------------------------ generation
def test_generated_layouts_are_valid_and_ranked():
    out = generate_layouts(ctx_ref([{"kind": "PILLAR", "x": 2.7, "y": 2.0, "w": 0.3, "d": 0.3, "id": 2, "label": "Pillar"}]), CFG)
    assert out["feasible"] and out["options"]
    scores = [o["score"] for o in out["options"]]
    assert scores == sorted(scores, reverse=True)
    for o in out["options"]:
        assert o["validation"]["valid"]
        racks = [RackIn(**r) for r in o["racks"]]
        assert validate_layout(ctx_ref([{"kind": "PILLAR", "x": 2.7, "y": 2.0, "w": 0.3, "d": 0.3, "id": 2}]), CFG, racks).valid


def test_max_racks_respected():
    out = generate_layouts(ctx_ref(), RackConfig(max_racks=1))
    assert all(o["metrics"]["rack_count"] == 1 for o in out["options"])


def test_infeasible_room_is_explained():
    ctx = build_context(1.0, 1.0, 2.5, [])
    out = generate_layouts(ctx, RackConfig())
    assert not out["feasible"] and out["options"] == []
    assert any("Rack length" in d["reason"] for d in out["diagnosis"])


def test_infeasible_low_ceiling():
    ctx = build_context(4, 4, 1.5, [])
    out = generate_layouts(ctx, RackConfig())
    assert not out["feasible"]
    assert any("ceiling" in d["reason"] for d in out["diagnosis"])


def test_orientation_restriction():
    out = generate_layouts(ctx_ref(), RackConfig(orientation="Y"))
    assert all(r["rotation"] == 90 for o in out["options"] for r in o["racks"])


def test_config_validation():
    with pytest.raises(ValueError):
        RackConfig.from_dict({"levels": 0})
    with pytest.raises(ValueError):
        RackConfig.from_dict({"levels": 6, "level_gap_m": 0.4, "rack_height_m": 1.8})


# ------------------------------------------------------------------ capacity
def test_capacity_formula():
    crop = {"name": "Lettuce", "spacing_m": 0.2, "mature_height_m": 0.25}
    c = capacity(RackConfig(), 3, crop)
    per_row, per_col = math.floor((1.2 - 0.1) / 0.2), math.floor((0.45 - 0.1) / 0.2)
    assert c["plants_per_level"] == per_row * per_col == 5
    assert c["total"] == 5 * 4 * 3
    assert c["warnings"] == []


def test_capacity_override_and_height_warning():
    c = capacity(RackConfig(plants_per_level=10, levels=5), 2, {"name": "Kale", "spacing_m": 0.3, "mature_height_m": 0.4})
    assert c["total"] == 100
    assert any("Kale" in w for w in c["warnings"])


def test_capacity_needs_spacing():
    c = capacity(RackConfig(), 2, None)
    assert c["total"] is None and c["warnings"]


def test_rack_accessible_if_any_clear_side_is_reachable():
    # partition at y=1.0 seals off the strip next to the north wall; the rack's north walkway is
    # clear but unreachable, its south walkway is reachable -> valid, and the reachable side is chosen
    wall = {"kind": "FIXED", "x": 0, "y": 0.0, "w": 10 * FT, "d": 0.05, "id": 5, "label": "Ledge"}
    door_s = {"kind": "DOOR", "x": 1.5, "y": 8 * FT - 0.05, "w": 0.8, "d": 0.05, "clearance_m": 0.6, "id": 6, "label": "Door"}
    box = {"kind": "FIXED", "x": 1.25, "y": 0.05, "w": 10 * FT - 1.25, "d": 0.85, "id": 7, "label": "Counter"}
    ctx = build_context(10 * FT, 8 * FT, 9 * FT, [wall, door_s, box])
    rk = RackIn("R1", 0.0, 0.9, 1.2, 0.45, access_side="N")  # N side faces a dead-end pocket
    res = validate_layout(ctx, RackConfig(obstacle_clearance_m=0.0), [rk])
    assert res.valid, res.violations
    assert res.aisles["R1"]["side"] == "S"
