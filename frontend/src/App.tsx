import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { login, logout, restoreSession } from "./api/auth";
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
    if (!credential || busy) return;
    setBusy(true); setError(null);
    try {
      await login(credential);
      if (credentialRef.current) credentialRef.current.value = "";
      setAuthenticated(true);
    } catch (reason) {
      if (credentialRef.current) credentialRef.current.value = "";
      setError(reason instanceof Error ? reason.message : "Sign in failed.");
    } finally { setBusy(false); }
  }

  async function signOut() {
    setBusy(true); setError(null);
    try { await logout(); setAuthenticated(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Sign out failed."); }
    finally { setBusy(false); }
  }

  if (checking) return <div className="grid min-h-screen place-items-center bg-[var(--bg)] text-[var(--secondary)]" role="status">Checking operator session…</div>;
  if (!authenticated) return <main className="grid min-h-screen place-items-center bg-[var(--bg)] px-4 text-[var(--text)]"><form onSubmit={(event) => void submit(event)} className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-8 shadow-2xl">
    <div className="mb-7 flex items-center gap-4"><img src="/assets/agentforge-logo.png" alt="AgentForge" className="h-14 w-14 rounded-xl"/><div><h1 className="text-xl font-semibold">Operator sign in</h1><p className="text-sm text-[var(--secondary)]">Authenticate to open AgentForge.</p></div></div>
    <label htmlFor="operator-credential" className="mb-2 block text-sm font-medium">Operator credential</label>
    <input ref={credentialRef} id="operator-credential" name="credential" type="password" autoComplete="current-password" required disabled={busy} className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2.5 text-[var(--text)]" />
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
