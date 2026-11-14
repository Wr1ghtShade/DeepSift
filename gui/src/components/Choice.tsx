// A group of native radio buttons drawn as chips or as a segmented control. Native
// radios give arrow-key navigation and the right semantics for free.
import { useId } from "react";

export interface ChoiceOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
}

export function Choice<T extends string>({
  legend,
  options,
  value,
  onChange,
  variant = "chips",
  hideLegend = false,
}: {
  legend: string;
  options: ChoiceOption<T>[];
  value: T;
  onChange: (value: T) => void;
  variant?: "chips" | "segmented";
  hideLegend?: boolean;
}) {
  const name = useId();
  return (
    <fieldset className={`choice ${variant}`}>
      <legend className={hideLegend ? "visually-hidden" : undefined}>{legend}</legend>
      {options.map((option) => (
        <label key={option.value} className="choice-option">
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={option.disabled}
            onChange={() => onChange(option.value)}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
