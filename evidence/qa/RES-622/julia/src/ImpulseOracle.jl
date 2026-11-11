"""
    ImpulseOracle

Independent vertical impulse-momentum oracle for the RES-622 squat export. See `../SPEC.md`
(frozen before any real-data residual was computed). Standard library only.
"""
module ImpulseOracle

using SHA

export Series, Window, WindowResult, InputError, read_series, windows_of, evaluate, report_json,
    MASS_KG, GRAVITY, EPS_REL, EPS_ABS, EPS_Q, MAX_ROWS, MAX_BYTES

const MASS_KG = 95.0          # 75 kg athlete + 20 kg barbell (declared, SPEC section 2)
const GRAVITY = 9.80665       # ISO 80000-3 standard gravity, m/s^2
const EPS_REL = 1.0e-3        # SPEC section 5
const EPS_ABS = 1.0e-9        # N s
const EPS_Q = 5.0e-3          # cap on the quadrature allowance (SPEC erratum 2)
const MAX_ROWS = 1_000_000
const MAX_BYTES = 256 * 1024 * 1024
const TOOL_SCHEMA = "dynamisbench.qa.impulse-oracle/1"
const REQUIRED = ("t_s", "grf_left_z_n", "grf_right_z_n", "com_vz_m_s", "phase")

struct InputError <: Exception
    msg::String
end
Base.showerror(io::IO, e::InputError) = print(io, "input rejected: ", e.msg)

struct Series
    t::Vector{Float64}
    fz::Vector{Float64}        # left + right vertical ground reaction, N
    v::Vector{Float64}         # vertical CoM velocity, m/s
    phase::Vector{String}
    sha256::String
end

struct Window
    label::String
    first::Int
    last::Int
end

struct WindowResult
    label::String
    t_start::Float64
    t_end::Float64
    samples::Int
    delta_momentum::Float64    # M (v_b - v_a), N s
    net_impulse::Float64       # integral of (Fz - M g), N s
    residual::Float64          # R
    u_quad::Float64
    tolerance::Float64
    ratio::Float64             # |R| / tau
    pass::Bool
    quadrature_limited::Bool   # u_quad exceeded its cap: the grid cannot resolve the signal
end

"Neumaier-compensated sum of `f(i)` for `i in rng`."
function csum(f, rng)
    s = 0.0
    c = 0.0
    for i in rng
        x = f(i)
        t = s + x
        c += abs(s) >= abs(x) ? (s - t) + x : (x - t) + s
        s = t
    end
    return s + c
end

"Composite trapezoid of `y` from index `i0` with stride `k`, `n` panels, base step `h`."
function trapezoid(y::AbstractVector{Float64}, h::Float64, i0::Int, n::Int, k::Int)
    n >= 1 || return 0.0
    inner = n >= 2 ? csum(i -> y[i], (i0 + k):k:(i0 + (n - 1) * k)) : 0.0
    return k * h * (0.5 * (y[i0] + y[i0 + n * k]) + inner)
end

function read_series(path::AbstractString)
    isfile(path) || throw(InputError("not a file: $path"))
    filesize(path) <= MAX_BYTES || throw(InputError("input larger than $(MAX_BYTES) bytes"))
    bytes = read(path)
    digest = bytes2hex(sha256(bytes))
    lines = split(String(bytes), '\n'; keepempty = false)
    isempty(lines) && throw(InputError("empty input"))
    header = split(rstrip(lines[1], '\r'), ',')
    col = Dict{String,Int}(String(h) => i for (i, h) in enumerate(header))
    for name in REQUIRED
        haskey(col, name) || throw(InputError("missing column $name"))
    end
    n = length(lines) - 1
    n >= 3 || throw(InputError("fewer than 3 samples"))
    n <= MAX_ROWS || throw(InputError("more than $(MAX_ROWS) rows"))
    t = Vector{Float64}(undef, n)
    fz = similar(t)
    v = similar(t)
    phase = Vector{String}(undef, n)
    width = length(header)
    for r in 1:n
        f = split(rstrip(lines[r + 1], '\r'), ',')
        length(f) == width || throw(InputError("row $r has $(length(f)) fields, expected $width"))
        try
            t[r] = parse(Float64, f[col["t_s"]])
            fz[r] = parse(Float64, f[col["grf_left_z_n"]]) + parse(Float64, f[col["grf_right_z_n"]])
            v[r] = parse(Float64, f[col["com_vz_m_s"]])
        catch
            throw(InputError("row $r holds a non-numeric value"))
        end
        phase[r] = String(f[col["phase"]])
        (isfinite(t[r]) && isfinite(fz[r]) && isfinite(v[r])) ||
            throw(InputError("row $r holds a non-finite value"))
    end
    h = (t[end] - t[1]) / (n - 1)
    h > 0 || throw(InputError("time is not increasing"))
    for r in 2:n
        abs((t[r] - t[r - 1]) - h) <= 1e-6 * h + 1e-9 ||
            throw(InputError("time grid is not uniform at row $r"))
    end
    return Series(t, fz, v, phase, digest)
end

function windows_of(s::Series)
    n = length(s.t)
    ws = [Window("whole-record", 1, n)]
    a = 1
    for i in 2:(n + 1)
        if i == n + 1 || s.phase[i] != s.phase[a]
            i - 1 > a && push!(ws, Window("phase:" * s.phase[a] * "@" * string(a), a, i - 1))
            a = i
        end
    end
    return ws
end

function evaluate(s::Series, w::Window; mass = MASS_KG, gravity = GRAVITY)
    h = (s.t[end] - s.t[1]) / (length(s.t) - 1)
    net = Vector{Float64}(undef, length(s.fz))
    @inbounds for i in eachindex(net)
        net[i] = s.fz[i] - mass * gravity
    end
    n = w.last - w.first
    impulse = trapezoid(net, h, w.first, n, 1)
    n_even = n - (n % 2)
    if n_even >= 2
        i_h = trapezoid(net, h, w.first, n_even, 1)
        i_2h = trapezoid(net, h, w.first, n_even ÷ 2, 2)
        u_q = abs(i_h - i_2h) * (n / n_even)
    else
        u_q = 0.0
    end
    dp = mass * (s.v[w.last] - s.v[w.first])
    r = dp - impulse
    dt = s.t[w.last] - s.t[w.first]
    cap = EPS_Q * mass * gravity * dt
    tau = min(u_q, cap) + EPS_REL * mass * gravity * dt + EPS_ABS
    return WindowResult(w.label, s.t[w.first], s.t[w.last], n + 1, dp, impulse, r, u_q, tau,
        abs(r) / tau, abs(r) <= tau, u_q > cap)
end

evaluate(s::Series; kwargs...) = [evaluate(s, w; kwargs...) for w in windows_of(s)]

jnum(x::Real) = isfinite(x) ? string(Float64(x)) : "null"
jstr(x::AbstractString) = "\"" * replace(x, "\\" => "\\\\", "\"" => "\\\"") * "\""

function report_json(s::Series, results; mass = MASS_KG, gravity = GRAVITY)
    io = IOBuffer()
    println(io, "{")
    println(io, "  \"schema\": ", jstr(TOOL_SCHEMA), ",")
    println(io, "  \"julia_version\": ", jstr(string(VERSION)), ",")
    println(io, "  \"input_sha256\": ", jstr(s.sha256), ",")
    println(io, "  \"constants\": {\"mass_kg\": ", jnum(mass), ", \"gravity_m_s2\": ", jnum(gravity),
        ", \"eps_rel\": ", jnum(EPS_REL), ", \"eps_abs\": ", jnum(EPS_ABS), ", \"eps_q\": ", jnum(EPS_Q), "},")
    println(io, "  \"all_pass\": ", all(r -> r.pass, results), ",")
    println(io, "  \"windows\": [")
    for (k, r) in enumerate(results)
        print(io, "    {\"label\": ", jstr(r.label), ", \"t_start_s\": ", jnum(r.t_start),
            ", \"t_end_s\": ", jnum(r.t_end), ", \"samples\": ", r.samples,
            ", \"delta_momentum_n_s\": ", jnum(r.delta_momentum),
            ", \"net_impulse_n_s\": ", jnum(r.net_impulse),
            ", \"residual_n_s\": ", jnum(r.residual), ", \"u_quad_n_s\": ", jnum(r.u_quad),
            ", \"tolerance_n_s\": ", jnum(r.tolerance), ", \"ratio\": ", jnum(r.ratio),
            ", \"pass\": ", r.pass, ", \"quadrature_limited\": ", r.quadrature_limited, "}")
        println(io, k < length(results) ? "," : "")
    end
    println(io, "  ]")
    println(io, "}")
    return String(take!(io))
end

function main(args::Vector{String})
    input = nothing
    output = nothing
    mass = MASS_KG
    gravity = GRAVITY
    i = 1
    while i <= length(args)
        a = args[i]
        if a == "--input" && i < length(args)
            input = args[i + 1]; i += 2
        elseif a == "--output" && i < length(args)
            output = args[i + 1]; i += 2
        elseif a == "--mass-kg" && i < length(args)
            mass = parse(Float64, args[i + 1]); i += 2
        elseif a == "--gravity" && i < length(args)
            gravity = parse(Float64, args[i + 1]); i += 2
        else
            println(stderr, "usage: impulse_oracle.jl --input <csv> [--output <json>] [--mass-kg M] [--gravity g]")
            return 2
        end
    end
    if input === nothing
        println(stderr, "missing --input")
        return 2
    end
    local s
    try
        s = read_series(input)
    catch e
        e isa InputError || rethrow()
        println(stderr, sprint(showerror, e))
        return 2
    end
    results = evaluate(s; mass = mass, gravity = gravity)
    json = report_json(s, results; mass = mass, gravity = gravity)
    output === nothing ? print(json) : write(output, json)
    return all(r -> r.pass, results) ? 0 : 1
end

end # module
