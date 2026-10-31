import {
  Activity,
  Bot,
  BriefcaseBusiness,
  Calculator,
  Gauge,
  ListChecks,
  NotebookText,
  Settings2,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";

export type NavItem = {
  label: string;
  to: string;
  icon: typeof Gauge;
};

export const navigationItems: NavItem[] = [
  { label: "Dashboard", to: "/", icon: Gauge },
  { label: "Workflows", to: "/workflows", icon: ListChecks },
  { label: "Agents", to: "/agents", icon: Bot },
  { label: "Tools", to: "/tools", icon: Wrench },
  { label: "Executions", to: "/executions", icon: Activity },
  { label: "Settings", to: "/settings", icon: Settings2 },
];

export const dashboardMetrics = [
  { label: "Total workflows", value: "24", change: "+12% vs last week", tone: "violet" },
  { label: "Active executions", value: "6", change: "2 in progress", tone: "blue" },
  { label: "Successful executions", value: "91%", change: "+4.8% this month", tone: "green" },
  { label: "Failed executions", value: "3", change: "2 retries queued", tone: "red" },
] as const;

export const recentWorkflows = [
  { name: "AI onboarding flow", description: "Recruiting ops automation", updated: "3 mins ago", status: "Running", executionCount: 18 },
  { name: "Research collection", description: "Market monitoring and synthesis", updated: "1 hour ago", status: "Queued", executionCount: 7 },
  { name: "Compliance review", description: "Risk analysis and policy checks", updated: "Yesterday", status: "Completed", executionCount: 36 },
  { name: "Client summary sprint", description: "Weekly narrative report generation", updated: "2 days ago", status: "Paused", executionCount: 11 },
] as const;

export const executionActivity = [
  { workflow: "Research collection", status: "Running", time: "2 min ago", duration: "00:07:12" },
  { workflow: "Compliance review", status: "Succeeded", time: "17 min ago", duration: "00:09:54" },
  { workflow: "Client summary sprint", status: "Failed", time: "41 min ago", duration: "00:03:41" },
  { workflow: "AI onboarding flow", status: "Running", time: "1 hr ago", duration: "00:11:08" },
] as const;

export const quickAccessCards = [
  { name: "Planner Agent", description: "Workflow design and task decomposition", icon: NotebookText },
  { name: "Calculator", description: "Quick financial and analytical calculations", icon: Calculator },
  { name: "Policy Review", description: "Structured checks and escalations", icon: ShieldCheck },
  { name: "Ops Toolkit", description: "Execution monitoring and task orchestration", icon: BriefcaseBusiness },
] as const;

export const agentDirectory = [
  {
    name: "Planner Agent",
    responsibility: "Workflow design",
    description: "Maps goals into structured tasks and decision points.",
    capabilities: ["Task planning", "Sequence design", "Dependency mapping"],
    status: "Configured",
  },
  {
    name: "Researcher Agent",
    responsibility: "Gathering context",
    description: "Collects verified information and synthesizes key findings.",
    capabilities: ["Source review", "Summaries", "Research briefs"],
    status: "Mock ready",
  },
  {
    name: "Analyst Agent",
    responsibility: "Evaluation and insights",
    description: "Analyzes output quality, patterns, and execution risks.",
    capabilities: ["Analysis", "Scoring", "Metrics review"],
    status: "Configured",
  },
  {
    name: "Reviewer Agent",
    responsibility: "Quality controls",
    description: "Verifies outputs against policy, intent, and standards.",
    capabilities: ["Checks", "Policy review", "Approval gate"],
    status: "Configured",
  },
] as const;

export const toolRegistry = [
  {
    name: "Calculator",
    description: "Performs numerical calculations and lightweight financial modeling.",
    permission: "Safe",
    status: "Available",
    category: "Utility",
  },
  {
    name: "Text Summarizer",
    description: "Condenses longer content into concise executive summaries.",
    permission: "Approvals needed",
    status: "Planned",
    category: "Content",
  },
  {
    name: "CSV Profiler",
    description: "Cleans, profiles, and validates structured datasets.",
    permission: "Restricted",
    status: "Preview",
    category: "Analysis",
  },
] as const;

export const workflowFixtures = [
  { name: "AI onboarding flow", description: "Recruiting ops automation", lastUpdated: "3 mins ago", status: "Running", executionCount: 18 },
  { name: "Research collection", description: "Market monitoring and synthesis", lastUpdated: "1 hour ago", status: "Queued", executionCount: 7 },
  { name: "Compliance review", description: "Risk analysis and policy checks", lastUpdated: "Yesterday", status: "Completed", executionCount: 36 },
  { name: "Client summary sprint", description: "Weekly narrative report generation", lastUpdated: "2 days ago", status: "Paused", executionCount: 11 },
  { name: "Knowledge base sync", description: "Documentation update pipeline", lastUpdated: "4 days ago", status: "Draft", executionCount: 2 },
] as const;

export const executionFixtures = [
  { id: "EX-1042", workflow: "AI onboarding flow", status: "Running", startTime: "2026-10-31 10:12", duration: "00:07:12" },
  { id: "EX-1039", workflow: "Research collection", status: "Succeeded", startTime: "2026-10-31 09:41", duration: "00:09:54" },
  { id: "EX-1032", workflow: "Client summary sprint", status: "Failed", startTime: "2026-10-31 08:24", duration: "00:03:41" },
  { id: "EX-1018", workflow: "Compliance review", status: "Queued", startTime: "2026-10-30 16:55", duration: "00:00:00" },
] as const;

export const themeOptions = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
] as const;

export const defaultTheme = "system" as const;

export const dashboardStateLabel: Record<string, string> = {
  live: "Live demo data",
  empty: "Empty demo state",
  error: "Error demo state",
  loading: "Loading demo state",
};

export const badgePillStyles = {
  violet: "bg-[var(--accent-soft)] text-[var(--accent)]",
  blue: "bg-[rgba(96,165,250,0.14)] text-[var(--info)]",
  green: "bg-[rgba(34,197,94,0.12)] text-[var(--success)]",
  red: "bg-[rgba(239,68,68,0.12)] text-[var(--error)]",
  neutral: "bg-[var(--surface-alt)] text-[var(--secondary)]",
};

export const defaultProfile = {
  name: "Nihar",
  workspace: "AgentForge / Core ops",
  role: "Product engineering",
};

export const accentToken = "var(--primary)" as const;
export const sparklesIcon = Sparkles;
