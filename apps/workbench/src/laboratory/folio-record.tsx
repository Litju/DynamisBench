/**
 * Folio V · Evidence: the chain of provenance of what is on show, the register of predeclared
 * checks, and the colophon that states the claim and its limits.
 *
 * Two kinds of record, never presented as each other:
 *
 * * a **packaged recording** — its published check results; a diagnostic record of a model
 *   run, not sealed evidence, and the folio says so;
 * * a **workspace run** — what the run service established when it read the run back from its
 *   seals *for this request*: both bundles' verification (file by file), the provenance chain
 *   from the source documents to the canonical series, the independent numerical verification,
 *   the benchmark assessment and the adapter's checks. A run that did not verify is shown with
 *   its reasons and none of its data.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { ApiClientError } from "../api/errors";
import type { LaboratoryCheck } from "../api/laboratory-types";
import { apiQueryKeys, runEvidenceOptions } from "../api/queries";
import type { BundleVerification, RunEvidenceResponse } from "../api/run-types";
import { useLabData } from "./data";
import { Seal } from "./folio-analysis";
import { formatNumber, shortDigest } from "./series";
import { useLaboratoryStore } from "./store";

const GROUP_ORDER = ["Mechanics", "Contact", "Coupling & joints", "Human-likeness", "Numerics", "Benchmark metrics", "Verification"];

export function formatCheckValue(check: LaboratoryCheck): string {
  if (check.value === null) {
    return "—";
  }
  if (Number.isInteger(check.value)) {
    return formatNumber(check.value, 0);
  }
  const magnitude = Math.abs(check.value);
  if (magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e5)) {
    return check.value.toExponential(1).replace("-", "−");
  }
  const digits = magnitude >= 100 ? 1 : magnitude >= 10 ? 2 : 3;
  return formatNumber(check.value, digits);
}

/** Limitations stated by the model card (`adapters/mujoco/squat/README.md`). */
export const LIMITATIONS = [
  "one repetition from quiet standing, an empty 20 kg bar",
  "pure-hinge knee: valgus and tibial rotation cannot occur",
  "an exact internal model (a person's is approximate)",
  "no sensorimotor delay",
  "joint torque generators, not muscles",
  "population-scaled segments, no subject calibration",
];

export function RecordFolio() {
  const { ref, workspaceId, entries } = useLabData();
  const evidenceRunId = useLaboratoryStore((state) => state.evidenceRunId);
  const inspectEvidence = useLaboratoryStore((state) => state.inspectEvidence);
  const runIds = entries.filter((entry) => entry.ref.source === "run").map((entry) => entry.ref.id);
  const target = workspaceId === null ? null : (evidenceRunId ?? (ref.source === "run" ? ref.id : null));
  return (
    <div className="lab-folio lab-evidence">
      {workspaceId !== null ? (
        <div className="lab-evidence-select">
          <label className="lab-field">
            <span>Inspect</span>
            <select
              aria-label="Evidence of"
              value={target ?? ""}
              onChange={(event) => inspectEvidence(event.target.value === "" ? null : event.target.value)}
            >
              <option value="">{ref.source === "dataset" ? "the packaged recording on show" : "the run on show"}</option>
              {runIds.map((id) => (
                <option key={id} value={id}>
                  run {id}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
      {target !== null && workspaceId !== null ? <RunEvidence workspaceId={workspaceId} runId={target} /> : <DatasetEvidence />}
    </div>
  );
}

function DatasetEvidence() {
  const { index, model, recording } = useLabData();
  const groups = GROUP_ORDER.map((group) => ({
    group,
    checks: recording.checks.filter((check) => check.group === group),
  })).filter((entry) => entry.checks.length > 0);
  const others = recording.checks.filter((check) => !GROUP_ORDER.includes(check.group));
  if (others.length > 0) {
    groups.push({ group: "Other", checks: others });
  }
  const passed = recording.checks.filter((check) => check.status === "pass").length;
  const failed = recording.checks.filter((check) => check.status === "fail").length;
  const notEvaluated = recording.checks.length - passed - failed;
  const companions = index.recordings.filter((entry) => entry.recording_id !== recording.recording_id);
  const engine = `${index.generated_with.engine ?? "engine"} ${index.generated_with.engine_version ?? ""}`.trim();

  const chain = [
    { pigment: "ink", title: "Model authority", lines: ["anthropometry.py · mjcf.py · stance.py", "de Leva 1996 · AAOS · IWF"] },
    { pigment: "gold", title: "MJCF asset", lines: ["barbell_back_squat.xml", `sha256 ${shortDigest(model.model_sha256, 16)}…`] },
    { pigment: "lapis", title: "Worker environment", lines: [`${engine} · CPython ${index.generated_with.python_version ?? "—"}`, "isolated worker process, locked"] },
    {
      pigment: "sanguine",
      title: "Recording",
      lines: [`${recording.recording_id} · dt ${formatNumber(recording.timestep_s * 1000, 1)} ms · ${recording.steps} steps`, `trajectory ${shortDigest(recording.trajectory_sha256, 16)}…`],
    },
    {
      pigment: "sanguine",
      title: "Companions",
      lines: [companions.map((entry) => entry.label.split(" — ")[1] ?? entry.label).join(" · "), companions.map((entry) => `${shortDigest(entry.trajectory_sha256, 8)}…`).join(" · ")],
    },
    { pigment: "gold", title: "Laboratory dataset", lines: [`${index.dataset_id} · packaged`, `manifest ${shortDigest(index.manifest_sha256, 16)}… pinned`] },
    { pigment: "verdigris", title: "Application API", lines: ["GET /laboratory/… (JSON, Arrow IPC)", "packaged records, read-only"] },
    { pigment: "verdigris", title: "Workbench", lines: ["this view", "renders only what the API published"] },
  ];

  return (
    <div className="lab-record">
      <section className="lab-card lab-chain" aria-labelledby="chain-title">
        <h2 id="chain-title" className="lab-card-title lab-display">
          Chain of provenance
        </h2>
        <p className="lab-marginal">packaged files are pinned; this view does not re-run the worker execution</p>
        <ol>
          {chain.map((link) => (
            <li key={link.title} data-pigment={link.pigment}>
              <span className="lab-chain-node" aria-hidden="true" />
              <strong>{link.title}</strong>
              {link.lines.map((line, i) => (
                <span key={i} className={i === 1 ? "lab-chain-digest" : undefined}>
                  {line}
                </span>
              ))}
            </li>
          ))}
        </ol>
      </section>

      <section className="lab-card lab-checks" aria-labelledby="checks-title">
        <h2 id="checks-title" className="lab-card-title lab-display">
          Register of checks
        </h2>
        <p className="lab-marginal" data-testid="check-tally">
          predeclared acceptance criteria, evaluated on {recording.label} · {passed} pass · {failed} fail
          {notEvaluated > 0 ? ` · ${notEvaluated} not evaluated` : ""}
        </p>
        {groups.map((entry) => (
          <table key={entry.group} className="lab-table lab-check-table" aria-label={`${entry.group} checks`}>
            <caption>{entry.group}</caption>
            <colgroup>
              <col className="seal" />
              <col />
              <col className="value" />
              <col className="bound" />
              <col className="status" />
            </colgroup>
            <thead className="sr-only">
              <tr>
                <th scope="col">Outcome</th>
                <th scope="col">Check</th>
                <th scope="col">Value</th>
                <th scope="col">Bound</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {entry.checks.map((check) => (
                <tr key={`${entry.group}-${check.criterion_id}`} data-status={check.status} data-criterion={check.criterion_id} title={check.rationale}>
                  <td className="lab-check-seal">
                    <Seal status={check.status} />
                  </td>
                  <th scope="row">
                    {check.label}
                    <small>{check.rationale}</small>
                  </th>
                  <td className="num">
                    {formatCheckValue(check)} <span className="unit">{check.unit}</span>
                  </td>
                  <td className="num lab-check-bound">{check.bound}</td>
                  <td className="lab-check-status">{check.status === "not_evaluated" ? "N/E" : check.status.toUpperCase()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      </section>

      <section className="lab-card lab-colophon" aria-labelledby="colophon-title">
        <h2 id="colophon-title" className="lab-card-title lab-display">
          Colophon
        </h2>
        <h3 className="lab-rubric">Claim</h3>
        <p>{index.claim}</p>
        {recording.kind !== "nominal" && <p className="lab-note">{recording.description}</p>}
        <h3 className="lab-rubric">Limitations</h3>
        <ul>
          {LIMITATIONS.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
        <h3 className="lab-rubric">Reproduce</h3>
        <p className="lab-marginal">
          The packaged recording and figure are checked against their pinned manifest. The
          MuJoCo worker that generated them is not run by this read-only integration.
        </p>
        <h3 className="lab-rubric lab-ochre">Not sealed evidence</h3>
        <p className="lab-marginal">
          This packaged recording is a diagnostic record. Sealed, verified runs are produced from a workspace study in Study &amp; Runs,
          through RunSpec, preflight and the isolated worker, and their evidence is inspected here.
        </p>
      </section>
    </div>
  );
}

function describeError(error: unknown): string {
  return error instanceof ApiClientError ? (error.apiMessage ?? error.message) : "The evidence could not be read.";
}

const STATUS_TEXT: Record<RunEvidenceResponse["status"], string> = {
  verified: "Verified — both seals, the provenance chain and the canonical series check out",
  failed: "Sealed failure — authoritative evidence that the run did not produce a result",
  rejected: "Rejected — the sealed evidence does not verify; nothing of it is shown as data",
  incomplete: "Incomplete — the execution is sealed but was never normalized and verified",
};

function checkStatus(status: string): "pass" | "fail" | "not_evaluated" {
  return status === "pass" || status === "fail" ? status : "not_evaluated";
}

function RunEvidence({ workspaceId, runId }: { workspaceId: string; runId: string }) {
  const { client } = useLabData();
  const evidence = useQuery(runEvidenceOptions(client, workspaceId, runId));
  const queryClient = useQueryClient();
  const status = evidence.data?.status;
  // A run found not to verify is read again everywhere it is listed or drawn.
  useEffect(() => {
    if (status !== undefined && status !== "verified") {
      void queryClient.invalidateQueries({ queryKey: apiQueryKeys.runs(workspaceId) });
      // Its data reads (never its evidence, which is what is on show) are dropped from the cache.
      queryClient.removeQueries({ queryKey: apiQueryKeys.runRecording(workspaceId, runId) });
      queryClient.removeQueries({ queryKey: apiQueryKeys.runModel(workspaceId, runId) });
      queryClient.removeQueries({ queryKey: [...apiQueryKeys.run(workspaceId, runId), "frames"] });
    }
  }, [status, queryClient, workspaceId, runId]);
  if (evidence.isError) {
    return (
      <section className="lab-card" role="alert">
        <h2 className="lab-card-title lab-display">The evidence of {runId} could not be read</h2>
        <p>{describeError(evidence.error)}</p>
      </section>
    );
  }
  if (evidence.data === undefined) {
    return (
      <p className="lab-marginal" aria-busy="true">
        re-verifying {runId} from its seals…
      </p>
    );
  }
  return <RunEvidenceView evidence={evidence.data} verifiedAt={evidence.dataUpdatedAt} />;
}

function BundleCard({ title, bundle, pigment }: { title: string; bundle: BundleVerification; pigment: string }) {
  return (
    <section className="lab-card lab-bundle" data-valid={bundle.valid} aria-label={title}>
      <h3 className="lab-card-title lab-display">
        {title} <span className="lab-bundle-state">{bundle.valid ? "seal verifies" : "does not verify"}</span>
      </h3>
      <p className="lab-chain-digest" data-pigment={pigment}>
        {bundle.run_id ?? "—"} · {bundle.outcome ?? "—"} · evidence {bundle.evidence_digest === null ? "—" : `${shortDigest(bundle.evidence_digest, 16)}…`}
      </p>
      {bundle.defects.length > 0 ? (
        <ul className="lab-refusals">
          {bundle.defects.map((defect) => (
            <li key={defect}>{defect}</li>
          ))}
        </ul>
      ) : null}
      {bundle.files.length > 0 ? (
        <table className="lab-table lab-files">
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col" className="num">
                Bytes
              </th>
              <th scope="col">SHA-256</th>
            </tr>
          </thead>
          <tbody>
            {bundle.files.map((file) => (
              <tr key={file.path}>
                <th scope="row">
                  <code>{file.path}</code>
                </th>
                <td className="num">{file.size_bytes.toLocaleString("en-US")}</td>
                <td>
                  <span className="lab-digest" title={file.sha256}>
                    {shortDigest(file.sha256, 12)}…
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

function RunEvidenceView({ evidence, verifiedAt }: { evidence: RunEvidenceResponse; verifiedAt: number }) {
  const provenance = evidence.provenance;
  const definitions = provenance === null ? [] : Object.entries(provenance.definitions);
  const chain = provenance === null
    ? []
    : [
        {
          pigment: "ink",
          title: "Source documents",
          lines: [
            definitions.map(([kind, definition]) => `${kind.replace(/_/g, " ")} ${definition.identifier}@${definition.version}`).join(" · "),
            definitions.map(([, definition]) => `${shortDigest(definition.semantic_digest, 8)}`).join(" · "),
          ],
        },
        {
          pigment: "gold",
          title: "Inputs (content-addressed)",
          lines: ["model asset and definitions, materialized before preflight", `input manifest ${shortDigest(provenance.input_manifest_digest, 16)}…`],
        },
        {
          pigment: "lapis",
          title: "RunSpec & preflight",
          lines: [
            `execution fingerprint ${shortDigest(provenance.execution_fingerprint, 12)}…`,
            `request ${provenance.preflight_request_digest === null ? "—" : `${shortDigest(provenance.preflight_request_digest, 16)}…`}`,
          ],
        },
        {
          pigment: "lapis",
          title: "Isolated worker",
          lines: [
            `${provenance.adapter.adapter_id}@${provenance.adapter.adapter_version} · ${provenance.adapter.engine} ${provenance.adapter.engine_version}`,
            `implementation ${provenance.adapter.implementation_digest === null ? "—" : `${shortDigest(provenance.adapter.implementation_digest, 16)}…`}`,
          ],
        },
        {
          pigment: "sanguine",
          title: "Execution bundle (native)",
          lines: [
            `${Object.keys(provenance.native).length} native files · ${provenance.execution_outcome}`,
            `evidence ${shortDigest(provenance.execution_evidence_digest, 16)}…`,
          ],
        },
        {
          pigment: "sanguine",
          title: "Trajectory",
          lines: ["the integrated state sequence, hashed by the worker", provenance.trajectory_sha256 === null ? "—" : `${shortDigest(provenance.trajectory_sha256, 16)}…`],
        },
        {
          pigment: "verdigris",
          title: "Canonical series",
          lines: [
            `normalized to benchmark quantities · ${Object.keys(provenance.derivation_implementation).length} derivation modules pinned`,
            Object.values(provenance.canonical).map((digest) => `${shortDigest(digest, 16)}…`).join(" · ") || "none (failure)",
          ],
        },
        {
          pigment: "verdigris",
          title: "Derived bundle",
          lines: ["verification, assessment, provenance", evidence.derived.evidence_digest === null ? "—" : `evidence ${shortDigest(evidence.derived.evidence_digest, 16)}…`],
        },
      ];
  const metrics = evidence.metrics;
  const passedMetrics = metrics.filter((metric) => metric.status === "pass").length;
  const failedMetrics = metrics.filter((metric) => metric.status === "fail").length;
  const passedVerification = evidence.verification.filter((check) => check.status === "pass").length;

  return (
    <div className="lab-run-evidence" data-status={evidence.status}>
      <section className="lab-card lab-verdict" data-status={evidence.status} aria-label="Read-back verdict">
        <h2 className="lab-card-title lab-display">
          Run {evidence.run_id} <span className="lab-run-status" data-status={evidence.status}>{evidence.status}</span>
        </h2>
        <p role="status">{STATUS_TEXT[evidence.status]}</p>
        {evidence.reasons.length > 0 ? (
          <ul className="lab-refusals" aria-label="Reasons">
            {evidence.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
        <p className="lab-marginal">
          re-verified by the run service from the sealed bundles at {new Date(verifiedAt).toLocaleTimeString("en-GB")}
          {evidence.case_id === null ? " · no case could be read" : ` · case ${evidence.case_id}`}
        </p>
      </section>

      <div className="lab-record">
        <section className="lab-card lab-chain" aria-labelledby="run-chain-title">
          <h2 id="run-chain-title" className="lab-card-title lab-display">
            Chain of provenance
          </h2>
          <p className="lab-marginal">
            source → evidence as the sealed provenance records it; both seals and the execution → derived link are re-verified on every read
          </p>
          {chain.length === 0 ? (
            <p className="lab-note">No provenance could be read from this run&apos;s derived bundle.</p>
          ) : (
            <ol>
              {chain.map((link) => (
                <li key={link.title} data-pigment={link.pigment}>
                  <span className="lab-chain-node" aria-hidden="true" />
                  <strong>{link.title}</strong>
                  {link.lines.map((line, i) => (
                    <span key={i} className={i === 1 ? "lab-chain-digest" : undefined}>
                      {line}
                    </span>
                  ))}
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="lab-card lab-checks" aria-labelledby="run-checks-title">
          <h2 id="run-checks-title" className="lab-card-title lab-display">
            Register
          </h2>
          <p className="lab-marginal" data-testid="run-check-tally">
            {evidence.status === "verified"
              ? `verification ${passedVerification} of ${evidence.verification.length} pass · benchmark metrics ${passedMetrics} pass · ${failedMetrics} fail`
              : evidence.status === "failed"
                ? "no register: the run did not produce a result (see the failure below)"
                : "no register: nothing is read from a run whose evidence does not verify"}
          </p>
          {evidence.verification.length > 0 ? (
            <table className="lab-table lab-check-table" aria-label="Independent verification">
              <caption>Independent verification</caption>
              <colgroup>
                <col className="seal" />
                <col />
                <col className="value" />
                <col className="bound" />
                <col className="status" />
              </colgroup>
              <tbody>
                {evidence.verification.map((check) => (
                  <tr key={check.check_id} data-status={checkStatus(check.status)} data-criterion={check.check_id} title={check.method}>
                    <td className="lab-check-seal">
                      <Seal status={checkStatus(check.status)} />
                    </td>
                    <th scope="row">
                      {check.label}
                      <small>{check.method}</small>
                    </th>
                    <td className="num">
                      {check.value === null ? "—" : formatSmall(check.value)} <span className="unit">{check.unit}</span>
                    </td>
                    <td className="num lab-check-bound">{check.tolerance === null ? "" : `≤ ${formatSmall(check.tolerance)}`}</td>
                    <td className="lab-check-status">{check.status.toUpperCase()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {metrics.length > 0 ? (
            <table className="lab-table lab-check-table" aria-label="Benchmark metrics">
              <caption>Benchmark metrics (assessment)</caption>
              <colgroup>
                <col className="seal" />
                <col />
                <col className="value" />
                <col className="bound" />
                <col className="status" />
              </colgroup>
              <tbody>
                {metrics.map((metric) => (
                  <tr key={metric.metric_id} data-status={checkStatus(metric.status)} data-criterion={metric.metric_id} title={metric.description}>
                    <td className="lab-check-seal">
                      <Seal status={checkStatus(metric.status)} />
                    </td>
                    <th scope="row">
                      {metric.label}
                      <small>
                        {metric.metric_id} · {metric.aggregation} of {metric.quantity_id}
                      </small>
                    </th>
                    <td className="num">
                      {metric.value === null ? "—" : formatSmall(metric.value)} <span className="unit">{metric.unit}</span>
                    </td>
                    <td className="num lab-check-bound">
                      {metric.operator === null || metric.threshold === null ? "reported" : `${OPERATORS[metric.operator] ?? metric.operator} ${formatSmall(metric.threshold)}`}
                    </td>
                    <td className="lab-check-status">{metric.status === "reported" ? "REP." : metric.status.toUpperCase()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {evidence.adapter_checks.length > 0 ? (
            <table className="lab-table lab-check-table" aria-label="Adapter checks">
              <caption>Adapter checks of the repetition</caption>
              <colgroup>
                <col className="seal" />
                <col />
                <col className="value" />
                <col className="bound" />
                <col className="status" />
              </colgroup>
              <tbody>
                {evidence.adapter_checks.map((check) => (
                  <tr key={check.criterion_id} data-status={checkStatus(check.status)} data-criterion={check.criterion_id} title={check.rationale}>
                    <td className="lab-check-seal">
                      <Seal status={checkStatus(check.status)} />
                    </td>
                    <th scope="row">
                      {check.label}
                      <small>{check.rationale}</small>
                    </th>
                    <td className="num">
                      {check.value === null ? "—" : formatSmall(check.value)} <span className="unit">{check.unit}</span>
                    </td>
                    <td className="num lab-check-bound">{check.bound}</td>
                    <td className="lab-check-status">{check.status === "not_evaluated" ? "N/E" : check.status.toUpperCase()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {evidence.failure !== null ? <p className="lab-refusal">{evidence.failure}</p> : null}
        </section>

        <section className="lab-card lab-colophon" aria-labelledby="run-colophon-title">
          <h2 id="run-colophon-title" className="lab-card-title lab-display">
            Colophon
          </h2>
          <h3 className="lab-rubric">Claim</h3>
          <p>{evidence.claim ?? "No claim could be read from this run."}</p>
          <h3 className="lab-rubric">Limitations</h3>
          <ul>
            {LIMITATIONS.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
          <h3 className="lab-rubric">Reproduce</h3>
          <pre className="lab-code">{`cd python
uv run python tools/mujoco_squat_authority.py \
  --workspace <directory>
# then, in the workbench: open the workspace,
# Study & Runs → case ${evidence.case_id ?? "custom"} → Preflight → Execute.
# The same configuration reproduces trajectory
# ${provenance?.trajectory_sha256 === null || provenance === null ? "—" : shortDigest(provenance.trajectory_sha256, 16)}… bit for bit.`}</pre>
        </section>
      </div>

      <div className="lab-bundles">
        <BundleCard title="Execution bundle" bundle={evidence.execution} pigment="sanguine" />
        <BundleCard title="Derived bundle" bundle={evidence.derived} pigment="verdigris" />
      </div>
    </div>
  );
}

const OPERATORS: Record<string, string> = {
  less: "<",
  less_or_equal: "≤",
  equal: "=",
  not_equal: "≠",
  greater_or_equal: "≥",
  greater: ">",
};

function formatSmall(value: number): string {
  if (value === 0) {
    return "0";
  }
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e5) {
    return value.toExponential(2).replace("-", "−");
  }
  return formatNumber(value, magnitude >= 100 ? 1 : magnitude >= 10 ? 2 : 3);
}
