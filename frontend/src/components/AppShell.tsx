import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const handleMenuClick = () => setMobileOpen((currentValue) => !currentValue);
  const handleMobileClose = () => setMobileOpen(false);

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex min-h-screen">
        <Sidebar
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed((currentValue) => !currentValue)}
          mobileOpen={mobileOpen}
          onToggleMobile={handleMobileClose}
        />
        <div className="flex min-h-screen flex-1 flex-col">
          <Header onMenuClick={handleMenuClick} />
          <main className="flex-1 p-4 md:p-6" aria-label="Main content">
            <Outlet context={{ currentPath: location.pathname }} />
          </main>
        </div>
      </div>
    </div>
  );
}
