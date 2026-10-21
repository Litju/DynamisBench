/**
 * A validated definition, rendered as structure rather than as text.
 *
 * `ArtifactInspectionResponse.content` is the domain model serialised in JSON mode, so it is
 * already meaning that passed validation. This component presents that meaning read-only:
 * objects and arrays open into labelled children, scalars are rendered as values, and null is
 * rendered as the word `null` rather than as an empty string. There is no textarea, no
 * contenteditable, no editor and no control that could write back.
 *
 * The tree is a set of semantic lists and disclosure elements, so it is navigable with the
 * keyboard the browser already provides. Nested containers start collapsed below the first
 * level; a person opens what they need instead of receiving a wall of JSON.
 */

const MAX_DEPTH = 12;

export function ArtifactContent({ content }: { content: Record<string, unknown> }) {
  return (
    <div className="text-sm" data-testid="artifact-content">
      <ValueNode label={null} value={content} depth={0} />
    </div>
  );
}

function ValueNode({
  label,
  value,
  depth,
}: {
  label: string | null;
  value: unknown;
  depth: number;
}) {
  if (value === null) {
    return <ScalarRow label={label} value="null" muted />;
  }

  if (Array.isArray(value)) {
    return (
      <ContainerNode
        label={label}
        count={value.length}
        noun="item"
        depth={depth}
        open={depth === 0}
      >
        {value.map((entry, index) => (
          <ValueNode key={index} label={`[${index}]`} value={entry} depth={depth + 1} />
        ))}
      </ContainerNode>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <ContainerNode
        label={label}
        count={entries.length}
        noun="field"
        depth={depth}
        open={depth === 0}
      >
        {entries.map(([key, entry]) => (
          <ValueNode key={key} label={key} value={entry} depth={depth + 1} />
        ))}
      </ContainerNode>
    );
  }

  if (typeof value === "string") {
    return <ScalarRow label={label} value={value} />
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return <ScalarRow label={label} value={String(value)} />
  }

  return <ScalarRow label={label} value="(unsupported value)" muted />;
}

function ContainerNode({
  label,
  count,
  noun,
  depth,
  open,
  children,
}: {
  label: string | null;
  count: number;
  noun: string;
  depth: number;
  open: boolean;
  children: React.ReactNode;
}) {
  const summary = `${count} ${noun}${count === 1 ? "" : "s"}`;

  if (depth >= MAX_DEPTH) {
    return (
      <div className="py-0.5">
        <span className="text-slate-500">{label ?? "value"}</span>
        <span className="ml-2 text-xs text-slate-400">nested content beyond the display depth</span>
      </div>
    );
  }

  return (
    <details open={open} className="group py-0.5">
      <summary className="cursor-pointer select-none rounded px-1 py-0.5 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400">
        {label !== null && <span className="font-medium text-slate-700">{label}</span>}
        <span className={label === null ? "text-slate-500" : "ml-2 text-xs text-slate-400"}>
          {summary}
        </span>
      </summary>
      <div className="ml-4 border-l border-slate-200 pl-3">{children}</div>
    </details>
  );
}

function ScalarRow({
  label,
  value,
  muted = false,
}: {
  label: string | null;
  value: string;
  muted?: boolean;
}) {
  return (
    <div className="flex min-w-0 gap-2 py-0.5">
      {label !== null && (
        <span className="shrink-0 font-medium text-slate-600">{label}</span>
      )}
      <code
        className={
          muted
            ? "min-w-0 whitespace-pre-wrap break-words text-xs text-slate-400"
            : "min-w-0 whitespace-pre-wrap break-words text-xs text-slate-800"
        }
      >
        {value}
      </code>
    </div>
  );
}
