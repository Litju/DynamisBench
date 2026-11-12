# RES-640 energy qualification correction

The energy fields in the historical `raw/mechanism-windows-local.json` do not
measure energy. The packaged MJCF has no energy-enable flag. MuJoCo 3.17.0's
[`mj_forwardSkip`](https://github.com/google-deepmind/mujoco/blob/3.17.0/src/engine/engine_forward.c#L1795-L1813)
explicitly clears the energy array when the optional calculation is disabled
and an energy sensor has not requested it. The historical zeros are preserved
as observations of that disabled path, and superseded as evidence of symmetry.
The [versioned XML documentation](https://mujoco.readthedocs.io/en/3.17.0/XMLreference.html#option-flag-energy)
declares this optional calculation disabled by default.

`energy_qualification.py` enables the flag only on a freshly loaded diagnostic
model in an isolated process. It does not integrate, regenerate a reference,
write MJCF, or change the production configuration. Every sample initializes
the energy array with nonzero sentinels before `mj_forward`, so clearing versus
calculation is demonstrated directly. All sample velocities are zero; kinetic
energy is therefore zero. No claim of energy conservation in the controlled,
actuated, dissipative standing trajectory follows from these static tests.

The independent gravitational calculation is `sum(m_b * 9.80665 * h_b)` in
joules, using declared compiled body masses in kilograms and world COM heights
in metres. Each height is independently reconstructed as the body's world
origin height plus the third row of its world rotation matrix dotted with its
declared local inertial offset. It uses `math.fsum` and does not read `xipos` or
`energy`. This shares MuJoCo kinematics and the declared model with the engine
calculation, so it is an independent energy arithmetic path, not an independent
kinematic implementation. Recorded per-body masses and heights permit audit.
The declared total mass is checked against 75 kg athlete plus 20 kg barbell;
vertical gravity is checked against 9.80665 m/s². Joint stiffness (including
polynomial stiffness), tendon stiffness and flexes are checked absent, so
additional elastic potential terms do not confound the comparison.

Before sampling, the script sets an engineering roundoff allowance of
`gamma_N * 95 * 9.80665 * 4` J per energy, where
`gamma_N = N*epsilon/(1-N*epsilon)`, `N=256*(nbody+1)`, and
`epsilon=2^-52`. The allowance conservatively permits 256 scalar roundings per
kinematic link along a chain no longer than the body count, covering quaternion
and matrix transformations, multiplication and summation. Every COM height is
checked below the prescribed 4 m scale. Comparisons use twice this allowance
for subtraction of two energies: **8.049484335978884e-9 J** on this model.
This is conditional on ordinary binary64 and accurate libm trigonometry. It is
an explicit numerical engineering budget, not a formal proof of a particular
libm implementation, a solver tolerance, or an estimate of biomechanical or
measurement uncertainty. It does not change `KEYFRAME_TOLERANCE`.

Positive control: translating both free bodies upward by exactly 0.125 m,
without changing any joint or relative configuration, must increase potential
by `95*9.80665*0.125 = 116.45396874999999` J. The measured residual is
**7.105427357601002e-14 J** in both paths. This exceeds the error budget in
signal amplitude by over ten billion and demonstrates sensitivity to nonzero
energy changes. The lifted state need not be a static contact equilibrium;
the test concerns potential energy at a prescribed configuration.

Negative controls: rigid common yaw at `-pi, -1, -0.1, 0.001, 0.1, 1, pi/2, pi`
radians preserves height and gravitational potential. The recorded independent
calculation yields floating-point residual 0.0 J at these samples; MuJoCo's
maximum observed residual is **2.2737367544323206e-13 J**. Neither is claimed
to prove exact numerical zero generally. Both are inside the predeclared
budget. Baseline computed potential is **1030.3403578290963 J**; the disabled
path yields 0.0 J despite nonzero sentinel initialization.

`raw/energy-windows-local.json` records the actual Python, NumPy, MuJoCo, OS,
CPU, model identity, script/engine/reference/worker-lock/interpreter digests
and installed MuJoCo native-library hashes. It is a Windows observation;
Linux qualification is separately required. The mandatory regression executes
the same controls in each actual isolated worker, with no disabled-energy
comparison treated as evidence of invariance.
