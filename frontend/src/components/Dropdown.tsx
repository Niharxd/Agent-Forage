type DropdownOption = {
  value: string;
  label: string;
};

type DropdownProps = {
  label: string;
  value?: string;
  options: DropdownOption[];
  onChange?: (value: string) => void;
};

export function Dropdown({ label, value, options, onChange }: DropdownProps) {
  return (
    <label className="flex flex-col gap-1 text-sm text-[var(--secondary)]">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-soft)]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
