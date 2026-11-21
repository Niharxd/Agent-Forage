import { afterEach, describe, expect, it, vi } from "vitest";
import { login, logout, restoreSession } from "./auth";

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
    await logout();

    expect(fetchMock.mock.calls).toHaveLength(3);
    for (const [url, init] of fetchMock.mock.calls) {
      expect(String(url)).toBe("/api/v1/auth/session");
      expect(init?.credentials).toBe("include");
    }
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[2][1]?.method).toBe("DELETE");
  });
});
