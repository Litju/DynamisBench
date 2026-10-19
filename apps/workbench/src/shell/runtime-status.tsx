/**
 * The runtime status surface: the shell's answer to "is there an API, and is it usable?".
 *
 * It is the one place the frontend asks the application anything on its own, and it asks
 * exactly one question — `GET /api/v1/info` — through the session's typed client. Every
 * other surface in this milestone is chrome.
 *
 * The read and the session are deliberately separate inputs to [`runtimeState`]: a session
 * that is ready and an API that is being read are two different facts, and the states that
 * describe them are different states.
 */

import { useQuery } from "@tanstack/react-query";

import { apiQueryKeys } from "../api/queries";
import { useSession } from "../session/provider";
import { Badge } from "../ui/badge";
import { cn } from "../ui/cn";
import { runtimeState, type InfoState } from "./runtime-state";

export function RuntimeStatus({ className }: { className?: string }) {
  const { session, client } = useSession();

  const query = useQuery({
    queryKey: apiQueryKeys.info(),
    queryFn: () => {
      if (client === null) {
        throw new Error("the session provides no API client");
      }
      return client.info();
    },
    enabled: client !== null,
  });

  const state = runtimeState(session, infoStateOf(query.status, query.data, query.error));

  return (
    <div
      data-runtime-state={state.id}
      className={cn("flex min-w-0 items-center gap-3", className)}
    >
      <Badge tone={state.tone}>{state.label}</Badge>
      <p className="truncate text-xs text-slate-500">{state.detail}</p>
    </div>
  );
}

function infoStateOf(
  status: "pending" | "error" | "success",
  data: { application: string; version: string; api_version: string } | undefined,
  error: unknown,
): InfoState {
  if (status === "success" && data !== undefined) {
    return {
      status: "success",
      application: data.application,
      version: data.version,
      apiVersion: data.api_version,
    };
  }

  if (status === "error") {
    return { status: "error", error };
  }

  return { status: "pending" };
}
