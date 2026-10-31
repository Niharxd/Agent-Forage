import type { ReactNode } from "react";

type DataTableProps = {
  columns: string[];
  rows: Array<Record<string, ReactNode>>;
};

export function DataTable({ columns, rows }: DataTableProps) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)]">
      <table className="min-w-full divide-y divide-[var(--border)] text-left">
        <thead className="bg-[var(--surface-alt)] text-[var(--secondary)]">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-4 py-3 text-xs font-medium uppercase tracking-[0.08em]">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)] text-sm text-[var(--text)]">
          {rows.map((row, index) => (
            <tr key={`${Object.values(row).join("-")}-${index}`} className="bg-[var(--surface)] hover:bg-[var(--surface-alt)]">
              {columns.map((column) => (
                <td key={`${column}-${index}`} className="px-4 py-3 align-middle">
                  {row[column]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
