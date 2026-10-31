import type { InputHTMLAttributes } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement>;

export function Input({ className = "", ...props }: InputProps) {
  return (
    <input
      className={`w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] transition-colors duration-200 focus:border-[var(--primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-soft)] ${className}`}
      {...props}
    />
  );
}
