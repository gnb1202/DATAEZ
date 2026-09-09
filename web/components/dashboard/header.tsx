"use client";

import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { Menu, PanelRightOpen, PanelRightClose } from "lucide-react";
import type { Section } from "@/app/dashboard/page";
import type { Project } from "@/app/lib/api";

const subscribe = () => () => {};
export function ThemeSelect() {
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  return <select aria-label="화면 테마" value={mounted ? theme : "dark"} onChange={(event) => setTheme(event.target.value)} className="h-9 w-[78px] rounded-lg border border-border bg-card px-2 text-xs">
    <option value="dark">다크</option><option value="light">라이트</option><option value="system">시스템</option>
  </select>;
}
const titles: Record<Section, string> = { dashboard: "대시보드", analysis: "분석 결과", history: "분석 이력", tables: "데이터 관리", settings: "설정" };
export function Header({ activeSection, selectedProject, chatOpen, onToggleChat, onOpenMenu }: {
  activeSection: Section; selectedProject: Project | null; chatOpen: boolean; onToggleChat: () => void; onOpenMenu: () => void;
}) {
  return <header className="flex h-[76px] shrink-0 items-center justify-between gap-2 border-b border-border px-3 sm:px-6">
    <div className="flex min-w-0 items-center gap-2">
      <button aria-label="작업 메뉴 열기" id="workspace-menu-toggle" onClick={onOpenMenu} className="rounded-lg p-2 text-muted-foreground md:hidden"><Menu size={20} /></button>
      <div className="min-w-0"><h1 className="truncate text-base font-bold sm:text-lg">{titles[activeSection]}</h1><p className="mt-1 truncate text-[11px] text-muted-foreground">{selectedProject?.name || "가게를 추가해 시작하세요"}</p></div>
    </div>
    <div className="flex shrink-0 items-center gap-2"><ThemeSelect /><button id="workspace-chat-toggle" aria-label={chatOpen ? "AI 채팅 닫기" : "AI 채팅 열기"} aria-expanded={chatOpen} aria-controls="workspace-chat" onClick={onToggleChat} className="flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-2.5 text-xs hover:bg-secondary">{chatOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}<span className="hidden sm:inline">AI 채팅</span></button></div>
  </header>;
}
