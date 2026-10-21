/**
 * The Inspector pane: the documented identity and validation facts of one artifact.
 *
 * Every row here is a field the API publishes: the portable logical reference, the declared
 * category and kind, the authoring format, the validation status, the human identifier and
 * version when a valid definition has them, the semantic digest when valid, and the bounded
 * diagnostics. It is deliberately not evidence lineage: there is no timestamp, no absolute
 * source path, no author, no seal and no provenance claim, because the read model carries
 * none of those and inventing one would make this pane a second authority.
 */

import type {
  ArtifactDiagnostic,
  ArtifactInspectionResponse,
  ArtifactSummary,
} from "../api/types";
import { Badge } from "../ui/badge";

export function InspectorPane({ artifact }: { artifact: ArtifactSummary | null }) {
  return (
    <section aria-labelledby="inspector-heading" className="flex min-h-0 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="inspector-heading" className="text-sm font-semibold text-slate-800">
          Inspector
        </h2>
        {artifact !== null && (
          <Badge tone={artifact.validation_status === "valid" ? "ready" : "danger"}>
            {artifact.validation_status}
          </Badge>
        )}
      </div>

      {artifact === null ? (
        <p className="text-sm text-slate-500">
          Select an artifact to inspect its identity and validation facts.
        </p>
      ) : (
        <div className="flex flex-col gap-4 text-sm">
          <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-2">
            <Fact label="Logical reference">
              <code className="break-words text-xs">{artifact.logical_reference}</code>
            </Fact>
            <Fact label="Category">{artifact.category}</Fact>
            <Fact label="Kind">{artifact.kind}</Fact>
            <Fact label="Authoring format">{artifact.authoring_format}</Fact>
            <Fact label="Validation">{artifact.validation_status}</Fact>
            <Fact label="Identifier">{artifact.identifier ?? "none published"}</Fact>
            <Fact label="Version">{artifact.version ?? "none published"}</Fact>
            <Fact label="Semantic digest">
              {artifact.semantic_digest === null ? (
                "none published"
              ) : (
                <span className="flex flex-col gap-0.5">
                  <span className="text-xs text-slate-500">{artifact.semantic_digest.algorithm}</span>
                  <code className="break-all text-xs">{artifact.semantic_digest.hex}</code>
                </span>
              )}
            </Fact>
          </dl>

          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Validation diagnostics
            </h3>
            {artifact.diagnostics.length === 0 ? (
              <p className="mt-1 text-sm text-slate-500">No diagnostics.</p>
            ) : (
              <ul className="mt-1 space-y-2">
                {artifact.diagnostics.map((diagnostic, index) => (
                  <DiagnosticItem key={`${diagnostic.code}-${index}`} diagnostic={diagnostic} />
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-slate-800">{children}</dd>
    </>
  );
}

function DiagnosticItem({ diagnostic }: { diagnostic: ArtifactDiagnostic }) {
  return (
    <li className="rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-900">
      <p className="font-medium">{diagnostic.code}</p>
      <p className="mt-0.5 break-words">{diagnostic.message}</p>
      {(diagnostic.reference !== null ||
        diagnostic.location !== null ||
        diagnostic.category !== null) && (
        <p className="mt-1 break-words text-rose-700">
          {diagnostic.reference !== null && <span>reference: {diagnostic.reference}</span>}
          {diagnostic.location !== null && (
            <span className={diagnostic.reference === null ? "" : " · "}>
              location: {diagnostic.location}
            </span>
          )}
          {diagnostic.category !== null && (
            <span
              className={
                diagnostic.reference === null && diagnostic.location === null ? "" : " · "
              }
            >
              category: {diagnostic.category}
            </span>
          )}
        </p>
      )}
    </li>
  );
}

/** The facts the Inspector can show for an inspection, which is a summary plus content. */
export function inspectorArtifact(
  selected: ArtifactSummary | null,
  inspection: ArtifactInspectionResponse | null,
): ArtifactSummary | null {
  return inspection ?? selected;
}
