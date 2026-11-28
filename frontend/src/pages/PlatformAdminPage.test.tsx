import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PlatformAdminPage from "./PlatformAdminPage";

const overview = {
  users: { total: 3, active: 1, pending: 1, suspended: 1 },
  workspaces: 1,
  workflows: 2,
  executions: 4,
  recent_activity: [],
};
const active = {
  id: "user-active", email: "active@example.com", account_status: "active",
  created_at: "2026-01-01T00:00:00Z", last_login_at: null, email_verified_at: null,
  workspaces: [{ id: "ws-a", name: "Acme", slug: "acme", role: "owner" }],
};
const suspended = {
  ...active, id: "user-suspended", email: "suspended@example.com", account_status: "suspended",
  workspaces: [],
};
const workspace = {
  id: "ws-a", name: "Acme", slug: "acme", status: "active",
  owner: { id: "user-active", email: "active@example.com" },
  members: [{ id: "user-active", email: "active@example.com", role: "owner" }],
  workflow_count: 2, execution_count: 4,
};

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 500): Response {
  return { ok, status, json: async () => body } as Response;
}

function installApi(options?: { failOverview?: boolean; failAction?: boolean }) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/platform-admin/overview")) {
      return options?.failOverview ? jsonResponse({}, false) : jsonResponse(overview);
    }
    if (url.includes("/platform-admin/users/") && init?.method === "PATCH") {
      return options?.failAction ? jsonResponse({}, false) : jsonResponse({ account_status: "suspended" });
    }
    if (url.endsWith("/platform-admin/users/user-active")) return jsonResponse(active);
    if (url.endsWith("/platform-admin/users/user-suspended")) return jsonResponse(suspended);
    if (url.includes("/platform-admin/users?")) {
      const params = new URLSearchParams(url.split("?")[1]);
      const rows = params.get("status") === "suspended" ? [suspended] : [active, suspended];
      const filtered = rows.filter((user) => user.email.includes(params.get("q") ?? ""));
      return jsonResponse({ items: filtered, total: filtered.length });
    }
    if (url.includes("/platform-admin/workspaces")) {
      return jsonResponse({ items: [workspace], total: 1 });
    }
    return jsonResponse({}, false, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("PlatformAdminPage", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  beforeEach(() => { installApi(); });

  it("shows loading and then accurate overview metrics", async () => {
    const pending: { url: string; resolve: (response: Response) => void }[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => new Promise<Response>((resolve) => {
      pending.push({ url: String(input), resolve });
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<PlatformAdminPage />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading platform metrics/i);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await act(async () => pending.forEach(({ url, resolve }) => resolve(
      url.endsWith("/overview") ? jsonResponse(overview)
        : url.includes("/users?") ? jsonResponse({ items: [active, suspended], total: 2 })
          : jsonResponse({ items: [workspace], total: 1 }),
    )));
    expect(await screen.findByText("4", { selector: ".text-3xl" })).toBeInTheDocument();
    expect(screen.getByText("3", { selector: ".text-3xl" })).toBeInTheDocument();
  });

  it("shows the empty state when there are no matching users", async () => {
    const fetchMock = installApi();
    fetchMock.mockImplementation(async (input) => String(input).includes("/users?")
      ? jsonResponse({ items: [], total: 0 })
      : String(input).includes("/overview") ? jsonResponse(overview) : jsonResponse({ items: [], total: 0 }));
    render(<PlatformAdminPage />);
    expect(await screen.findByText("No users match this search.")).toBeInTheDocument();
  });

  it("shows an error and retries loading platform data", async () => {
    let fail = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/overview") && fail) return jsonResponse({}, false);
      return String(input).endsWith("/overview") ? jsonResponse(overview) : jsonResponse({ items: [], total: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PlatformAdminPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be loaded/i);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Recent platform activity")).toBeInTheDocument();
  });

  it("filters users by email and account status", async () => {
    const fetchMock = installApi();
    render(<PlatformAdminPage />);
    expect(await screen.findByText("active@example.com")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), { target: { value: "suspended" } });
    expect(await screen.findByText("suspended@example.com")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /account status/i }), { target: { value: "suspended" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("status=suspended"))).toBe(true));
    expect(screen.queryByText("active@example.com")).not.toBeInTheDocument();
  });

  it("does not let a slow old search overwrite the latest search result", async () => {
    const newer = { ...active, id: "user-newer", email: "newer@example.com" };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/users?q=old")) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          setTimeout(() => reject(new Error("stale request did not abort")), 200);
        });
      }
      if (url.includes("/users?q=new")) return Promise.resolve(jsonResponse({ items: [newer], total: 1 }));
      if (url.includes("/users?")) return Promise.resolve(jsonResponse({ items: [], total: 0 }));
      if (url.includes("/overview")) return Promise.resolve(jsonResponse(overview));
      return Promise.resolve(jsonResponse({ items: [], total: 0 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PlatformAdminPage />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const search = screen.getByRole("textbox", { name: "Search" });
    fireEvent.change(search, { target: { value: "old" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("users?q=old"))).toBe(true));
    fireEvent.change(search, { target: { value: "new" } });
    expect(await screen.findByText("newer@example.com")).toBeInTheDocument();
    expect(screen.queryByText("stale request did not abort")).not.toBeInTheDocument();
  });

  it("loads user details through the dedicated detail endpoint", async () => {
    const fetchMock = installApi();
    render(<PlatformAdminPage />);
    await screen.findByText("active@example.com");
    fireEvent.click(screen.getAllByRole("button", { name: "Details" })[0]);
    expect(await screen.findByRole("dialog", { name: /user details/i })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByText("Acme · owner")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/users/user-active"))).toBe(true);
  });

  it("requires confirmation before suspension and refreshes after success", async () => {
    const fetchMock = installApi();
    render(<PlatformAdminPage />);
    await screen.findByText("active@example.com");
    fireEvent.click(screen.getAllByRole("button", { name: "Suspend" })[0]);
    expect(screen.getByRole("alertdialog")).toHaveTextContent(/active sessions will be revoked/i);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /confirm suspension/i }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("can cancel a suspend confirmation and confirms reactivation too", async () => {
    render(<PlatformAdminPage />);
    await screen.findByText("suspended@example.com");
    fireEvent.click(screen.getAllByRole("button", { name: "Reactivate" })[0]);
    expect(screen.getByRole("alertdialog")).toHaveTextContent(/reactivate account/i);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Reactivate" })[0]);
    fireEvent.click(screen.getByRole("button", { name: /confirm reactivation/i }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("shows failed status changes without reporting success", async () => {
    installApi({ failAction: true });
    render(<PlatformAdminPage />);
    await screen.findByText("active@example.com");
    fireEvent.click(screen.getAllByRole("button", { name: "Suspend" })[0]);
    fireEvent.click(screen.getByRole("button", { name: /confirm suspension/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be loaded/i);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("discovers workspaces and shows owner, members and aggregate counts", async () => {
    const fetchMock = installApi();
    render(<PlatformAdminPage />);
    await screen.findByText("active@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText(/Owner: active@example.com · 1 members · 2 workflows · 4 executions/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), { target: { value: "Acme" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("workspaces?q=Acme"))).toBe(true));
  });
});
