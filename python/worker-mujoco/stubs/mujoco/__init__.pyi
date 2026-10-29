"""Minimal type surface for the compiled MuJoCo extension used by the worker.

MuJoCo 3.17 ships compiled ``_structs``/``_enums`` extension modules without a ``py.typed``
marker or stub files, so a static checker cannot see the classes re-exported through
``from mujoco._structs import *``. This stub declares only the API this adapter uses. It is
a type-checking aid, never a runtime module and never part of the adapter identity.
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
    opt: Any
    jnt_type: Any
    jnt_bodyid: Any
    jnt_limited: Any
    jnt_axis: Any
    jnt_pos: Any
    body_mass: Any
    body_inertia: Any
    body_ipos: Any
    body_iquat: Any
    dof_damping: Any
    dof_armature: Any
    dof_frictionloss: Any
    @classmethod
    def from_xml_string(cls, xml: str) -> MjModel: ...

class MjData:
    qpos: Any
    qvel: Any
    qacc: Any
    time: float
    ncon: int
    nefc: int
    def __init__(self, model: MjModel) -> None: ...

class mjtObj:
    mjOBJ_BODY: int
    mjOBJ_JOINT: int

class mjtJoint:
    mjJNT_HINGE: int

class mjtIntegrator:
    mjINT_RK4: int

class mjtSolver:
    mjSOL_NEWTON: int

def mj_id2name(model: MjModel, object_type: Any, object_id: int) -> str | None: ...
def mj_resetData(model: MjModel, data: MjData) -> None: ...
def mj_forward(model: MjModel, data: MjData) -> None: ...
def mj_step(model: MjModel, data: MjData) -> None: ...
