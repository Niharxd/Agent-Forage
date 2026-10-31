import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { SearchInput } from "../components/SearchInput";
import { StatusBadge } from "../components/StatusBadge";
import { DataTable } from "../components/DataTable";
import { Dropdown } from "../components/Dropdown";
import { executionFixtures } from "../data/demoData";

export default function ExecutionsPage() {
  const [searchValue, setSearchValue] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const filteredExecutions = useMemo(() => {
    return executionFixtures.filter((execution) => {
      const matchesQuery = execution.id.toLowerCase().includes(searchValue.toLowerCase()) || execution.workflow.toLowerCase().includes(searchValue.toLowerCase());
      const matchesStatus = statusFilter === "all" || execution.status === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [searchValue, statusFilter]);

  const rows = filteredExecutions.map((execution) => ({
    "Execution ID": <span className="font-medium text-[var(--text)]">{execution.id}</span>,
    "Workflow name": <span className="text-[var(--secondary)]">{execution.workflow}</span>,
    Status: <StatusBadge tone={execution.status === "Succeeded" ? "green" : execution.status === "Running" ? "violet" : execution.status === "Failed" ? "red" : "blue"}>{execution.status}</StatusBadge>,
    "Start time": <span className="text-[var(--secondary)]">{execution.startTime}</span>,
    Duration: <span className="text-[var(--secondary)]">{execution.duration}</span>,
  }));

  return (
    <div>
      <PageHeader
        title="Executions"
        description="Execution records are mocked for the current frontend milestone."
      />

      <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 md:flex-row md:items-end">
        <div className="flex-1">
          <SearchInput value={searchValue} onChange={setSearchValue} ariaLabel="Search executions" placeholder="Filter executions" />
        </div>
        <div className="w-full md:max-w-[180px]">
          <Dropdown
            label="Status"
            value={statusFilter}
            options={[
              { value: "all", label: "All statuses" },
              { value: "Running", label: "Running" },
              { value: "Succeeded", label: "Succeeded" },
              { value: "Failed", label: "Failed" },
              { value: "Queued", label: "Queued" },
            ]}
            onChange={setStatusFilter}
          />
        </div>
      </div>

      {filteredExecutions.length === 0 ? (
        <EmptyState
          title="No execution history matches the current filters"
          description="Reset your search to view the underlying development fixtures."
        />
      ) : (
        <DataTable columns={["Execution ID", "Workflow name", "Status", "Start time", "Duration"]} rows={rows} />
      )}

      <div className="mt-6 flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--secondary)]">
        <Search className="h-3.5 w-3.5" />
        Search and filter support is ready for integration with the live backend.
      </div>
    </div>
  );
}
