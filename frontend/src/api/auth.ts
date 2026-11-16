const authUrl = "/api/v1/auth/session";

export async function restoreSession(): Promise<boolean> {
  const response = await fetch(authUrl, { credentials: "include", headers: { Accept: "application/json" } });
  if (response.status === 401) return false;
  if (!response.ok) throw new Error("The operator session could not be checked.");
  return true;
}

export async function login(credential: string): Promise<void> {
  const response = await fetch(authUrl, {
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

export async function logout(): Promise<void> {
  const response = await fetch(authUrl, { method: "DELETE", credentials: "include" });
  if (!response.ok) throw new Error("Sign out could not be completed. Try again.");
}
