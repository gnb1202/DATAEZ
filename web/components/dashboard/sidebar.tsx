"use client";

import React, { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { Section } from "@/app/dashboard/page";
import type { Project } from "@/app/lib/api";
import {
  LayoutDashboard,
  Bot,
  Settings,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  TableProperties,
  Plus,
  ChevronDown,
  FolderKanban,
} from "lucide-react";

interface SidebarProps {
  activeSection: Section;
  onSectionChange: (section: Section) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  projects: Project[];
  selectedProjectId: string;
  onSelectProject: (projectId: string) => void;
  onCreateProject: () => void;
}

type NavItem = { id: Section; label: string; icon: React.ElementType };

const navItems: NavItem[] = [
  { id: "dashboard", label: "대시보드", icon: LayoutDashboard },
  { id: "ai-chat", label: "AI 분석", icon: Bot },
  { id: "tables", label: "장부 관리", icon: TableProperties },
  { id: "settings", label: "설정", icon: Settings },
];

export function Sidebar({
  activeSection,
  onSectionChange,
  collapsed,
  onCollapsedChange,
  projects,
  selectedProjectId,
  onSelectProject,
  onCreateProject,
}: SidebarProps) {
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!projectMenuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setProjectMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [projectMenuOpen]);

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 h-screen bg-sidebar border-r border-sidebar-border transition-all duration-300 ease-out flex flex-col",
        collapsed ? "w-[72px]" : "w-[260px]"
      )}
    >
      {/* Logo */}
      <div className="h-16 flex items-center px-4 border-b border-sidebar-border">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 bg-white">
            <BarChart3 className="w-5 h-5 text-accent-foreground" />
          </div>
          <span
            className={cn(
              "font-semibold text-lg text-sidebar-foreground whitespace-nowrap transition-all duration-300",
              collapsed ? "opacity-0 w-0" : "opacity-100 w-auto"
            )}
          >
            DATAEZ
          </span>
        </div>
      </div>

      {/* Project Selector */}
      {!collapsed && (
        <div className="px-3 pt-3 pb-1">
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setProjectMenuOpen(!projectMenuOpen)}
              aria-expanded={projectMenuOpen}
              aria-haspopup="listbox"
              className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-sidebar-accent/50 hover:bg-sidebar-accent text-sm transition-colors"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FolderKanban className="w-4 h-4 text-accent shrink-0" />
                <span className="truncate text-sidebar-foreground font-medium">
                  {selectedProject?.name || "프로젝트 선택"}
                </span>
              </div>
              <ChevronDown
                className={cn(
                  "w-4 h-4 text-muted-foreground shrink-0 transition-transform",
                  projectMenuOpen && "rotate-180"
                )}
              />
            </button>

            {projectMenuOpen && (
              <div role="listbox" aria-label="프로젝트 목록" className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-lg shadow-lg z-50 py-1 max-h-48 overflow-y-auto">
                {projects.map((p) => (
                  <button
                    key={p.id}
                    role="option"
                    aria-selected={p.id === selectedProjectId}
                    onClick={() => {
                      onSelectProject(p.id);
                      setProjectMenuOpen(false);
                    }}
                    className={cn(
                      "w-full text-left px-3 py-2 text-sm transition-colors",
                      p.id === selectedProjectId
                        ? "bg-accent/10 text-accent font-medium"
                        : "text-popover-foreground hover:bg-secondary"
                    )}
                  >
                    {p.name}
                  </button>
                ))}
                <div className="border-t border-border mt-1 pt-1" role="none">
                  <button
                    onClick={() => {
                      onCreateProject();
                      setProjectMenuOpen(false);
                    }}
                    role="option"
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    새 프로젝트
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Divider */}
      <div className="px-3 pt-2">
        <div className="border-t border-sidebar-border" />
      </div>

      {/* Navigation */}
      <nav aria-label="메인 메뉴" className="flex-1 px-3 py-3 space-y-1 overflow-hidden">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;

          return (
            <button
              key={item.id}
              onClick={() => onSectionChange(item.id)}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group relative",
                isActive
                  ? "bg-sidebar-accent text-sidebar-foreground"
                  : "text-muted-foreground hover:text-sidebar-foreground hover:bg-sidebar-accent/50"
              )}
            >
              <span
                className={cn(
                  "absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 rounded-r-full bg-accent transition-all duration-300",
                  isActive ? "opacity-100" : "opacity-0"
                )}
              />
              <Icon
                className={cn(
                  "w-5 h-5 shrink-0 transition-transform duration-200",
                  isActive ? "text-accent" : "group-hover:scale-110"
                )}
              />
              <span
                className={cn(
                  "whitespace-nowrap transition-all duration-300",
                  collapsed ? "opacity-0 w-0 overflow-hidden" : "opacity-100"
                )}
              >
                {item.label}
              </span>
            </button>
          );
        })}
      </nav>

      {/* Collapse button */}
      <div className="p-3 border-t border-sidebar-border">
        <button
          onClick={() => onCollapsedChange(!collapsed)}
          aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-sidebar-foreground hover:bg-sidebar-accent/50 transition-all duration-200"
        >
          {collapsed ? (
            <ChevronRight className="w-5 h-5" />
          ) : (
            <>
              <ChevronLeft className="w-5 h-5" />
              <span>접기</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
