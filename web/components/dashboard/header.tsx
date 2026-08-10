"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Section } from "@/app/dashboard/page";
import type { Project, TableMeta } from "@/app/lib/api";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Bell, Search, Calendar, Home } from "lucide-react";

interface HeaderProps {
  activeSection: Section;
  selectedProject?: Project | null;
  selectedTable?: TableMeta | null;
  onNavigateHome: () => void;
  email?: string;
}

const sectionTitles: Record<Section, string> = {
  dashboard: "대시보드",
  "ai-chat": "AI 분석",
  tables: "장부 관리",
  settings: "설정",
};

function getInitials(email?: string): string {
  if (!email) return "U";
  const name = email.split("@")[0];
  if (name.length <= 2) return name.toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

export function Header({
  activeSection,
  selectedProject,
  selectedTable,
  onNavigateHome,
  email,
}: HeaderProps) {
  const [searchFocused, setSearchFocused] = useState(false);

  return (
    <header className="h-16 border-b border-border bg-background/80 backdrop-blur-sm sticky top-0 z-30 flex items-center justify-between px-6">
      {/* Left: Title + Date range */}
      <div className="flex items-center gap-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">
            {sectionTitles[activeSection]}
          </h1>
          <Breadcrumb className="mt-0.5">
            <BreadcrumbList className="text-xs">
              <BreadcrumbItem>
                <BreadcrumbLink
                  onClick={onNavigateHome}
                  className="cursor-pointer"
                >
                  <Home className="w-3 h-3" />
                </BreadcrumbLink>
              </BreadcrumbItem>

              {selectedProject && (
                <>
                  <BreadcrumbSeparator className="text-muted-foreground/50" />
                  <BreadcrumbItem>
                    {activeSection === "dashboard" && !selectedTable ? (
                      <BreadcrumbPage className="text-xs">
                        {selectedProject.name}
                      </BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink
                        onClick={onNavigateHome}
                        className="cursor-pointer text-xs"
                      >
                        {selectedProject.name}
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                </>
              )}

              {selectedTable && (
                <>
                  <BreadcrumbSeparator className="text-muted-foreground/50" />
                  <BreadcrumbItem>
                    <BreadcrumbPage className="text-xs">
                      {selectedTable.name}
                    </BreadcrumbPage>
                  </BreadcrumbItem>
                </>
              )}
            </BreadcrumbList>
          </Breadcrumb>
        </div>

        <div className="hidden md:flex items-center gap-2 text-sm text-muted-foreground">
          <Calendar className="w-4 h-4" />
          <span>최근 30일</span>
        </div>
      </div>

      {/* Right: Search + Notifications + Avatar */}
      <div className="flex items-center gap-4">
        {/* Search */}
        <div
          className={cn(
            "relative hidden md:flex items-center transition-all duration-300",
            searchFocused ? "w-64" : "w-48"
          )}
        >
          <Search className="absolute left-3 w-4 h-4 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            placeholder="검색..."
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            className="w-full h-9 pl-9 pr-4 rounded-lg bg-secondary border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/20 focus:border-accent transition-all duration-200"
          />
        </div>

        {/* Notifications */}
        <button aria-label="알림" className="relative w-9 h-9 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-all duration-200">
          <Bell className="w-5 h-5" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-accent rounded-full animate-pulse" />
        </button>

        {/* User avatar */}
        <button aria-label="사용자 메뉴" className="w-9 h-9 rounded-lg overflow-hidden bg-secondary ring-2 ring-transparent hover:ring-accent/50 transition-all duration-200">
          <div className="w-full h-full bg-gradient-to-br from-accent/80 to-chart-1 flex items-center justify-center text-xs font-semibold text-accent-foreground">
            {getInitials(email)}
          </div>
        </button>
      </div>
    </header>
  );
}
