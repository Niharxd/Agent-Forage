type LoadingStateProps = {
  label?: string;
};

export function LoadingState({ label = "Loading demo data" }: LoadingStateProps) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-10">
      <div className="flex items-center gap-3 text-sm text-[var(--secondary)]">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--primary)] border-t-transparent" aria-hidden="true" />
        <span>{label}</span>
      </div>
    </div>
  );
}
