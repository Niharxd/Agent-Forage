import { afterEach, describe, expect, it, vi } from "vitest";
import { login, loginUser, logout, restoreSession } from "./auth";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("session authentication API", () => {
  it("checks, creates, and revokes the session through the shared relative URL", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({ authenticated: true }),
      ...init,
    } as Response));
    vi.stubGlobal("fetch", fetchMock);

    await restoreSession();
    await login("operator-credential");
    await loginUser("user@example.com", "StrongPassword123");
    await logout();

    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(6);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/auth/session") && init?.method === "POST")).toBe(true);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/auth/login") && init?.method === "POST")).toBe(true);
  });
});
