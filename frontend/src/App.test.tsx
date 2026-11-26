import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("AgentForge application shell", () => {
  afterEach(cleanup);
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
    document.documentElement.dataset.theme = "light";
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ authenticated: true }) } as Response);
      }
      return Promise.reject(new Error("API unavailable"));
    }));
  });

  it("renders the dashboard and application navigation", async () => {
    render(<App />);

    expect(await screen.findByRole("navigation", { name: /primary navigation/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "AgentForge" })).toHaveAttribute("src", "/assets/agentforge-logo.png");
    expect(screen.getByText("Operator console")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /agents/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/operator credential/i)).not.toBeInTheDocument();
    expect(screen.getByText(/recent executions/i)).toBeInTheDocument();
  });

  it("switches to the workflows route from the sidebar", async () => {
    render(<App />);
    await screen.findByRole("navigation", { name: /primary navigation/i });

    fireEvent.click(screen.getAllByRole("link", { name: /workflows/i })[0]);

    expect(screen.getByRole("heading", { name: /prepare a workflow/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /workflow registry/i })).toBeInTheDocument();
  });

  it("switches theme and persists the selection", async () => {
    render(<App />);
    await screen.findByRole("navigation", { name: /primary navigation/i });

    fireEvent.click(screen.getAllByRole("button", { name: /dark mode/i })[0]);

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("agentforge-theme")).toBe("dark");
  });

  it("shows a clear dashboard retry state when the API is unavailable", async () => {
    render(<App />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent(/api unavailable/i);
    expect(screen.getAllByRole("button", { name: /retry/i }).length).toBeGreaterThan(0);
  });

  it("renders the settings page with theme controls", async () => {
    render(<App />);
    await screen.findByRole("navigation", { name: /primary navigation/i });

    fireEvent.click(screen.getAllByRole("link", { name: /settings/i })[0]);

    expect(screen.getByText(/appearance and account placeholders for the frontend shell/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/theme selection/i)).toBeInTheDocument();
  });

  it("restores an unauthenticated session to the login screen and logs in without persistence", async () => {
    let operatorLoggedIn = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/session") && !init?.method) return Promise.resolve({ ok: operatorLoggedIn, status: operatorLoggedIn ? 200 : 401, json: async () => ({ authenticated: true }) } as Response);
      if (url.includes("/auth/logout") && init?.method === "DELETE") return Promise.resolve({ ok: true, status: 204 } as Response);
      if (url.includes("/auth/session") && init?.method === "POST") {
        operatorLoggedIn = true;
        return Promise.resolve({ ok: true, status: 200 } as Response);
      }
      return Promise.reject(new Error("API unavailable"));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const field = await screen.findByLabelText(/operator credential/i);
    fireEvent.change(field, { target: { value: "private-operator-token" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("navigation", { name: /primary navigation/i })).toBeInTheDocument();
    expect(window.localStorage.getItem("private-operator-token")).toBeNull();
    const loginCall = fetchMock.mock.calls.find(([url, init]) => String(url).includes("/auth/session") && init?.method === "POST");
    expect(loginCall).toBeDefined();
    expect(loginCall?.[1]?.credentials).toBe("include");
  });

  it("shows a safe login error for invalid credentials", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/auth/session") && !init?.method) return Promise.resolve({ ok: false, status: 401 } as Response);
      if (String(input).includes("/auth/logout") && init?.method === "DELETE") return Promise.resolve({ ok: true, status: 204 } as Response);
      return Promise.resolve({ ok: false, status: 401 } as Response);
    }));
    render(<App />);
    fireEvent.change(await screen.findByLabelText(/operator credential/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("The credential was not accepted.")).toBeInTheDocument();
    expect(screen.queryByText("wrong")).not.toBeInTheDocument();
  });

  it("logs in as a public user, restores the user dashboard, and logs out", async () => {
    let loggedIn = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/session")) {
        if (init?.method === "DELETE") return Promise.resolve({ ok: true, status: 204 } as Response);
        return Promise.resolve({ ok: false, status: 401 } as Response);
      }
      if (url.endsWith("/auth/user-session")) {
        if (!loggedIn) return Promise.resolve({ ok: false, status: 401 } as Response);
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ workspace_role: "owner" }),
        } as Response);
      }
      if (url.endsWith("/auth/login")) {
        loggedIn = true;
        return Promise.resolve({ ok: true, status: 200 } as Response);
      }
      if (url.includes("/workflows?")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response);
      }
      if (url.includes("/executions?")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response);
      }
      if (url.includes("/approvals?")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response);
      }
      if (url.endsWith("/auth/logout")) return Promise.resolve({ ok: true, status: 204 } as Response);
      return Promise.reject(new Error("Unexpected request"));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /^user$/i }));
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "StrongPassword123" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("heading", { name: /your workspace/i })).toBeInTheDocument();
    expect(screen.getAllByText("Personal workspace")).toHaveLength(2);
    expect(screen.queryByRole("link", { name: /agents/i })).not.toBeInTheDocument();
    expect(window.localStorage.getItem("agentforge-auth-mode")).toBe("user");

    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(await screen.findByRole("heading", { name: /user sign in/i })).toBeInTheDocument();
    expect(window.localStorage.getItem("agentforge-auth-mode")).toBeNull();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/auth/logout") && init?.method === "DELETE")).toBe(true);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/auth/session") && init?.method === "DELETE")).toBe(true);
  });

  it("does not fall back to a valid operator cookie when the selected user session is invalid", async () => {
    window.localStorage.setItem("agentforge-auth-mode", "user");
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith("/auth/user-session")) {
        return Promise.resolve({ ok: false, status: 401 } as Response);
      }
      if (String(input).endsWith("/auth/session")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ authenticated: true }) } as Response);
      }
      return Promise.reject(new Error("Unexpected request"));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByRole("heading", { name: /operator sign in/i })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/session"))).toBe(false);
    expect(window.localStorage.getItem("agentforge-auth-mode")).toBeNull();
  });

  it("restores a public user session directly to the user dashboard", async () => {
    window.localStorage.setItem("agentforge-auth-mode", "user");
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/user-session")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ workspace_role: "owner" }),
        } as Response);
      }
      if (url.includes("/workflows?")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response);
      }
      if (url.includes("/executions?")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response);
      }
      if (url.includes("/approvals?")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response);
      }
      return Promise.reject(new Error("Unexpected request"));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByRole("heading", { name: /your workspace/i })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/session"))).toBe(false);
  });
});
