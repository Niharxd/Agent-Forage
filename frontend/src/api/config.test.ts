import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "./config";

describe("API base URL", () => {
  it("uses the same-origin relative base in production", () => {
    expect(resolveApiBaseUrl("https://agentforge-api-kc0x.onrender.com/api/v1", true)).toBe("/api/v1");
  });

  it("preserves a configured local development base", () => {
    expect(resolveApiBaseUrl("http://127.0.0.1:8000/api/v1", false)).toBe("http://127.0.0.1:8000/api/v1");
  });

  it("uses the local Vite proxy default when no base is configured", () => {
    expect(resolveApiBaseUrl(undefined, false)).toBe("/api/v1");
  });
});
