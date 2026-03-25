/**
 * A number input that defers clamping/defaulting until blur, so the user
 * can freely clear and retype values without aggressive auto-fill.
 */

import { useState } from "react";

interface Props extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value" | "type"> {
  value: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}

export function DeferredNumberInput({ value, min = 1, max = 100, onChange, ...rest }: Props) {
  const [localValue, setLocalValue] = useState(String(value));
  const [prevValue, setPrevValue] = useState(value);

  // Sync from external value changes (e.g. initial load, undo).
  // Safe without a focus guard because onChange is deferred to blur,
  // so the parent value never changes while the user is actively typing.
  if (value !== prevValue) {
    setPrevValue(value);
    setLocalValue(String(value));
  }

  const commitValue = (raw: string) => {
    const parsed = parseInt(raw, 10);
    if (isNaN(parsed) || parsed < min) {
      onChange(min);
      setLocalValue(String(min));
    } else if (parsed > max) {
      onChange(max);
      setLocalValue(String(max));
    } else {
      onChange(parsed);
      setLocalValue(String(parsed));
    }
  };

  return (
    <input
      type="number"
      min={min}
      max={max}
      value={localValue}
      onChange={(e) => {
        setLocalValue(e.target.value);
      }}
      onBlur={(e) => {
        commitValue(e.target.value);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          commitValue((e.target as HTMLInputElement).value);
        }
      }}
      {...rest}
    />
  );
}
