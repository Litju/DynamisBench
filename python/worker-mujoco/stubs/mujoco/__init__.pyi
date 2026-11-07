"""Minimal type surface for the compiled MuJoCo extension used by the worker.

MuJoCo 3.17 ships compiled ``_structs``/``_enums`` extension modules without a ``py.typed``
marker or stub files, so a static checker cannot see the classes re-exported through
``from mujoco._structs import *``. This stub declares only the API this adapter uses. It is
a type-checking aid, never a runtime module and never part of the adapter identity.

The reference pendulum (``physics.py``) and the barbell back-squat model (``squat/engine.py``)
are the two modules that use it; a name is added here only when one of them uses it.
"""

from typing import Any

__version__: str

class MjModel:
    nq: int
    nv: int
    nu: int
    na: int
    njnt: int
    nbody: int
    ngeom: int
    nsite: int
    nmesh: int
    ntex: int
    nsensor: int
    nkey: int
    neq: int
    opt: Any
    jnt_type: Any
    jnt_bodyid: Any
    jnt_limited: Any
    jnt_axis: Any
    jnt_pos: Any
    body_mass: Any
    body_parentid: Any
    geom_bodyid: Any
    geom_contype: Any
    geom_conaffinity: Any
    geom_type: Any
    geom_size: Any
    geom_pos: Any
    geom_quat: Any
    body_inertia: Any
    body_ipos: Any
    body_pos: Any
    body_quat: Any
    body_iquat: Any
    dof_damping: Any
    dof_armature: Any
    dof_frictionloss: Any
    jnt_qposadr: Any
    jnt_dofadr: Any
    jnt_range: Any
    actuator_trnid: Any
    npair: int
    pair_solreffriction: Any
    pair_solref: Any
    actuator_forcerange: Any
    actuator_dynprm: Any
    eq_type: Any
    key_qpos: Any
    key_act: Any
    @classmethod
    def from_xml_string(cls, xml: str) -> MjModel: ...

class MjData:
    qpos: Any
    qvel: Any
    qacc: Any
    time: float
    ncon: int
    nefc: int
    act: Any
    ctrl: Any
    xpos: Any
    xquat: Any
    xmat: Any
    site_xpos: Any
    site_xmat: Any
    geom_xpos: Any
    subtree_com: Any
    subtree_linvel: Any
    subtree_angmom: Any
    qfrc_bias: Any
    qfrc_passive: Any
    qfrc_inverse: Any
    xfrc_applied: Any
    contact: Any
    efc_type: Any
    efc_id: Any
    efc_force: Any
    actuator_force: Any
    def __init__(self, model: MjModel) -> None: ...

class mjtObj:
    mjOBJ_BODY: int
    mjOBJ_JOINT: int
    mjOBJ_GEOM: int
    mjOBJ_SITE: int
    mjOBJ_ACTUATOR: int
    mjOBJ_KEY: int

class mjtJoint:
    mjJNT_FREE: int
    mjJNT_HINGE: int

class mjtIntegrator:
    mjINT_RK4: int
    mjINT_IMPLICITFAST: int

class mjtCone:
    mjCONE_ELLIPTIC: int

class mjtEq:
    mjEQ_CONNECT: int
    mjEQ_WELD: int

class mjtConstraint:
    mjCNSTR_EQUALITY: int

class mjtSolver:
    mjSOL_NEWTON: int

def mj_id2name(model: MjModel, object_type: Any, object_id: int) -> str | None: ...
def mj_resetData(model: MjModel, data: MjData) -> None: ...
def mj_forward(model: MjModel, data: MjData) -> None: ...
def mj_step(model: MjModel, data: MjData) -> None: ...
def mj_name2id(model: MjModel, object_type: Any, name: str) -> int: ...
def mj_resetDataKeyframe(model: MjModel, data: MjData, key: int) -> None: ...
def mj_kinematics(model: MjModel, data: MjData) -> None: ...
def mj_comPos(model: MjModel, data: MjData) -> None: ...
def mj_inverse(model: MjModel, data: MjData) -> None: ...
def mj_subtreeVel(model: MjModel, data: MjData) -> None: ...
def mj_integratePos(model: MjModel, qpos: Any, qvel: Any, dt: float) -> None: ...
def mj_jac(model: MjModel, data: MjData, jacp: Any, jacr: Any, point: Any, body: int) -> None: ...
def mj_jacBody(model: MjModel, data: MjData, jacp: Any, jacr: Any, body: int) -> None: ...
def mj_jacSite(model: MjModel, data: MjData, jacp: Any, jacr: Any, site: int) -> None: ...
def mj_jacSubtreeCom(model: MjModel, data: MjData, jacp: Any, body: int) -> None: ...
def mj_mulM(model: MjModel, data: MjData, res: Any, vec: Any) -> None: ...
def mj_contactForce(model: MjModel, data: MjData, index: int, result: Any) -> None: ...
def mju_mat2Quat(quat: Any, mat: Any) -> None: ...
def mju_quat2Vel(res: Any, quat: Any, dt: float) -> None: ...
def mj_comVel(model: MjModel, data: MjData) -> None: ...
def mj_rne(model: MjModel, data: MjData, flg_acc: int, result: Any) -> None: ...
def mj_differentiatePos(model: MjModel, qvel: Any, dt: float, qpos1: Any, qpos2: Any) -> None: ...
def mj_objectVelocity(
    model: MjModel, data: MjData, object_type: int, object_id: int, result: Any, flg_local: int
) -> None: ...
