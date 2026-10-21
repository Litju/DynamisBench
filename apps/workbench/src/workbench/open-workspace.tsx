/**
 * The explicit open-workspace flow: two roots, one command, one opaque identifier.
 *
 * The roots are the only operational paths the workbench ever accepts, and they are held in
 * component state for exactly as long as the form is on screen: there is no localStorage,
 * no query parameter, no router context and no log. A successful open clears both inputs
 * before navigating, so returning to this route starts empty rather than replaying a path.
 *
 * The request is the typed client's `openWorkspace` mutation. No other module builds it, and
 * everything after it identifies the workspace by the opaque identifier the application
 * returned.
 */

import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { FolderOpen } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiClientError } from "../api/errors";
import { openWorkspaceOptions } from "../api/queries";
import type { ApiClient } from "../api/client";
import { Button } from "../ui/button";

export function OpenWorkspaceForm({ client }: { client: ApiClient }) {
  const navigate = useNavigate();
  const [sourceRoot, setSourceRoot] = useState("");
  const [evidenceRoot, setEvidenceRoot] = useState("");
  const open = useMutation(openWorkspaceOptions(client));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sourceRoot.trim() === "" || evidenceRoot.trim() === "") {
      return;
    }

    open.mutate(
      { sourceRoot, evidenceRoot },
      {
        onSuccess: (workspace) => {
          setSourceRoot("");
          setEvidenceRoot("");
          open.reset();
          void navigate({
            to: "/workspace/$workspaceId",
            params: { workspaceId: workspace.workspace_id },
          });
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-describedby="open-help">
      <p id="open-help" className="text-sm text-slate-600">
        Choose an existing repository and its evidence directory. The application reads them
        and returns an opaque workspace identifier; neither path is stored or published.
      </p>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-slate-700">Source root</span>
        <input
          type="text"
          value={sourceRoot}
          onChange={(event) => setSourceRoot(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-slate-700">Evidence root</span>
        <input
          type="text"
          value={evidenceRoot}
          onChange={(event) => setEvidenceRoot(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
        />
      </label>

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          size="icon"
          disabled={open.isPending || sourceRoot.trim() === "" || evidenceRoot.trim() === ""}
          className="w-auto px-3"
        >
          <FolderOpen aria-hidden className="h-4 w-4" />
          {open.isPending ? "Opening…" : "Open workspace"}
        </Button>
        {open.isError && (
          <p role="alert" className="min-w-0 text-xs text-rose-700">
            {openFailure(open.error)}
          </p>
        )}
      </div>
    </form>
  );
}

/**
 * A bounded explanation of a failed open.
 *
 * The application's own envelope message is used when it produced one; every other failure
 * is described by this client's fixed vocabulary. The rejected roots never appear: the client
 * never retained them in an error and this text does not read them back out of the form.
 */
function openFailure(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.kind === "http") {
      return error.apiMessage ?? "The declared workspace roots could not be opened.";
    }
    return error.message;
  }
  return "The workspace could not be opened.";
}
