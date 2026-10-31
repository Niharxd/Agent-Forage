import { Search } from "lucide-react";
import { Input } from "./Input";

type SearchInputProps = {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
};

export function SearchInput({
  value,
  onChange,
  placeholder = "Search",
  ariaLabel = "Search",
}: SearchInputProps) {
  return (
    <div className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted)]" />
      <Input
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        placeholder={placeholder}
        className="pl-9"
      />
    </div>
  );
}
