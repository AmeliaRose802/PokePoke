/**
 * Hook to manage collapsible banner state with localStorage persistence.
 */

import { useCallback, useState } from "react";

const STORAGE_KEY = "pokepoke-banner-collapsed";

function readStoredState(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function useCollapsibleBanner() {
  const [collapsed, setCollapsed] = useState(readStoredState);

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // Ignore storage errors
      }
      return next;
    });
  }, []);

  return { collapsed, toggle } as const;
}
