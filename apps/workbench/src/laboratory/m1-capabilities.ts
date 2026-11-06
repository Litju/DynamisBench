/**
 * M1 is the source-preserving, read-only Laboratory integration.
 *
 * The VM's RunSpec/preflight/start/cancel interface remains in the source tree for the later
 * approved execution phase, but this production route must not call it until the repository
 * accepts the native-evidence and run-service contracts (RES-555/561/569).
 */
export const LIVE_WORKSPACE_RUN_API_AVAILABLE = false;

export const LIVE_WORKSPACE_RUN_API_UNAVAILABLE_MESSAGE =
  "Workspace study catalogues, preflight, execution, cancellation and sealed workspace-run readback are not enabled in this M1 read-only integration. The packaged diagnostic recordings remain available; they are not workspace runs or sealed evidence.";
