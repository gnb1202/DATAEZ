"use client";

import { LayoutDashboard, Database, History, Settings, Plus, PanelLeftClose, PanelLeftOpen, Store, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Project } from "@/app/lib/api";
import type { Section } from "@/app/dashboard/page";
import { DataEzLogo } from "@/components/brand/dataez-logo";

export interface SidebarProps {
  activeSection: Section;
  onSectionChange: (section: Section) => void;
  collapsed: boolean;
  onCollapsedChange: (value: boolean) => void;
  projects: Project[];
  selectedProjectId: string;
  onSelectProject: (id: string) => void;
  onCreateProject: () => void;
  onNewAnalysis: () => void;
  email: string;
  mobile?: boolean;
}
const navigation = [
  { id: "dashboard" as const, label: "대시보드", icon: LayoutDashboard },
  { id: "tables" as const, label: "데이터 관리", icon: Database },
  { id: "history" as const, label: "분석 이력", icon: History },
];
export function Sidebar({ activeSection, onSectionChange, collapsed, onCollapsedChange, projects, selectedProjectId, onSelectProject, onCreateProject, onNewAnalysis, email, mobile }: SidebarProps) {
  const compact = collapsed && !mobile;
  return (
    <div className={cn("flex h-full shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground", compact ? "w-[76px]" : "w-[232px]", mobile && "w-full border-0")}>
      <div className={cn("flex h-[76px] shrink-0 items-center gap-2", compact ? "justify-center" : "justify-between px-5")}>
        <button onClick={() => onSectionChange("dashboard")} aria-label="DATA:EZ 대시보드" className={cn("flex min-h-11 shrink-0 items-center justify-center rounded-sm transition-opacity hover:opacity-80", compact && "w-11")}>
          <DataEzLogo symbolOnly={compact} className={compact ? "h-7 w-7" : "w-[136px]"} />
        </button>
        {!compact && !mobile && <button aria-label="메뉴 접기" onClick={() => onCollapsedChange(true)} className="rounded p-1 text-muted-foreground hover:text-foreground"><PanelLeftClose size={17} /></button>}
      </div>
      <div className="px-3">
        {compact ? <button onClick={() => onCollapsedChange(false)} aria-label="가게 선택 메뉴 펼치기" className="flex h-11 w-full items-center justify-center rounded-lg border border-border"><Store size={18} /></button> : <>
          <label className="mb-2 block px-1 text-[11px] text-muted-foreground">현재 작업 가게</label>
          <select aria-label="현재 작업 가게" value={selectedProjectId} onChange={(event) => onSelectProject(event.target.value)} className="h-11 w-full min-w-0 rounded-lg border border-border bg-[var(--surface-input)] px-2 text-sm">
            {!projects.length && <option value="">가게를 추가하세요</option>}
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
          <button onClick={onCreateProject} className="mt-2 flex items-center gap-1 px-1 py-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={13} />가게 추가</button>
        </>}
        <button onClick={onNewAnalysis} title="새 분석" aria-label="새 분석" className="mt-7 mb-6 flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-[var(--line-strong)] bg-card text-sm font-medium hover:bg-secondary"><Plus size={17} />{!compact && "새 분석"}</button>
      </div>
      <nav aria-label="작업 메뉴" className="space-y-1 px-3">
        {navigation.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => onSectionChange(id)} title={label} aria-label={label} aria-current={activeSection === id ? "page" : undefined} className={cn("flex h-11 w-full items-center gap-3 rounded-lg px-3 text-sm transition-colors", compact && "justify-center px-0", activeSection === id ? "bg-sidebar-accent text-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground")}><Icon size={18} />{!compact && label}</button>)}
      </nav>
      <div className="mt-auto space-y-2 p-3">
        {compact && <button aria-label="메뉴 펼치기" onClick={() => onCollapsedChange(false)} className="flex h-10 w-full items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary"><PanelLeftOpen size={18} /></button>}
        <button onClick={() => onSectionChange("settings")} title="설정 및 계정" aria-label="설정 및 계정" aria-current={activeSection === "settings" ? "page" : undefined} className={cn("flex w-full items-center gap-3 rounded-lg p-3 text-muted-foreground hover:bg-secondary", compact && "justify-center", activeSection === "settings" && "bg-sidebar-accent text-foreground")}>
          <Settings size={18} className="shrink-0" />{!compact && <span className="min-w-0 flex-1 text-left"><span className="block text-sm text-foreground">설정 및 계정</span><span className="mt-1 block truncate text-[11px]">{email}</span></span>}{!compact && <ArrowUpRight size={13} />}
        </button>
      </div>
    </div>
  );
}
