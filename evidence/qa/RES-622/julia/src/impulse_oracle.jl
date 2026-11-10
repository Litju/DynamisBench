# One-shot command-line entry point. See ../SPEC.md.
include(joinpath(@__DIR__, "ImpulseOracle.jl"))
exit(ImpulseOracle.main(ARGS))
