import { useCallback, useEffect, useRef, useState } from "react";

export interface UseResizableOptions {
  /** Initial fraction (0–1) of the container width allocated to the left panel. */
  initialFraction?: number;
  /** Minimum width in pixels for the left panel. */
  minLeftPx?: number;
  /** Minimum width in pixels for the right panel. */
  minRightPx?: number;
}

export interface UseResizableReturn {
  /** Fraction (0–1) of container width for the left panel. */
  fraction: number;
  /** Whether the user is currently dragging. */
  isDragging: boolean;
  /** Attach to the container element that holds both panels. */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** Props to spread on the resize handle element. */
  handleProps: {
    onMouseDown: (e: React.MouseEvent) => void;
    "data-dragging": boolean;
  };
}

const DEFAULT_FRACTION = 0.667; // 2:1 ratio (matches flex 2:1)
const DEFAULT_MIN_LEFT = 200;
const DEFAULT_MIN_RIGHT = 200;

/**
 * Hook that enables drag-to-resize between two horizontally adjacent panels.
 * Returns a fraction representing the left panel's share of container width.
 */
export function useResizable(options: UseResizableOptions = {}): UseResizableReturn {
  const { initialFraction = DEFAULT_FRACTION, minLeftPx = DEFAULT_MIN_LEFT, minRightPx = DEFAULT_MIN_RIGHT } = options;

  const [fraction, setFraction] = useState(initialFraction);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Sync the CSS custom property whenever fraction changes
  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      el.style.setProperty("--left-panel-fraction", String(fraction));
    }
  }, [fraction]);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const onMouseMove = (e: MouseEvent) => {
      const container = containerRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const containerWidth = rect.width;
      if (containerWidth === 0) return;

      const x = e.clientX - rect.left;
      let newFraction = x / containerWidth;

      // Enforce minimum widths
      const minLeftFraction = minLeftPx / containerWidth;
      const minRightFraction = minRightPx / containerWidth;
      const maxFraction = 1 - minRightFraction;

      newFraction = Math.max(minLeftFraction, Math.min(maxFraction, newFraction));
      setFraction(newFraction);
    };

    const onMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);

    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, [isDragging, minLeftPx, minRightPx]);

  return {
    fraction,
    isDragging,
    containerRef,
    handleProps: {
      onMouseDown,
      "data-dragging": isDragging,
    },
  };
}
