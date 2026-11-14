import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("AgentForge application shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.dataset.theme = "light";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("API unavailable")));
  });

  it("renders the dashboard and application navigation", async () => {
    render(<App />);

    expect(screen.getByRole("navigation", { name: /primary navigation/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "AgentForge" })).toHaveAttribute("src", "/assets/agentforge-logo.png");
    expect(await screen.findByRole("heading", { name: /command center/i })).toBeInTheDocument();
    expect(screen.getByText(/recent executions/i)).toBeInTheDocument();
  });

  it("switches to the workflows route from the sidebar", () => {
    render(<App />);

    fireEvent.click(screen.getAllByRole("link", { name: /workflows/i })[0]);

    expect(screen.getByRole("heading", { name: /prepare a workflow/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /workflow registry/i })).toBeInTheDocument();
  });

  it("switches theme and persists the selection", () => {
    render(<App />);

    fireEvent.click(screen.getAllByRole("button", { name: /dark mode/i })[0]);

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("agentforge-theme")).toBe("dark");
  });

  it("shows a clear dashboard retry state when the API is unavailable", async () => {
    render(<App />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent(/api unavailable/i);
    expect(screen.getAllByRole("button", { name: /retry/i }).length).toBeGreaterThan(0);
  });

  it("renders the settings page with theme controls", () => {
    render(<App />);

    fireEvent.click(screen.getAllByRole("link", { name: /settings/i })[0]);

    expect(screen.getByText(/appearance and account placeholders for the frontend shell/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/theme selection/i)).toBeInTheDocument();
  });
});
