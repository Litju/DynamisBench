/**
 * Folio I · Study & Runs: the researcher's workflow over a workspace study.
 *
 * Select the study (the model it realizes is the workspace's validated realization), configure
 * its factors in display units, preflight, execute, follow the run, and find every run of the
 * workspace with what reading it back established. The folio *asks* the application's run
 * service and renders its answers: planning, admission, execution in the isolated worker,
 * sealing, normalization, verification and assessment all happen behind the API, and a run is
 * only ever shown as a result after it has been read back from its seals.
 *
 * Execution is offered only for a configuration that the service has just preflighted as ready
 * — the same study and the same doubles. Anything the service refuses is shown with its reason;
 * nothing is retried, clipped or substituted.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiClientError } from "../api/errors";
import {
  apiQueryKeys,
  cancelRunOptions,
  preflightRunOptions,
  runProgressOptions,
  startRunOptions,
  studyCatalogueOptions,
} from "../api/queries";
import type {
  CatalogueFactor,
  CatalogueStudy,
  PreflightResponse,
  RunConfigurationRequest,
  RunEntry,
  RunProgressResponse,
} from "../api/run-types";
import {
  DISPLAY_UNITS,
  describeConfiguration,
  displayDigits,
  factorProblem,
  formatDisplay,
  fromDisplay,
  matchingPreset,
  nominalDraft,
  parseDisplay,
  presetValues,
  sameConfiguration,
  toDisplay,
} from "./configuration";
import { useLabData } from "./data";
import { formatNumber, shortDigest } from "./series";
import { sameRef } from "./sources";
import { useLaboratoryStore, type RunDraft } from "./store";
import {
  LIVE_WORKSPACE_RUN_API_AVAILABLE,
  LIVE_WORKSPACE_RUN_API_UNAVAILABLE_MESSAGE,
} from "./m1-capabilities";

/** The stages a run passes through, in order, as the progress read model names them. */
const PIPELINE = [
  { state: "planning", label: "Plan" },
  { state: "preflight", label: "Materialize & preflight" },
  { state: "starting", label: "Start worker" },
  { state: "running", label: "Forward dynamics" },
  { state: "sealing", label: "Seal execution" },
  { state: "deriving", label: "Normalize · verify · assess" },
  { state: "completed", label: "Sealed & verified" },
] as const;

function describeError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.apiMessage ?? error.message;
  }
  return "The request could not be completed.";
}

export function StudyFolio() {
  const { workspaceId } = useLabData();
  if (workspaceId === null) {
    return <NoWorkspace />;
  }
  if (!LIVE_WORKSPACE_RUN_API_AVAILABLE) {
    return <WorkspaceStudyUnavailable />;
  }
  return <WorkspaceStudy workspaceId={workspaceId} />;
}

function WorkspaceStudyUnavailable() {
  const setFolio = useLaboratoryStore((state) => state.setFolio);
  return (
    <div className="lab-folio lab-study">
      <section className="lab-card lab-study-empty" aria-labelledby="m1-study-unavailable-title">
        <h2 id="m1-study-unavailable-title" className="lab-card-title lab-display">
          Workspace execution is not enabled in this integration phase
        </h2>
        <p>{LIVE_WORKSPACE_RUN_API_UNAVAILABLE_MESSAGE}</p>
        <p>
          <button type="button" className="lab-link-button" onClick={() => setFolio("laboratory")}>
            Open the packaged Laboratory recordings
          </button>
        </p>
      </section>
    </div>
  );
}

function NoWorkspace() {
  return (
    <div className="lab-folio lab-study">
      <section className="lab-card lab-study-empty" aria-labelledby="study-empty-title">
        <h2 id="study-empty-title" className="lab-card-title lab-display">
          No workspace is bound to the laboratory
        </h2>
        <p>
          Studies are source documents of a workspace, and runs are sealed into that workspace&apos;s evidence root. Open a workspace
          that contains a study, then choose <em>Open in the laboratory</em> in its Simulation Laboratory mode.
        </p>
        <p className="lab-marginal">
          M1 publishes the packaged diagnostic back-squat recordings only. Workspace study
          authoring and execution remain unavailable until their production authority is accepted.
        </p>
        <p>
          <Link to="/" className="lab-link">
            Open a workspace
          </Link>
        </p>
      </section>
    </div>
  );
}

function WorkspaceStudy({ workspaceId }: { workspaceId: string }) {
  const { client } = useLabData();
  const catalogue = useQuery(studyCatalogueOptions(client, workspaceId));
  const draft = useLaboratoryStore((state) => state.draft);
  const setDraft = useLaboratoryStore((state) => state.setDraft);
  const studies = catalogue.data?.studies ?? [];
  const study = studies.find((entry) => entry.study_id === draft?.studyId) ?? studies[0];

  // Start from the first study's nominal configuration.
  useEffect(() => {
    if (study !== undefined && (draft === null || draft.studyId !== study.study_id)) {
      setDraft(nominalDraft(study));
    }
  }, [study, draft, setDraft]);

  if (catalogue.isError) {
    return (
      <div className="lab-folio lab-study">
        <section className="lab-card" role="alert">
          <h2 className="lab-card-title lab-display">The workspace&apos;s studies could not be read</h2>
          <p>{describeError(catalogue.error)}</p>
        </section>
      </div>
    );
  }
  if (catalogue.data === undefined) {
    return (
      <div className="lab-folio lab-study" aria-busy="true">
        <p className="lab-marginal">reading the workspace&apos;s studies…</p>
      </div>
    );
  }
  if (study === undefined) {
    return (
      <div className="lab-folio lab-study">
        <section className="lab-card" role="status">
          <h2 className="lab-card-title lab-display">This workspace has no valid study</h2>
          <p>
            {catalogue.data.invalid_documents > 0
              ? `${catalogue.data.invalid_documents} source document(s) did not validate; inspect them in the workspace.`
              : "Add a study source document that names an executable realization."}
          </p>
        </section>
        <RunsRegister workspaceId={workspaceId} study={undefined} />
      </div>
    );
  }
  return (
    <div className="lab-folio lab-study">
      <div className="lab-study-grid">
        <StudyCard studies={studies} study={study} invalid={catalogue.data.invalid_documents} />
        {draft !== null && draft.studyId === study.study_id ? (
          <>
            <ConfigurationCard study={study} draft={draft} />
            <ExecutionCard workspaceId={workspaceId} study={study} draft={draft} />
          </>
        ) : null}
      </div>
      <RunsRegister workspaceId={workspaceId} study={study} />
    </div>
  );
}

function StudyCard({
  studies,
  study,
  invalid,
}: {
  studies: readonly CatalogueStudy[];
  study: CatalogueStudy;
  invalid: number;
}) {
  const setDraft = useLaboratoryStore((state) => state.setDraft);
  return (
    <section className="lab-card lab-study-card" aria-labelledby="study-title">
      <h2 id="study-title" className="lab-card-title lab-display">
        Study &amp; model
      </h2>
      <label className="lab-field">
        <span>Study</span>
        <select
          aria-label="Study"
          value={study.study_id}
          onChange={(event) => {
            const next = studies.find((entry) => entry.study_id === event.target.value);
            if (next !== undefined) setDraft(nominalDraft(next));
          }}
        >
          {studies.map((entry) => (
            <option key={entry.study_id} value={entry.study_id}>
              {entry.label} · {entry.study_id}@{entry.version}
            </option>
          ))}
        </select>
      </label>
      <p className="lab-study-question">{study.research_question}</p>
      <dl className="lab-facts">
        <div>
          <dt>Realization (model)</dt>
          <dd>
            {study.realization.label}
            <small>
              {study.realization.identifier}@{study.realization.version}
            </small>
          </dd>
        </div>
        <div>
          <dt>Environment</dt>
          <dd>
            {study.environment || "—"}
            <small>platform {study.platform || "—"}</small>
          </dd>
        </div>
        <div>
          <dt>Executable here</dt>
          <dd data-executable={study.executable}>{study.executable ? "yes — reviewed adapter, provisioned worker" : `no — ${study.reason}`}</dd>
        </div>
        {invalid > 0 ? (
          <div>
            <dt>Invalid documents</dt>
            <dd>{invalid} not loaded</dd>
          </div>
        ) : null}
      </dl>
      <h3 className="lab-rubric">Scientific limitations</h3>
      <ul className="lab-limitations">
        {study.limitations.map((limitation) => (
          <li key={limitation}>{limitation}</li>
        ))}
      </ul>
    </section>
  );
}

function ConfigurationCard({ study, draft }: { study: CatalogueStudy; draft: RunDraft }) {
  const setDraft = useLaboratoryStore((state) => state.setDraft);
  const preset = matchingPreset(study, draft.values);
  return (
    <section className="lab-card lab-config-card" aria-labelledby="config-title">
      <h2 id="config-title" className="lab-card-title lab-display">
        Configuration
      </h2>
      <p className="lab-marginal">values are sent in canonical units; ranges are the study&apos;s qualified domain</p>
      <div className="lab-presets" role="group" aria-label="Presets">
        {Object.keys(study.presets).map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={preset === name}
            onClick={() => setDraft({ studyId: study.study_id, caseId: name, values: presetValues(study, name) })}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="lab-factors">
        {study.factors.map((factor) => (
          <FactorField
            key={factor.factor_id}
            factor={factor}
            value={draft.values[factor.factor_id]}
            onChange={(value) => {
              const values = { ...draft.values, [factor.factor_id]: value };
              setDraft({ studyId: study.study_id, caseId: matchingPreset(study, values), values });
            }}
          />
        ))}
      </div>
    </section>
  );
}

function FactorField({
  factor,
  value,
  onChange,
}: {
  factor: CatalogueFactor;
  value: number | undefined;
  onChange: (value: number) => void;
}) {
  const unit = DISPLAY_UNITS[factor.display];
  const id = `factor-${factor.factor_id.replace(/[^A-Za-z0-9]/g, "-")}`;
  const [text, setText] = useState(value === undefined ? "" : formatDisplay(factor, value));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused && value !== undefined) {
      setText(formatDisplay(factor, value));
    }
  }, [factor, value, focused]);
  const problem = factorProblem(factor, value);
  // The slider moves in readable display steps; its two ends are the domain's exact bounds.
  const digits = displayDigits(factor.display);
  const lower = Number(toDisplay(factor.display, factor.lower).toFixed(digits));
  const upper = Number(toDisplay(factor.display, factor.upper).toFixed(digits));
  const fromSlider = (shown: number) =>
    shown <= lower ? factor.lower : shown >= upper ? factor.upper : fromDisplay(factor.display, shown);
  const step = 10 ** -displayDigits(factor.display) * (factor.display === "degree" ? 5 : factor.display === "second" ? 5 : 1);

  return (
    <div className="lab-factor" data-invalid={problem !== null}>
      <label htmlFor={id}>{factor.label}</label>
      <small id={`${id}-domain`} className="lab-factor-domain">
        {factor.factor_id} · {formatDisplay(factor, factor.lower)}–{formatDisplay(factor, factor.upper)}
        {unit === "" ? "" : ` ${unit}`} · nominal {formatDisplay(factor, factor.nominal)}
        {unit === "" ? "" : ` ${unit}`}
      </small>
      {factor.choices.length > 0 ? (
        <select
          id={id}
          aria-describedby={`${id}-domain`}
          value={value === undefined ? "" : String(value)}
          onChange={(event) => {
            const chosen = factor.choices.find((choice) => String(choice) === event.target.value);
            if (chosen !== undefined) onChange(chosen);
          }}
        >
          {factor.choices.map((choice) => (
            <option key={choice} value={String(choice)}>
              {formatDisplay(factor, choice)} {unit}
              {factor.display === "millisecond" ? ` · ${Math.round(0.01 / choice)} steps per 10 ms sample` : ""}
            </option>
          ))}
        </select>
      ) : (
        <div className="lab-factor-inputs">
          <input
            type="range"
            aria-label={`${factor.label} slider`}
            min={lower}
            max={upper}
            step={step}
            value={value === undefined || !Number.isFinite(value) ? lower : Math.min(upper, Math.max(lower, toDisplay(factor.display, value)))}
            onChange={(event) => {
              const parsed = parseDisplay(event.target.value);
              if (parsed !== null) onChange(fromSlider(parsed));
            }}
          />
          <input
            id={id}
            type="text"
            inputMode="decimal"
            spellCheck={false}
            value={text}
            aria-invalid={problem !== null}
            aria-describedby={problem === null ? `${id}-domain` : `${id}-domain ${id}-problem`}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onChange={(event) => {
              setText(event.target.value);
              const parsed = parseDisplay(event.target.value);
              onChange(parsed === null ? Number.NaN : fromDisplay(factor.display, parsed));
            }}
          />
          <span className="lab-factor-unit">{unit}</span>
        </div>
      )}
      {problem !== null ? (
        <p id={`${id}-problem`} className="lab-factor-problem">
          {problem}
        </p>
      ) : null}
    </div>
  );
}

function requestOf(draft: RunDraft): RunConfigurationRequest {
  return { study_id: draft.studyId, case_id: draft.caseId, values: draft.values };
}

function ExecutionCard({ workspaceId, study, draft }: { workspaceId: string; study: CatalogueStudy; draft: RunDraft }) {
  const { client } = useLabData();
  const queryClient = useQueryClient();
  const activeRunId = useLaboratoryStore((state) => state.activeRunId);
  const setActiveRun = useLaboratoryStore((state) => state.setActiveRun);
  const preflight = useMutation(preflightRunOptions(client, workspaceId));
  const start = useMutation(startRunOptions(client, workspaceId));
  const cancel = useMutation(cancelRunOptions(client, workspaceId));
  const progress = useQuery({
    ...(activeRunId === null
      ? {
          queryKey: apiQueryKeys.runProgress(workspaceId, "none"),
          queryFn: (): Promise<RunProgressResponse> => Promise.reject(new Error("no run")),
        }
      : runProgressOptions(client, workspaceId, activeRunId)),
    enabled: activeRunId !== null,
  });

  const problems = study.factors.map((factor) => factorProblem(factor, draft.values[factor.factor_id])).filter((p) => p !== null);
  const request = requestOf(draft);
  const checked = preflight.variables;
  const current =
    checked !== undefined &&
    checked.study_id === request.study_id &&
    sameConfiguration(checked.values, request.values) &&
    preflight.data !== undefined;
  const active = progress.data?.active === true || start.isPending;
  const canExecute = study.executable && current && preflight.data?.decision === "ready" && !active;

  // When the run stops, every list that names it is read again from the evidence.
  const finished = progress.data !== undefined && !progress.data.active;
  useEffect(() => {
    if (finished) {
      void queryClient.invalidateQueries({ queryKey: apiQueryKeys.runs(workspaceId) });
    }
  }, [finished, queryClient, workspaceId]);

  return (
    <section className="lab-card lab-exec-card" aria-labelledby="exec-title">
      <h2 id="exec-title" className="lab-card-title lab-display">
        Preflight &amp; execution
      </h2>
      <p className="lab-marginal">{describeConfiguration(study.factors, draft.values)}</p>
      <div className="lab-exec-actions">
        <button
          type="button"
          className="lab-action"
          disabled={!study.executable || problems.length > 0 || preflight.isPending}
          onClick={() => preflight.mutate(request)}
        >
          {preflight.isPending ? "Preflighting…" : "Preflight"}
        </button>
        <button
          type="button"
          className="lab-action lab-action-primary"
          disabled={!canExecute}
          title={canExecute ? undefined : "Execution is offered for a configuration that has just preflighted as ready."}
          onClick={() => {
            // The previous run's progress is not this one's.
            setActiveRun(null);
            start.mutate(request, {
              onSuccess: (started) => {
                setActiveRun(started.run_id);
                void queryClient.invalidateQueries({ queryKey: apiQueryKeys.runs(workspaceId) });
              },
            });
          }}
        >
          {start.isPending ? "Starting…" : "Execute run"}
        </button>
        <button
          type="button"
          className="lab-action"
          disabled={!(progress.data?.active === true) || cancel.isPending}
          onClick={() => activeRunId !== null && cancel.mutate(activeRunId)}
        >
          Cancel
        </button>
      </div>
      {problems.length > 0 ? (
        <p className="lab-factor-problem" role="status">
          {problems.length} value{problems.length === 1 ? "" : "s"} outside the qualified domain — correct before preflight.
        </p>
      ) : null}
      {preflight.isError ? (
        <PreflightRefusal message={describeError(preflight.error)} stale={!current && checked !== undefined} />
      ) : preflight.data !== undefined ? (
        <PreflightReport report={preflight.data} stale={!current} />
      ) : (
        <p className="lab-note">Preflight plans the configuration against the workspace&apos;s validated definitions, asks the worker environment for its implementation identity and asks the execution boundary to admit the run (the model asset&apos;s digest included). Nothing is materialized, started or sealed; execution repeats the admission on the materialized inputs.</p>
      )}
      {start.isError ? (
        <p className="lab-refusal" role="alert">
          The run was not started: {describeError(start.error)}
        </p>
      ) : null}
      {activeRunId !== null ? <RunProgressView runId={activeRunId} progress={progress.data} error={progress.error} /> : null}
    </section>
  );
}

function PreflightRefusal({ message, stale }: { message: string; stale: boolean }) {
  return (
    <div className="lab-preflight" data-decision="refused" data-stale={stale}>
      <p className="lab-decision">
        <strong>Refused before admission</strong>
        {stale ? <span> · for an earlier configuration</span> : null}
      </p>
      <p className="lab-refusal" role="alert">
        {message}
      </p>
    </div>
  );
}

function Digest({ value, label }: { value: string | null; label?: string }) {
  if (value === null) {
    return <span className="lab-digest">—</span>;
  }
  return (
    <span className="lab-digest" title={value} aria-label={label === undefined ? value : `${label} ${value}`}>
      {shortDigest(value, 12)}…
    </span>
  );
}

function PreflightReport({ report, stale }: { report: PreflightResponse; stale: boolean }) {
  return (
    <div className="lab-preflight" data-decision={report.decision} data-stale={stale} aria-label="Preflight report">
      <p className="lab-decision" role="status">
        <strong>{report.decision === "ready" ? "Ready — admitted by preflight" : "Refused by preflight"}</strong>
        {stale ? <span> · for an earlier configuration; preflight again</span> : null}
      </p>
      {report.refusals.length > 0 ? (
        <ul className="lab-refusals">
          {report.refusals.map((refusal) => (
            <li key={`${refusal.code}-${refusal.message}`}>
              <code>{refusal.code}</code> {refusal.message}
            </li>
          ))}
        </ul>
      ) : null}
      <table className="lab-table lab-identity-table">
        <caption>Identities the run would execute</caption>
        <tbody>
          <tr>
            <th scope="row">Study</th>
            <td>
              {report.study.identifier}@{report.study.version}
            </td>
            <td className="num">
              <Digest value={report.study.semantic_digest} />
            </td>
          </tr>
          {Object.entries(report.definitions).map(([kind, definition]) => (
            <tr key={kind}>
              <th scope="row">{kind.replace(/_/g, " ")}</th>
              <td>
                {definition.identifier}@{definition.version}
              </td>
              <td className="num">
                <Digest value={definition.semantic_digest} />
              </td>
            </tr>
          ))}
          <tr>
            <th scope="row">Adapter</th>
            <td>
              {report.adapter.adapter_id}@{report.adapter.adapter_version} · {report.adapter.engine} {report.adapter.engine_version} · CPython{" "}
              {report.adapter.python_version} · {report.adapter.platform}
            </td>
            <td className="num">
              <Digest value={report.adapter.implementation_digest} label="implementation" />
            </td>
          </tr>
          <tr>
            <th scope="row">Dependency closure</th>
            <td>locked worker environment</td>
            <td className="num">
              <Digest value={report.adapter.dependency_closure_digest} />
            </td>
          </tr>
          <tr>
            <th scope="row">Execution fingerprint</th>
            <td>RunSpec with this configuration</td>
            <td className="num">
              <Digest value={report.execution_fingerprint} />
            </td>
          </tr>
          <tr>
            <th scope="row">Request digest</th>
            <td>timeout {formatNumber(report.timeout_seconds, 0)} s</td>
            <td className="num">
              <Digest value={report.request_digest} />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function RunProgressView({
  runId,
  progress,
  error,
}: {
  runId: string;
  progress: RunProgressResponse | undefined;
  error: unknown;
}) {
  const setRecording = useLaboratoryStore((state) => state.setRecording);
  const setFolio = useLaboratoryStore((state) => state.setFolio);
  const inspectEvidence = useLaboratoryStore((state) => state.inspectEvidence);
  const { entries } = useLabData();
  const entry = entries.find((candidate) => sameRef(candidate.ref, { source: "run", id: runId }));
  if (progress === undefined) {
    return (
      <div className="lab-progress" aria-live="polite">
        <p className="lab-marginal">{error === null ? `reading the progress of ${runId}…` : `the progress of ${runId} could not be read: ${describeError(error)}`}</p>
      </div>
    );
  }
  const reached = PIPELINE.findIndex((stage) => stage.state === progress.state);
  const terminal = !progress.active;
  return (
    <div className="lab-progress" aria-label="Run progress" aria-live="polite" data-state={progress.state}>
      <p className="lab-decision">
        <strong>{runId}</strong> · {progress.state.replace("_", " ")} · {formatNumber(progress.elapsed_s, 1)} s
      </p>
      <ol className="lab-pipeline">
        {PIPELINE.map((stage, i) => {
          const done = terminal ? progress.state === "completed" || i < reached : i < reached;
          const current = !terminal && i === reached;
          return (
            <li key={stage.state} data-done={done} data-current={current}>
              {stage.label}
            </li>
          );
        })}
      </ol>
      {progress.message !== "" ? <p className="lab-note">{progress.message}</p> : null}
      {progress.refusals.length > 0 ? (
        <ul className="lab-refusals">
          {progress.refusals.map((refusal) => (
            <li key={`${refusal.code}-${refusal.message}`}>
              <code>{refusal.code}</code> {refusal.message}
            </li>
          ))}
        </ul>
      ) : null}
      {terminal ? (
        <div className="lab-exec-actions">
          <button
            type="button"
            className="lab-action lab-action-primary"
            disabled={entry?.playable !== true}
            onClick={() => {
              setRecording({ source: "run", id: runId });
              setFolio("laboratory");
            }}
          >
            Open in Laboratory
          </button>
          <button
            type="button"
            className="lab-action"
            onClick={() => {
              inspectEvidence(runId);
              setFolio("record");
            }}
          >
            Inspect evidence
          </button>
          {entry !== undefined ? <span className="lab-note">read back: {entry.status}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

function counts(run: RunEntry, kind: "verification" | "metrics" | "checks"): ReactNode {
  const c = run[kind];
  if (c.pass + c.fail + c.not_evaluated + c.reported === 0) {
    return "—";
  }
  return (
    <span data-fail={c.fail > 0}>
      {c.pass}✓{c.fail > 0 ? ` ${c.fail}✗` : ""}
      {c.not_evaluated > 0 ? ` ${c.not_evaluated} n/e` : ""}
      {c.reported > 0 ? ` ${c.reported} rep.` : ""}
    </span>
  );
}

function RunsRegister({ workspaceId, study }: { workspaceId: string; study: CatalogueStudy | undefined }) {
  const { entries, ref } = useLabData();
  const setRecording = useLaboratoryStore((state) => state.setRecording);
  const setCompare = useLaboratoryStore((state) => state.setCompare);
  const setFolio = useLaboratoryStore((state) => state.setFolio);
  const inspectEvidence = useLaboratoryStore((state) => state.inspectEvidence);
  const runs = useMemo(() => entries.filter((entry) => entry.run !== null), [entries]);
  return (
    <section className="lab-card lab-runs-card" aria-labelledby="runs-title">
      <h2 id="runs-title" className="lab-card-title lab-display">
        Runs of this workspace
      </h2>
      <p className="lab-marginal">
        every sealed run, re-verified from its execution and derived bundles on every read · workspace {shortDigest(workspaceId, 8)}…
      </p>
      {runs.length === 0 ? (
        <p className="lab-note">No run has been sealed in this workspace yet.</p>
      ) : (
        <table className="lab-table lab-runs-table" aria-label="Runs">
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Configuration</th>
              <th scope="col">Read back</th>
              <th scope="col" className="num">
                Verification
              </th>
              <th scope="col" className="num">
                Metrics
              </th>
              <th scope="col" className="num">
                Checks
              </th>
              <th scope="col">Trajectory</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {runs.map((entry) => {
              const run = entry.run as RunEntry;
              return (
                <tr key={run.run_id} data-status={run.status} data-selected={sameRef(entry.ref, ref)}>
                  <th scope="row">
                    <code>{run.run_id}</code>
                    <small>{run.case_id || "—"}</small>
                  </th>
                  <td className="lab-runs-config">{study === undefined ? "" : describeConfiguration(study.factors, run.configuration)}</td>
                  <td>
                    <span className="lab-run-status" data-status={run.status}>
                      {run.status.replace("_", " ")}
                    </span>
                    {run.reasons.length > 0 ? <small title={run.reasons.join("\n")}>{run.reasons[0]}</small> : null}
                  </td>
                  <td className="num">{counts(run, "verification")}</td>
                  <td className="num">{counts(run, "metrics")}</td>
                  <td className="num">{counts(run, "checks")}</td>
                  <td>
                    <Digest value={run.trajectory_sha256} label="trajectory" />
                  </td>
                  <td className="lab-runs-actions">
                    <button
                      type="button"
                      disabled={!entry.playable}
                      onClick={() => {
                        setRecording(entry.ref);
                        setFolio("laboratory");
                      }}
                      aria-label={`Play ${run.run_id}`}
                    >
                      Play
                    </button>
                    <button
                      type="button"
                      disabled={!entry.playable || sameRef(entry.ref, ref)}
                      onClick={() => {
                        setCompare(entry.ref);
                        setFolio("analysis");
                      }}
                      aria-label={`Compare with ${run.run_id}`}
                    >
                      Compare
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        inspectEvidence(run.run_id);
                        setFolio("record");
                      }}
                      aria-label={`Evidence of ${run.run_id}`}
                    >
                      Evidence
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="lab-table-note">
        Verification: independent numerical checks of the canonical series. Metrics: the benchmark release&apos;s predeclared criteria
        (rep. = reported, no criterion). Checks: the adapter&apos;s predeclared checks of the repetition. None of these is validation
        against measured human motion.
      </p>
    </section>
  );
}
