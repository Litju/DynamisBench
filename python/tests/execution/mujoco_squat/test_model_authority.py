"""Engine-free qualification of the barbell back-squat model's declared authority and asset.

Nothing here imports MuJoCo. The packaged MJCF is parsed independently and held to the
physical facts in :mod:`tests.execution.mujoco_squat.support`.
"""

from __future__ import annotations

import hashlib
import math
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from importlib.resources import files

import pytest

from dynamisbench.adapters.mujoco.squat import anthropometry, contract, mjcf, stance
from tests.execution.mujoco_squat.support import (
    ATHLETE_MASS_KG,
    BARBELL_MASS_KG,
    DE_LEVA_MALE_MASS_FRACTION,
    GRAVITY_M_S2,
    STATURE_M,
)


def _asset() -> bytes:
    return (
        files("dynamisbench.adapters.mujoco.squat").joinpath(contract.MODEL_ASSET_PATH).read_bytes()
    )


def _root() -> ElementTree.Element:
    return ElementTree.fromstring(_asset())


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(value) for value in text.split())


def _world() -> ElementTree.Element:
    world = _root().find("worldbody")
    assert world is not None
    return world


def _bodies() -> dict[str, ElementTree.Element]:
    return {body.attrib["name"]: body for body in _world().iter("body")}


def _segment_family(body: str) -> str:
    return body[:-2] if body.endswith(("_l", "_r")) else body


# ---------------------------------------------------------------------------------------------
# Mass, geometry and inertia


def test_every_segment_mass_is_the_de_leva_fraction_of_75_kg() -> None:
    assert math.isclose(
        sum(DE_LEVA_MALE_MASS_FRACTION.values()) * 2
        - sum(
            DE_LEVA_MALE_MASS_FRACTION[name]
            for name in ("head", "torso_upper", "torso_middle", "pelvis")
        ),
        1.0,
        abs_tol=1e-12,
    )
    bodies = _bodies()
    athlete = 0.0
    for name, body in bodies.items():
        if name == "barbell":
            continue
        mass = float(body.find("inertial").attrib["mass"])  # type: ignore[union-attr]
        expected = DE_LEVA_MALE_MASS_FRACTION[_segment_family(name)] * ATHLETE_MASS_KG
        assert math.isclose(mass, expected, rel_tol=0, abs_tol=1e-9), name
        athlete += mass
    assert math.isclose(athlete, ATHLETE_MASS_KG, rel_tol=0, abs_tol=1e-9)
    bar = float(bodies["barbell"].find("inertial").attrib["mass"])  # type: ignore[union-attr]
    assert bar == BARBELL_MASS_KG


def test_the_anatomical_zero_posture_is_exactly_the_declared_stature() -> None:
    bodies = _bodies()

    def z(name: str) -> float:
        return _floats(bodies[name].attrib["pos"])[2]

    head_length = 0.2429 * STATURE_M / 1.741  # de Leva VERT-CERV, scaled to stature
    vertex = z("pelvis") + z("torso_middle") + z("torso_upper") + z("head") + head_length
    assert math.isclose(vertex, STATURE_M, rel_tol=0, abs_tol=1e-8)
    ankle = z("pelvis") + z("shank_l") + z("foot_l")
    assert math.isclose(ankle, 0.039 * STATURE_M, rel_tol=0, abs_tol=1e-8)
    for sole in bodies["foot_l"].findall("geom"):
        if sole.attrib.get("class") == "sole":
            bottom = ankle + _floats(sole.attrib["pos"])[2] - float(sole.attrib["size"])
            assert math.isclose(bottom, 0.0, abs_tol=1e-9)


def test_every_inertia_is_physical() -> None:
    for name, body in _bodies().items():
        inertial = body.find("inertial")
        assert inertial is not None, name
        a, b, c = _floats(inertial.attrib["diaginertia"])
        assert min(a, b, c) > 0.0, name
        assert a + b >= c and b + c >= a and a + c >= b, f"{name} violates the triangle inequality"


def test_segment_centres_of_mass_lie_inside_their_segments() -> None:
    lengths = anthropometry.geometry()
    for segment in anthropometry.segment_inertias():
        family = segment.segment
        if family == "foot":
            assert -lengths.heel_offset < segment.com[0] < lengths.foot - lengths.heel_offset
            continue
        length = getattr(lengths, family)
        assert 0.0 < abs(segment.com[2]) < length, segment.body


def test_the_barbell_is_an_iwf_mens_bar() -> None:
    bar = _bodies()["barbell"]
    geoms = {geom.attrib["name"]: geom for geom in bar.findall("geom")}
    shaft_radius, shaft_half = _floats(geoms["bar_shaft"].attrib["size"])
    assert math.isclose(2 * shaft_half, 2.20) and math.isclose(2 * shaft_radius, 0.028)
    sleeve_radius, sleeve_half = _floats(geoms["bar_sleeve_l"].attrib["size"])
    assert math.isclose(2 * sleeve_radius, 0.050) and math.isclose(2 * sleeve_half, 0.415)
    transverse, axial, transverse_2 = _floats(bar.find("inertial").attrib["diaginertia"])  # type: ignore[union-attr]
    assert transverse == transverse_2
    uniform_rod = BARBELL_MASS_KG * 2.20**2 / 12.0
    all_at_sleeves = BARBELL_MASS_KG * 0.8925**2
    assert uniform_rod < transverse < all_at_sleeves
    assert 0.0 < axial < BARBELL_MASS_KG * 0.025**2
    grips = {site.attrib["name"]: _floats(site.attrib["pos"]) for site in bar.findall("site")}
    assert grips["bar_grip_l"][1] == -grips["bar_grip_r"][1] > 0.3


# ---------------------------------------------------------------------------------------------
# Joints and actuators


def test_every_joint_is_limited_actuated_and_left_right_symmetric() -> None:
    joints = {joint.attrib["name"]: joint for joint in _world().iter("joint")}
    actuator_block = _root().find("actuator")
    assert actuator_block is not None
    actuators = {act.attrib["name"]: act for act in actuator_block.iter("general")}
    hinges = [name for name, joint in joints.items() if joint.attrib.get("type") == "hinge"]
    assert len(hinges) == 29
    assert set(hinges) == set(actuators)
    for name in hinges:
        assert "range" in joints[name].attrib, name
        actuator = actuators[name]
        assert actuator.attrib["joint"] == name
        assert actuator.attrib["dyntype"] == "filter"
        assert float(actuator.attrib["dynprm"]) == 0.03
        assert _floats(actuator.attrib["ctrlrange"]) == (-1.0, 1.0)
        low, high = _floats(actuator.attrib["forcerange"])
        assert low < 0.0 < high
        assert float(actuator.attrib["gainprm"]) == max(-low, high)
    for name in hinges:
        if not name.endswith("_l"):
            continue
        right = name[:-2] + "_r"
        assert joints[name].attrib["range"] == joints[right].attrib["range"]
        assert actuators[name].attrib["forcerange"] == actuators[right].attrib["forcerange"]
        left_axis = _floats(joints[name].attrib["axis"])
        right_axis = _floats(joints[right].attrib["axis"])
        # Sagittal axes (y) are shared; frontal (x) and transverse (z) axes mirror, so that a
        # positive angle is the same anatomical motion on both sides.
        assert left_axis[1] == right_axis[1]
        assert left_axis[0] == -right_axis[0] and left_axis[2] == -right_axis[2]


def test_ranges_of_motion_permit_a_parallel_squat_and_nothing_beyond_anatomy() -> None:
    ranges = {spec.name: spec.range_deg for spec in anthropometry.joint_specs()}
    # A parallel high-bar squat needs ~120 deg hip and knee flexion and ~35 deg of
    # weight-bearing ankle dorsiflexion; anatomy stops well short of 140/160/50.
    assert 120.0 <= ranges["hip_flexion_l"][1] <= 140.0
    assert 130.0 <= ranges["knee_flexion_l"][1] <= 160.0
    assert 35.0 <= ranges["ankle_dorsiflexion_l"][1] <= 50.0
    assert -10.0 <= ranges["knee_flexion_l"][0] <= 0.0  # at most slight hyperextension
    assert ranges["elbow_flexion_l"][0] == 0.0  # no elbow hyperextension
    assert ranges["lumbar_rotation"][1] <= 15.0  # the lumbar spine barely rotates


def test_extensors_are_stronger_than_flexors_where_anatomy_says_so() -> None:
    capacity = {spec.name: spec.torque_nm for spec in anthropometry.joint_specs()}
    # (negative-direction capacity, positive-direction capacity); positive = flexion.
    for name in ("hip_flexion_l", "knee_flexion_l", "lumbar_flexion", "thoracic_flexion"):
        extension, flexion = capacity[name]
        assert extension > flexion, name
    plantarflexion, dorsiflexion = capacity["ankle_dorsiflexion_l"]
    assert plantarflexion > 2 * dorsiflexion


def test_no_body_collides_with_another_body_and_every_body_meets_the_floor() -> None:
    root = _root()
    defaults = {
        element.attrib["class"]: element.find("geom")
        for element in root.iter("default")
        if "class" in element.attrib
    }

    def bits(geom: ElementTree.Element) -> tuple[int, int]:
        source = defaults.get(geom.attrib.get("class", ""), None)
        contype = geom.attrib.get("contype") or (
            source.attrib.get("contype") if source is not None else None
        )
        conaffinity = geom.attrib.get("conaffinity") or (
            source.attrib.get("conaffinity") if source is not None else None
        )
        return int(contype or 1), int(conaffinity or 1)

    geoms = list(_world().iter("geom"))
    floor = next(g for g in geoms if g.attrib.get("name") == "floor")
    others = [g for g in geoms if g is not floor and g.attrib.get("class") != "visual"]
    floor_bits = bits(floor)
    for first in others:
        first_bits = bits(first)
        assert (first_bits[0] & floor_bits[1]) or (floor_bits[0] & first_bits[1])
        for second in others:
            second_bits = bits(second)
            assert not (first_bits[0] & second_bits[1]) and not (second_bits[0] & first_bits[1])


def test_the_barbell_is_coupled_by_a_shelf_weld_and_two_grips() -> None:
    equality = _root().find("equality")
    assert equality is not None
    welds = equality.findall("weld")
    connects = equality.findall("connect")
    assert [(w.attrib["site1"], w.attrib["site2"]) for w in welds] == [("bar_center", "bar_shelf")]
    assert sorted((c.attrib["site1"], c.attrib["site2"]) for c in connects) == [
        ("grip_l", "bar_grip_l"),
        ("grip_r", "bar_grip_r"),
    ]


def test_every_sole_contact_is_an_explicit_pair_with_stiff_friction() -> None:
    """MuJoCo friction is a velocity servo with the contact's time constant; at the normal
    contact's 0.015 s the feet creep during a squat. Each plantar sphere therefore meets the
    floor through an explicit pair whose friction time constant is much shorter."""
    contact = _root().find("contact")
    assert contact is not None
    pairs = contact.findall("pair")
    soles = {
        geom.attrib["name"] for geom in _world().iter("geom") if geom.attrib.get("class") == "sole"
    }
    assert len(soles) == 10
    assert {pair.attrib["geom2"] for pair in pairs} == soles
    for pair in pairs:
        assert pair.attrib["geom1"] == "floor"
        normal = _floats(pair.attrib["solref"])[0]
        friction = _floats(pair.attrib["solreffriction"])[0]
        assert friction <= normal / 5.0
        assert friction >= 2 * 0.001  # MuJoCo's stability floor: two timesteps
        assert _floats(pair.attrib["friction"])[:2] == (0.9, 0.9)


def test_gravity_and_solver_are_the_declared_ones() -> None:
    option = _root().find("option")
    assert option is not None
    assert _floats(option.attrib["gravity"]) == (0.0, 0.0, -GRAVITY_M_S2)
    assert option.attrib["integrator"] == "implicitfast"
    assert option.attrib["cone"] == "elliptic"
    assert int(option.attrib["noslip_iterations"]) > 0


# ---------------------------------------------------------------------------------------------
# Asset identity and generation


def test_the_asset_is_self_contained() -> None:
    content = _asset()
    for forbidden in (b"<include", b"file=", b"<mesh", b"<texture", b"<hfield"):
        assert forbidden not in content


def test_the_asset_is_exactly_the_renderer_output_for_its_keyframe_and_is_pinned() -> None:
    content = _asset()
    key = _root().find("./keyframe/key")
    assert key is not None and key.attrib["name"] == "stand"
    qpos = list(_floats(key.attrib["qpos"]))
    act = list(_floats(key.attrib["act"]))
    assert key.attrib["ctrl"] == key.attrib["act"]
    assert len(qpos) == 43 and len(act) == 29
    assert all(-1.0 <= value <= 1.0 for value in act)
    assert mjcf.render_model_xml(qpos, act).encode("utf-8") == content
    assert hashlib.sha256(content).hexdigest() == contract.MODEL_SHA256
    assert contract.model_bytes() == content


def test_the_renderer_is_deterministic_and_refuses_half_a_keyframe() -> None:
    assert mjcf.render_model_xml() == mjcf.render_model_xml()
    with pytest.raises(ValueError):
        mjcf.render_model_xml([0.0] * 43, None)


def test_a_changed_pin_refuses_the_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contract, "MODEL_SHA256", "0" * 64)
    with pytest.raises(contract.SquatModelError):
        contract.model_bytes()


def test_the_stance_is_a_normal_squat_stance() -> None:
    shoulder_width = 2 * anthropometry.SHOULDER_JOINT_HALF_WIDTH_M
    assert 0.8 * shoulder_width <= 2 * stance.STANCE.ankle_half_width_m <= 1.5 * shoulder_width
    assert 10.0 <= stance.STANCE.toe_out_deg <= 30.0
    geometry = anthropometry.geometry()
    heel = -geometry.heel_offset
    toe = geometry.foot - geometry.heel_offset
    assert heel < stance.BALANCE_POINT_ANTERIOR_M < toe


def test_importing_the_model_authority_loads_no_engine_and_no_numpy() -> None:
    probe = "\n".join(
        [
            "import sys",
            "import dynamisbench.adapters.mujoco.squat",
            "from dynamisbench.adapters.mujoco.squat import anthropometry, contract, mjcf, stance",
            "mjcf.render_model_xml()",
            "print(' '.join(sorted(m for m in ('mujoco', 'numpy') if m in sys.modules)))",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == ""
