"use client";

/**
 * Who the browser is currently acting as.
 *
 * Development only. A pseudonym typed into a box is not authentication and is
 * not pretending to be: it exists so the interface can be built and shown
 * before school-managed identity is decided (concept note S7).
 */

import { useSyncExternalStore } from "react";

const KEY = "genai4ed.pseudonym";
const CHANGED = "genai4ed:identity";

export function getPseudonym(): string | null {
  if (typeof window === "undefined") return null;
  try {
    // `?as=` wins, and is read here rather than applied by an effect so that
    // the very first client render already knows who it is. Reading it later
    // would race the redirect that sends an unidentified browser home.
    const fromUrl = new URLSearchParams(window.location.search).get("as");
    return fromUrl || window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setPseudonym(value: string): void {
  try {
    window.localStorage.setItem(KEY, value);
    window.dispatchEvent(new Event(CHANGED));
  } catch {
    /* private browsing; the caller still holds it in React state */
  }
}

export function clearPseudonym(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}


function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGED, onChange);
  };
}

/**
 * Read the current pseudonym without setting state inside an effect.
 *
 * Three states, and the difference matters:
 *
 *   undefined  not known yet - the server render, and the hydration pass that
 *              reuses it. Show nothing; do not conclude anything.
 *   null       known to be absent. Ask who the viewer is.
 *   string     known.
 *
 * Collapsing the first two makes every page redirect home during hydration,
 * a moment before the real value arrives.
 */
export function useIdentity(): string | null | undefined {
  return useSyncExternalStore(subscribe, getPseudonym, () => undefined);
}
