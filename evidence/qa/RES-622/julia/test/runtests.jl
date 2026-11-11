# Qualification of the oracle itself against closed-form references (SPEC section 6).
# Run: julia --project=. test/runtests.jl
using Test
include(joinpath(@__DIR__, "..", "src", "ImpulseOracle.jl"))
using .ImpulseOracle

const M = MASS_KG
const G = GRAVITY

series(t, fz, v; phase = fill("p", length(t))) = Series(collect(t), fz, v, phase, "synthetic")
whole(s; kw...) = evaluate(s, windows_of(s)[1]; kw...)

@testset "closed-form references" begin
    t = 0.0:0.01:3.0
    @testset "rest" begin
        r = whole(series(t, fill(M * G, length(t)), zeros(length(t))))
        @test abs(r.residual) <= 1e-9 && r.pass
    end
    @testset "constant push (trapezoid exact)" begin
        F0 = 123.4
        r = whole(series(t, fill(M * G + F0, length(t)), [F0 * ti / M for ti in t]))
        @test abs(r.residual) <= 1e-9 && r.pass
    end
    @testset "free flight" begin
        r = whole(series(t, zeros(length(t)), [-G * ti for ti in t]))
        @test abs(r.residual) <= 1e-9 && r.pass
    end
    @testset "sinusoid: residual equals the Euler-Maclaurin truncation term" begin
        A, w = 400.0, 2pi * 1.3
        for h in (0.02, 0.01, 0.005)
            tt = 0.0:h:2.0
            s = series(tt, [M * G + A * sin(w * ti) for ti in tt],
                [A / (M * w) * (1 - cos(w * ti)) for ti in tt])
            r = whole(s)
            predicted = -(h^2 / 12) * A * w * (cos(w * tt[end]) - cos(w * tt[1]))
            @test r.residual ≈ predicted atol = 0.05 * abs(predicted) + 1e-9
            @test abs(r.residual) <= r.tolerance         # the budget covers the method error
            @test r.u_quad > 0
        end
    end
end

@testset "adversarial and perturbed cases" begin
    h = 0.01
    t = 0.0:h:4.0
    A, w = 300.0, 2pi * 0.8
    fz = [M * G + A * sin(w * ti) for ti in t]
    v = [A / (M * w) * (1 - cos(w * ti)) for ti in t]
    base = series(t, fz, v)
    @test whole(base).pass
    @testset "mass +1 %" begin
        @test !whole(base; mass = 1.01 * M).pass
    end
    @testset "gravity 9.9 fails, 9.81 is below the detection floor" begin
        @test !whole(base; gravity = 9.9).pass
        @test whole(base; gravity = 9.81).pass          # documented: +0.0034 % is undetectable
    end
    @testset "GRF sign inversion" begin
        @test !whole(series(t, -fz, v)).pass
    end
    @testset "one-sample velocity time shift on a moving window" begin
        vs = vcat(v[2:end], v[end])
        @test !evaluate(series(t, fz, vs), Window("w", 40, 90)).pass
    end
    @testset "single-sample GRF spike worth more than the tolerance" begin
        spike = copy(fz); spike[200] += 5000.0          # 5000 N * 0.01 s = 50 N s
        @test !whole(series(t, spike, v)).pass
    end
    @testset "slow velocity drift" begin
        drift = [vi + 0.02 * ti for (vi, ti) in zip(v, t)]
        @test !whole(series(t, fz, drift)).pass
    end
    @testset "sub-threshold spike is not flagged (detection floor)" begin
        spike = copy(fz); spike[200] += 1.0             # 0.01 N s << 0.1 % of weight impulse
        @test whole(series(t, spike, v)).pass
    end
end

@testset "input rejection" begin
    mktempdir() do dir
        good = "t_s,grf_left_z_n,grf_right_z_n,com_vz_m_s,phase\n" *
               join(["$(0.01i),$(M * G / 2),$(M * G / 2),0.0,standing" for i in 0:9], "\n") * "\n"
        write_case(name, text) = (p = joinpath(dir, name); write(p, text); p)
        @test read_series(write_case("good.csv", good)) isa Series
        rows = split(good, '\n'; keepempty = false)
        @test_throws InputError read_series(joinpath(dir, "missing.csv"))
        @test_throws InputError read_series(write_case("nan.csv", join([rows[1:5]; ["0.04,NaN,1.0,0.0,standing"]; rows[7:end]], "\n") * "\n"))
        @test_throws InputError read_series(write_case("col.csv", replace(good, "com_vz_m_s" => "vz")))
        @test_throws InputError read_series(write_case("few.csv", join(rows[1:3], "\n") * "\n"))
        @test_throws InputError read_series(write_case("nonuniform.csv",
            join([rows[1:5]; ["0.07,$(M * G / 2),$(M * G / 2),0.0,standing"]; rows[7:end]], "\n") * "\n"))
        @test_throws InputError read_series(write_case("decreasing.csv",
            join([rows[1]; reverse(rows[2:end])], "\n") * "\n"))
        @test_throws InputError read_series(write_case("ragged.csv", good * "0.10,1,2\n"))
        @test_throws InputError read_series(write_case("text.csv", join([rows[1:3]; ["0.02,abc,1.0,0.0,standing"]; rows[5:end]], "\n") * "\n"))
        @test ImpulseOracle.main(["--input", joinpath(dir, "nan.csv")]) == 2
        @test ImpulseOracle.main(["--input", joinpath(dir, "good.csv"), "--output", joinpath(dir, "o.json")]) == 0
        @test occursin("\"all_pass\": true", read(joinpath(dir, "o.json"), String))
        @test ImpulseOracle.main(["--bogus"]) == 2
    end
end
