import { apiBaseUrl } from "./config";

const operatorAuthUrl = `${apiBaseUrl}/auth/session`;
const userSessionUrl = `${apiBaseUrl}/auth/user-session`;
const userLogoutUrl = `${apiBaseUrl}/auth/logout`;
const userLoginUrl = `${apiBaseUrl}/auth/login`;

export async function restoreSession(): Promise<boolean> {
  const operatorResponse = await fetch(operatorAuthUrl, { credentials: "include", headers: { Accept: "application/json" } });
  if (operatorResponse.ok) {
    return true;
  }
  if (operatorResponse.status !== 401) throw new Error("The operator session could not be checked.");

  const userResponse = await fetch(userSessionUrl, { credentials: "include", headers: { Accept: "application/json" } });
  if (userResponse.ok) {
    return true;
  }
  if (userResponse.status === 401) return false;
  throw new Error("The user session could not be checked.");
}

export async function login(credential: string): Promise<void> {
  await fetch(userLogoutUrl, { method: "DELETE", credentials: "include" }).catch(() => undefined);
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
}

export async function loginUser(email: string, password: string): Promise<void> {
  await fetch(operatorAuthUrl, { method: "DELETE", credentials: "include" }).catch(() => undefined);
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
}

export async function logout(): Promise<void> {
  const publicResponse = await fetch(userLogoutUrl, { method: "DELETE", credentials: "include" }).catch(
    () => ({ ok: false, status: 0 } as Response),
  );
  const operatorResponse = await fetch(operatorAuthUrl, { method: "DELETE", credentials: "include" }).catch(
    () => ({ ok: false, status: 0 } as Response),
  );
  if (
    !publicResponse.ok
    && publicResponse.status !== 204
    && !operatorResponse.ok
    && operatorResponse.status !== 204
  ) {
    throw new Error("Sign out could not be completed. Try again.");
  }
}
