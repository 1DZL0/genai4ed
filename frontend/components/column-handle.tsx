"use client";

import { useRef, useState, useSyncExternalStore } from "react";

// The widths a teacher has dragged the columns to, in pixels, remembered per browser. Read as
// an external store, like the text size, so every render agrees. When storage is unavailable
// (a private window) the width is kept for this page only.
const listeners = new Set<() => void>();
const remembered = new Map<string, number>();

function readWidth(key: string): number | null {
  try {
    const kept = Number(window.localStorage.getItem(key));
    if (Number.isFinite(kept) && kept > 0) return kept;
  } catch {
    // Storage unavailable: fall through to what this page remembers.
  }
  return remembered.get(key) ?? null;
}
function writeWidth(key: string, width: number | null) {
  if (width === null) remembered.delete(key);
  else remembered.set(key, width);
  try {
    if (width === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, String(width));
  } catch {
    // Not kept across reloads; the screen still works.
  }
  listeners.forEach((onChange) => onChange());
}
function subscribe(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The width the teacher chose for a column, or null while it is at its usual width. */
export function useColumnWidth(storageKey: string): number | null {
  return useSyncExternalStore(
    subscribe,
    () => readWidth(storageKey),
    () => null,
  );
}

const STEP = 24;

/** The line between two columns. Drag it, or use the arrow keys, to make the column on its
 * `side` wider or narrower; a double click or Enter puts it back. It measures the column
 * itself (its neighbour in the row) and the column on its other side, which gives up or
 * takes the room, so it needs no ref. */
export function ColumnHandle({
  storageKey,
  side,
  min,
  max,
  keep,
  label,
  className = "",
}: {
  storageKey: string;
  /** Which neighbour it sizes: the column before it or the one after it. */
  side: "before" | "after";
  min: number;
  max: number;
  /** The width, in pixels, the column on the other side always keeps. */
  keep: number;
  label: string;
  className?: string;
}) {
  const width = useColumnWidth(storageKey);
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; width: number } | null>(null);

  function widthOf(el: Element | null) {
    return el?.getBoundingClientRect().width ?? 0;
  }
  function widthNow(handle: HTMLElement) {
    return widthOf(side === "before" ? handle.previousElementSibling : handle.nextElementSibling);
  }
  function clamp(handle: HTMLElement, next: number) {
    const other = side === "before" ? handle.nextElementSibling : handle.previousElementSibling;
    const room = widthNow(handle) + widthOf(other) - keep;
    return Math.round(Math.max(min, Math.min(next, max, room)));
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width ?? undefined}
      tabIndex={0}
      title="Drag to resize. Double click to put it back."
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        start.current = { x: e.clientX, width: widthNow(e.currentTarget) };
        setDragging(true);
      }}
      onPointerMove={(e) => {
        if (!start.current) return;
        const moved = e.clientX - start.current.x;
        const next = start.current.width + (side === "before" ? moved : -moved);
        writeWidth(storageKey, clamp(e.currentTarget, next));
      }}
      onPointerUp={() => {
        start.current = null;
        setDragging(false);
      }}
      onPointerCancel={() => {
        start.current = null;
        setDragging(false);
      }}
      onDoubleClick={() => writeWidth(storageKey, null)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          writeWidth(storageKey, null);
          return;
        }
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const wider = (e.key === "ArrowRight") === (side === "before");
        writeWidth(
          storageKey,
          clamp(e.currentTarget, widthNow(e.currentTarget) + (wider ? STEP : -STEP)),
        );
      }}
      className={`group no-print relative z-20 hidden w-0 shrink-0 cursor-col-resize touch-none select-none focus:outline-none ${className}`}
    >
      {/* Wider than the line, so it is easy to catch with the cursor. */}
      <span aria-hidden className="absolute inset-y-0 -left-2 w-4" />
      <span
        aria-hidden
        className={`absolute inset-y-0 left-0 -translate-x-1/2 transition-[width,background-color] group-hover:w-1 group-hover:bg-accent group-focus-visible:w-1 group-focus-visible:bg-accent ${
          dragging ? "w-1 bg-accent" : "w-px bg-rule"
        }`}
      />
    </div>
  );
}
