import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { login, loginUser, logout, restoreSession } from "./api/auth";
import { AppShell } from "./components/AppShell";
import AgentsPage from "./pages/AgentsPage";
import DashboardPage from "./pages/DashboardPage";
import ExecutionsPage from "./pages/ExecutionsPage";
import SettingsPage from "./pages/SettingsPage";
import ToolsPage from "./pages/ToolsPage";
import WorkflowsPage from "./pages/WorkflowsPage";
import { ThemeProvider } from "./theme/ThemeContext";

export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loginMode, setLoginMode] = useState<"operator" | "user">("operator");
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const credentialRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    let active = true;
    restoreSession().then((value) => { if (active) setAuthenticated(value); })
      .catch(() => { if (active) setError("Sign in to continue."); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const expired = () => setAuthenticated(false);
    window.addEventListener("agentforge:session-expired", expired);
    return () => window.removeEventListener("agentforge:session-expired", expired);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const credential = credentialRef.current?.value ?? "";
    const email = emailRef.current?.value ?? "";
    const password = passwordRef.current?.value ?? "";
    if (busy || (loginMode === "operator" ? !credential : !email || !password)) return;
    setBusy(true); setError(null);
    try {
      if (loginMode === "operator") {
        await login(credential);
        if (credentialRef.current) credentialRef.current.value = "";
      } else {
        await loginUser(email, password);
        if (passwordRef.current) passwordRef.current.value = "";
      }
      setAuthenticated(true);
    } catch (reason) {
      if (credentialRef.current) credentialRef.current.value = "";
      if (passwordRef.current) passwordRef.current.value = "";
      setError(reason instanceof Error ? reason.message : "Sign in failed.");
    } finally { setBusy(false); }
  }

  async function signOut() {
    setBusy(true); setError(null);
    try { await logout(); setAuthenticated(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Sign out failed."); }
    finally { setBusy(false); }
  }

  if (checking) return <div className="grid min-h-screen place-items-center bg-[var(--bg)] text-[var(--secondary)]" role="status">Checking session…</div>;
  if (!authenticated) return <main className="grid min-h-screen place-items-center bg-[var(--bg)] px-4 text-[var(--text)]"><form onSubmit={(event) => void submit(event)} className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-8 shadow-2xl">
    <div className="mb-7 flex items-center gap-4"><img src="/assets/agentforge-logo.png" alt="AgentForge" className="h-14 w-14 rounded-xl"/><div><h1 className="text-xl font-semibold">{loginMode === "operator" ? "Operator sign in" : "User sign in"}</h1><p className="text-sm text-[var(--secondary)]">Authenticate to open AgentForge.</p></div></div>
    <div className="mb-5 grid grid-cols-2 rounded-lg border border-[var(--border)] p-1">
      <button type="button" onClick={() => setLoginMode("operator")} className={`rounded-md px-3 py-2 text-sm ${loginMode === "operator" ? "bg-[var(--surface-alt)] font-medium" : "text-[var(--secondary)]"}`}>Operator</button>
      <button type="button" onClick={() => setLoginMode("user")} className={`rounded-md px-3 py-2 text-sm ${loginMode === "user" ? "bg-[var(--surface-alt)] font-medium" : "text-[var(--secondary)]"}`}>User</button>
    </div>
    {loginMode === "operator" ? <>
      <label htmlFor="operator-credential" className="mb-2 block text-sm font-medium">Operator credential</label>
      <input ref={credentialRef} id="operator-credential" name="credential" type="password" autoComplete="current-password" required disabled={busy} className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2.5 text-[var(--text)]" />
    </> : <>
      <label htmlFor="user-email" className="mb-2 block text-sm font-medium">Email</label>
      <input ref={emailRef} id="user-email" name="email" type="email" autoComplete="email" required disabled={busy} className="mb-4 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2.5 text-[var(--text)]" />
      <label htmlFor="user-password" className="mb-2 block text-sm font-medium">Password</label>
      <input ref={passwordRef} id="user-password" name="password" type="password" autoComplete="current-password" required disabled={busy} className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2.5 text-[var(--text)]" />
    </>}
    {error && <p role="alert" className="mt-3 text-sm text-[var(--error)]">{error}</p>}
    <button type="submit" disabled={busy} className="mt-5 w-full rounded-lg bg-[var(--primary)] px-4 py-2.5 font-medium text-white disabled:opacity-60">{busy ? "Signing in…" : "Sign in"}</button>
  </form></main>;
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell onLogout={() => void signOut()} logoutError={error} />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/workflows" element={<WorkflowsPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/tools" element={<ToolsPage />} />
            <Route path="/executions" element={<ExecutionsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
