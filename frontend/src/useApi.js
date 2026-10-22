import { useEffect, useState } from "react";

import { getJSON } from "./api";

/**
 * Tiny data-fetching hook: one request per path, with loading/error state.
 *
 * Passing `null` as the path means "do not fetch yet" (used for the author
 * panel before a node is selected). The `cancelled` flag prevents a late
 * response from overwriting the state of a newer request.
 */
export function useApi(path) {
  const [state, setState] = useState({
    data: null,
    error: null,
    loading: Boolean(path),
  });

  useEffect(() => {
    if (!path) {
      setState({ data: null, error: null, loading: false });
      return undefined;
    }

    let cancelled = false;
    setState({ data: null, error: null, loading: true });

    getJSON(path)
      .then((data) => {
        if (!cancelled) {
          setState({ data, error: null, loading: false });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ data: null, error: error.message, loading: false });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [path]);

  return state;
}
