import { Filter, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "../components/Button";
import { DataTable } from "../components/DataTable";
import { Dropdown } from "../components/Dropdown";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { SearchInput } from "../components/SearchInput";
import { StatusBadge } from "../components/StatusBadge";
import { workflowFixtures } from "../data/demoData";

export default function WorkflowsPage() {
  const [searchValue, setSearchValue] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const filteredWorkflows = useMemo(() => {
    return workflowFixtures.filter((workflow) => {
      const matchesQuery = workflow.name.toLowerCase().includes(searchValue.toLowerCase()) || workflow.description.toLowerCase().includes(searchValue.toLowerCase());
      const matchesStatus = statusFilter === "all" || workflow.status === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [searchValue, statusFilter]);

  const rows = filteredWorkflows.map((workflow) => ({
    Workflow: <div className="font-medium text-[var(--text)]">{workflow.name}</div>,
    Description: <span className="text-[var(--secondary)]">{workflow.description}</span>,
    "Last updated": <span className="text-[var(--secondary)]">{workflow.lastUpdated}</span>,
    Status: <StatusBadge tone={workflow.status === "Running" ? "violet" : workflow.status === "Completed" ? "green" : workflow.status === "Queued" ? "blue" : "neutral"}>{workflow.status}</StatusBadge>,
    "Executions": <span className="font-medium text-[var(--secondary)]">{workflow.executionCount}</span>,
  }));

  return (
    <div>
      <PageHeader
        title="Workflows"
        description="Development fixtures are used until real orchestration data is connected."
        actions={<Button><Plus className="mr-2 h-4 w-4" />Create Workflow</Button>}
      />

      <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 md:flex-row md:items-end">
        <div className="flex-1">
          <SearchInput value={searchValue} onChange={setSearchValue} ariaLabel="Search workflows" placeholder="Search workflows" />
        </div>
        <div className="w-full md:max-w-[180px]">
          <Dropdown
            label="Status"
            value={statusFilter}
            options={[
              { value: "all", label: "All statuses" },
              { value: "Running", label: "Running" },
              { value: "Queued", label: "Queued" },
              { value: "Completed", label: "Completed" },
              { value: "Paused", label: "Paused" },
              { value: "Draft", label: "Draft" },
            ]}
            onChange={setStatusFilter}
          />
        </div>
      </div>

      {filteredWorkflows.length === 0 ? (
        <EmptyState
          title="No workflow matches your filters"
          description="Try clearing the search and status filters to view the full mock register."
          action={<Button variant="secondary">Reset filters</Button>}
        />
      ) : (
        <DataTable columns={["Workflow", "Description", "Last updated", "Status", "Executions"]} rows={rows} />
      )}

      <div className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-xs text-[var(--secondary)]">
        <div className="flex items-center gap-2 font-medium text-[var(--text)]">
          <Filter className="h-3.5 w-3.5" />
          Demo workflow registry
        </div>
      </div>
    </div>
  );
}
