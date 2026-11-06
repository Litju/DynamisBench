# RES-566 Arrow pre-materialization qualification

## Scope and disposition

This focused repair adds a bounded, pure-standard-library Arrow IPC preflight to the Python
transport reader and the matching TypeScript frontend decoder. It runs before PyArrow's
`read_all()` or the frontend's `tableFromIPC()` and checks the complete stream framing,
schema profile, dimensions, metadata, body extents, and declared decoded-buffer total. The
PR adds no route, new dependency, or scientific-data claim.

The existing 1 MiB serialized-input cap, 100,000-row cap, lazy PyArrow import, frozen
cross-language 832-byte qualification stream, and its schema/value contract remain intact.
The original fixture is unchanged. Existing flat-scalar streams continue to decode under the
same public `ArrowTable` / `DecodedArrowTable` shape. Python continues to accept compressed
streams when their declared decoded buffers fit the cap and PyArrow provides that codec.

The preflight adds caps of 256 columns, 512 field nodes, 250,000 logical values, 8 MiB total
decoded buffers, 256 KiB per IPC message metadata, 512 KiB total metadata, 128 messages, 64
record batches, 16 field levels, 4,096 buffers, and bounded metadata counts/string sizes.
Nested, dictionary, view, extension, and other unprofiled schema layouts fail closed.
Compressed streams are parsed far enough to reject a declared expansion above 8 MiB before
PyArrow runs. Bounded LZ4-frame/Zstandard buffers retain Python's existing read behavior.
The browser decoder still refuses compressed input before `tableFromIPC` because the
existing frontend package has no compression codec; the previous frontend reader failed on
the same small-compressed control fixture with “codec not found.”

## Adversarial controls

The fixtures include a 15,528-byte stream declaring 100,000 rows × 256 Null columns
(25.6 million logical values, no body buffers), and a 1,208-byte compressed stream declaring
an 8.64 MB decoded string buffer. Other controls exceed the row and column limits, use nested
and dictionary schemas, contain malformed string offsets, and carry a bounded compressed
payload. Python tests assert rejection of the expansion before PyArrow and also verify that a
within-budget compressed stream is preflighted before PyArrow and remains readable. Vitest
asserts refusal before `tableFromIPC`, including compressed input because the browser codec
is unavailable. The Python receipt also asserts that PyArrow remains unloaded on both
principal expansion cases.

`arrow-allocation-windows-local.json` and
`arrow-allocation-frontend-windows-local.json` record local Windows measurements for the
repair commit in their `tested_sha` fields. They are local evidence only, not the authoritative
hosted Windows/Linux result. Exact-head GitHub Actions uploads are the platform qualification
artifacts for the PR. Each receipt includes serialized and decoded dimensions, refusal,
iterations, wall/CPU time, heap/RSS measurements, limits, target and tested/head SHA.

## Reproduction

From `python/`, run:

```powershell
uv run pytest tests/transport/test_arrow_transport.py tests/transport/test_arrow_preflight.py -q
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

From `apps/workbench/`, run:

```powershell
pnpm exec vitest run src/arrow/arrow-allocation.test.ts --reporter=verbose --silent=false
pnpm run typecheck
pnpm run build
```

The Python test confirms the frozen golden payload and API output; the focused adversarial
tests are resource-bound software evidence, not empirical biomechanical validation.
