import { apiBaseUrl } from "./config";

const operatorAuthUrl = `${apiBaseUrl}/auth/session`;
const userSessionUrl = `${apiBaseUrl}/auth/user-session`;
const userLogoutUrl = `${apiBaseUrl}/auth/logout`;
const userLoginUrl = `${apiBaseUrl}/auth/login`;
const authModeStorageKey = "agentforge-auth-mode";

export type AuthIdentity =
  | { kind: "operator" }
  | { kind: "user"; workspaceRole: "owner" | "admin" | "member" | null };

async function restoreOperatorSession(): Promise<AuthIdentity | null> {
  const response = await fetch(operatorAuthUrl, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (response.ok) {
    window.localStorage.setItem(authModeStorageKey, "operator");
    return { kind: "operator" };
  }
  if (response.status === 401) return null;
  throw new Error("The operator session could not be checked.");
}

async function restoreUserSession(): Promise<AuthIdentity | null> {
  const response = await fetch(userSessionUrl, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (response.ok) {
    const body = await response.json() as { workspace_role?: unknown };
    if (
      body.workspace_role !== "owner"
      && body.workspace_role !== "admin"
      && body.workspace_role !== "member"
      && body.workspace_role !== null
    ) {
      throw new Error("The user workspace role could not be checked.");
    }
    window.localStorage.setItem(authModeStorageKey, "user");
    return { kind: "user", workspaceRole: body.workspace_role };
  }
  if (response.status === 401) return null;
  throw new Error("The user session could not be checked.");
}

export function clearAuthMode(): void {
  window.localStorage.removeItem(authModeStorageKey);
}

export async function restoreSession(): Promise<AuthIdentity | null> {
  const mode = window.localStorage.getItem(authModeStorageKey);
  if (mode === "user") {
    const identity = await restoreUserSession();
    if (!identity) clearAuthMode();
    return identity;
  }
  if (mode === "operator") {
    const identity = await restoreOperatorSession();
    if (!identity) clearAuthMode();
    return identity;
  }

  const operatorIdentity = await restoreOperatorSession();
  if (operatorIdentity) return operatorIdentity;
  const userIdentity = await restoreUserSession();
  if (!userIdentity) clearAuthMode();
  return userIdentity;
}

export async function login(credential: string): Promise<void> {
  const userLogout = await fetch(userLogoutUrl, { method: "DELETE", credentials: "include" });
  if (!userLogout.ok && userLogout.status !== 204) {
    throw new Error("The existing user session could not be cleared.");
  }
  const response = await fetch(operatorAuthUrl, {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ credential }),
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error("The credential was not accepted.");
    throw new Error("Sign in is unavailable. Check the API configuration and try again.");
  }
  window.localStorage.setItem(authModeStorageKey, "operator");
}

export async function loginUser(email: string, password: string): Promise<void> {
  const operatorLogout = await fetch(operatorAuthUrl, { method: "DELETE", credentials: "include" });
  if (!operatorLogout.ok && operatorLogout.status !== 204) {
    throw new Error("The existing operator session could not be cleared.");
  }
  const response = await fetch(userLoginUrl, {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error("The email or password was not accepted.");
    throw new Error("Sign in is unavailable. Check the API configuration and try again.");
  }
  window.localStorage.setItem(authModeStorageKey, "user");
}

export async function logout(): Promise<void> {
  const [publicResponse, operatorResponse] = await Promise.all([
    fetch(userLogoutUrl, { method: "DELETE", credentials: "include" }),
    fetch(operatorAuthUrl, { method: "DELETE", credentials: "include" }),
  ]);
  if (!publicResponse.ok || !operatorResponse.ok) {
    throw new Error("Sign out could not be completed. Try again.");
  }
  clearAuthMode();
}
