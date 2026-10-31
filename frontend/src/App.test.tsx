import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";

describe("AgentForge application shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.dataset.theme = "light";
  });

  it("renders the dashboard and application navigation", () => {
    render(<App />);

    expect(screen.getByRole("navigation", { name: /primary navigation/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /welcome back, nihar/i })).toBeInTheDocument();
    expect(screen.getByText(/total workflows/i)).toBeInTheDocument();
  });

  it("switches to the workflows route from the sidebar", () => {
    render(<App />);

    fireEvent.click(screen.getAllByRole("link", { name: /workflows/i })[0]);

    expect(screen.getByText(/development fixtures are used until real orchestration data is connected/i)).toBeInTheDocument();
  });

  it("switches theme and persists the selection", () => {
    render(<App />);

    fireEvent.click(screen.getAllByRole("button", { name: /dark mode/i })[0]);

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("agentforge-theme")).toBe("dark");
  });

  it("renders the empty dashboard state for demo content", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /empty demo state/i }));

    expect(screen.getByText(/no workflows to display/i)).toBeInTheDocument();
  });

  it("renders the settings page with theme controls", () => {
    render(<App />);

    fireEvent.click(screen.getAllByRole("link", { name: /settings/i })[0]);

    expect(screen.getByText(/appearance and account placeholders for the frontend shell/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/theme selection/i)).toBeInTheDocument();
  });
});
