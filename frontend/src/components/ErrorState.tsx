import { Button } from "./Button";

type ErrorStateProps = {
  title?: string;
  description?: string;
  onRetry?: () => void;
};

export function ErrorState({
  title = "Something went wrong",
  description = "The dashboard demo failed to render. Try refreshing the view.",
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-10 text-center">
      <div className="text-lg font-semibold text-[var(--text)]">{title}</div>
      <p className="mt-2 max-w-md text-sm text-[var(--secondary)]">{description}</p>
      {onRetry ? (
        <div className="mt-4">
          <Button variant="secondary" onClick={onRetry}>
            Retry demo
          </Button>
        </div>
      ) : null}
    </div>
  );
}
