/**
 * The anatomical figure as a server read: fetched once per session through the typed client and
 * decoded here (the client never interprets the stream).
 */

import { queryOptions } from "@tanstack/react-query";

import type { ApiClient } from "../../api/client";
import { LABORATORY_QUERY_TIMING, apiQueryKeys } from "../../api/queries";
import { decodeFigure, type FigureAsset } from "./figure";

export function laboratoryFigureOptions(client: ApiClient) {
  return queryOptions<FigureAsset>({
    queryKey: apiQueryKeys.laboratoryFigure(),
    queryFn: async () => decodeFigure(await client.laboratoryFigure()),
    ...LABORATORY_QUERY_TIMING,
    retry: false,
  });
}
