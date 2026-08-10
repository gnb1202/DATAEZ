"use client";

import { createContext, useContext } from "react";

type ApiFetch = (path: string, init?: RequestInit) => Promise<Response>;

interface DashboardContextValue {
  selectedProjectId: string;
  apiFetch: ApiFetch;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function DashboardProvider({
  selectedProjectId,
  apiFetch,
  children,
}: DashboardContextValue & { children: React.ReactNode }) {
  return (
    <DashboardContext.Provider value={{ selectedProjectId, apiFetch }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) {
    throw new Error("useDashboard must be used within a DashboardProvider");
  }
  return ctx;
}
