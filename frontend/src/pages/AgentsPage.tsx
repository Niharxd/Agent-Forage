import { Plus } from "lucide-react";
import { AgentCard } from "../components/AgentCard";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { agentDirectory } from "../data/demoData";

export default function AgentsPage() {
  return (
    <div>
      <PageHeader
        title="Agents"
        description="Initial agent types for workflow orchestration and review."
        actions={<Button><Plus className="mr-2 h-4 w-4" />Add agent</Button>}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        {agentDirectory.map((agent) => (
          <AgentCard
            key={agent.name}
            name={agent.name}
            responsibility={agent.responsibility}
            description={agent.description}
            capabilities={agent.capabilities}
            status={agent.status}
          />
        ))}
      </div>
    </div>
  );
}
