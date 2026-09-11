"use client";

import { uploadSourceForm } from "@/app/lib/direct-upload";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { Loader2, ArrowRight, BarChart3, History, MessageSquare } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../hooks/use-auth";
import { useWorkspaceAnalysis } from "../hooks/use-workspace-analysis";
import { FileLibrary } from "@/components/dashboard/file-library";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import type { LibraryFile, LibraryReference } from "../lib/file-library";
import { ChatDock } from "@/components/dashboard/chat-dock";
import { AnalysisWorkspaceResult } from "@/components/dashboard/analysis-workspace-result";
import { useChartSaving } from "../hooks/use-chart-saving";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Header } from "@/components/dashboard/header";
import { ProjectCreateDialog } from "@/components/dashboard/project-create-dialog";
import FileUploadModal from "@/app/components/file-upload-modal";
import { ErrorBoundary } from "@/components/error-boundary";
import { DashboardProvider } from "../contexts/dashboard-context";
import type { Project, TableMeta } from "../lib/api";
import { parseError } from "../lib/api";

const SectionLoader = () => (
  <div className="flex items-center justify-center py-24">
    <Loader2 className="h-8 w-8 animate-spin text-accent" />
  </div>
);

const DashboardSection = dynamic(
  () => import("@/components/dashboard/sections/dashboard-section").then((m) => ({ default: m.DashboardSection })),
  { loading: SectionLoader }
);
const TablesSection = dynamic(
  () => import("@/components/dashboard/sections/tables-section").then((m) => ({ default: m.TablesSection })),
  { loading: SectionLoader }
);
const SettingsSection = dynamic(
  () => import("@/components/dashboard/sections/settings-section").then((m) => ({ default: m.SettingsSection })),
  { loading: SectionLoader }
);

export type Section = "dashboard" | "analysis" | "history" | "tables" | "settings";

export default function DashboardPage() {
  const router = useRouter();
  const auth = useAuth();
  const { isAuthenticated, initializing, apiFetchWithRefresh } = auth;
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState(false);
  const [reload, setReload] = useState(0);
  const [sampleStart, setSampleStart] = useState<{ project: Project; file: LibraryFile; view?: "analysis" | "dashboard" } | null>(null);
  useEffect(() => {
    if (!initializing && !isAuthenticated) router.replace("/");
  }, [initializing, isAuthenticated, router]);
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await apiFetchWithRefresh("/api/projects");
        if (!res.ok) throw new Error(await parseError(res));
        const data = await res.json();
        if (cancelled) return;
        const list: Project[] = data.projects || [];
        const requested = new URLSearchParams(window.location.search).get("project");
        const owned = list.find((item) => item.id === requested);
        if (requested && !owned) toast.error("연결된 가게에 접근할 수 없습니다.");
        setProjects(list);
        setSelectedProjectId(owned?.id || list[0]?.id || "");
        setProjectsError(false);
      } catch { if (!cancelled) setProjectsError(true); }
      finally { if (!cancelled) setProjectsLoading(false); }
    };
    void load();
    return () => { cancelled = true; };
  }, [isAuthenticated, apiFetchWithRefresh, reload]);
  if (initializing || (isAuthenticated && projectsLoading)) return <div className="flex min-h-screen items-center justify-center bg-background"><Loader2 aria-label="작업 공간 준비 중" className="h-6 w-6 animate-spin text-accent" /></div>;
  if (!isAuthenticated) return null;
  if (projectsError) return <div className="flex min-h-screen flex-col items-center justify-center gap-4"><p>가게 목록을 불러오지 못했습니다.</p><Button onClick={() => { setProjectsLoading(true); setReload((value) => value + 1); }}>다시 시도</Button></div>;
  return <StoreWorkspace key={selectedProjectId} projects={projects} selectedProjectId={selectedProjectId}
    sampleStart={sampleStart}
    onSampleConsumed={() => setSampleStart(null)}
    onSampleReady={(project, file, view) => { setProjects(prev => [project, ...prev.filter(item => item.id !== project.id)]); setSampleStart({project,file,view}); setSelectedProjectId(project.id); }}
    onSelectProject={setSelectedProjectId}
    onProjectCreated={(project) => { setProjects((prev) => [project, ...prev]); setSelectedProjectId(project.id); }}
    onProjectDeleted={(id) => { setProjects((prev) => prev.filter((item) => item.id !== id)); setSelectedProjectId((current) => current === id ? projects.find((item) => item.id !== id)?.id || "" : current); }}
    token={auth.token} email={auth.email} logout={auth.logout} apiFetchWithRefresh={apiFetchWithRefresh} />;
}

function StoreWorkspace({ sampleStart, onSampleConsumed, onSampleReady, projects, selectedProjectId, onSelectProject, onProjectCreated, onProjectDeleted, token, email, logout, apiFetchWithRefresh }: {
  sampleStart: { project: Project; file: LibraryFile; view?: "analysis" | "dashboard" } | null; onSampleConsumed: () => void; onSampleReady: (project: Project, file: LibraryFile, view?: "analysis" | "dashboard") => void;
  projects: Project[]; selectedProjectId: string; onSelectProject: (id: string) => void;
  onProjectCreated: (project: Project) => void; onProjectDeleted: (id: string) => void;
  token: string; email: string; logout: () => Promise<void>;
  apiFetchWithRefresh: (path: string, init?: RequestInit) => Promise<Response>;
}) {
  const router = useRouter();
  const analysis = useWorkspaceAnalysis(selectedProjectId, token, apiFetchWithRefresh);
  const { reset: resetAnalysis, setComposer: setAnalysisComposer } = analysis;
  const [chatOpen, setChatOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [librarySearch, setLibrarySearch] = useState("");
  const [dataTab, setDataTab] = useState("ledgers");
  const [menuOpen, setMenuOpen] = useState(false);
  const [dashboardRevision, setDashboardRevision] = useState(0);
  const [focusWidgetId, setFocusWidgetId] = useState<string>();
  const [dataRevision, setDataRevision] = useState(0);
  const mounted = useRef(true);
  const tablesRequest = useRef(0);
  useEffect(() => {
    mounted.current = true;
    const invalidate = () => { mounted.current = false; tablesRequest.current++; };
    return invalidate;
  }, []);

  // Navigation
  const [activeSection, setActiveSection] = useState<Section>("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    const section = new URLSearchParams(window.location.search).get("section");
    if (section === "tables" || section === "dashboard" || section === "analysis" || section === "history" || section === "settings") setActiveSection(section);
    if (section === "ai-chat") { setActiveSection("analysis"); setChatOpen(true); }
  }, []);

  useEffect(() => {
    if (!sampleStart || sampleStart.project.id !== selectedProjectId) return;
    if (sampleStart.view === "dashboard") {
      setActiveSection("dashboard"); setChatOpen(false); setDashboardRevision(value => value + 1); onSampleConsumed(); return;
    }
    const file = sampleStart.file, binding = file.bindings[0];
    const text = "선택한 샘플 파일의 원본 행만 사용해 paid_at 날짜별 amount 합계를 원화 꺾은선 그래프로 미리 보여줘. 음수 취소를 그대로 차감하고 전체 기간을 사용해. 재계산 가능한 지표로 준비하되 아직 저장하지 마.";
    resetAnalysis(text);
    setAnalysisComposer({ text, file: null, libraryFiles: [{...binding, file_id:file.file_id,filename:file.filename,content_hash:file.content_hash,scope:"original_file"}] });
    setActiveSection("analysis"); setChatOpen(true); onSampleConsumed();
  }, [sampleStart, selectedProjectId, resetAnalysis, setAnalysisComposer, onSampleConsumed]);

  // Projects
  const [projectCreateOpen, setProjectCreateOpen] = useState(false);
  const [projectCreateLoading, setProjectCreateLoading] = useState(false);

  // Tables
  const [tables, setTables] = useState<TableMeta[]>([]);
  const [selectedTableId, setSelectedTableId] = useState<string>("");

  // CSV Import
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadLoading, setUploadLoading] = useState(false);

  // Derived
  const selectedProject = projects.find((p) => p.id === selectedProjectId) || null;
  const savedChart = useCallback(() => setDashboardRevision((value) => value + 1), []);
  const chartSaving = useChartSaving(selectedProjectId, analysis.result, activeSection === "analysis", apiFetchWithRefresh, savedChart);

  useEffect(() => {
    if (!selectedProjectId) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("project") !== selectedProjectId) {
      url.searchParams.delete("source");
      url.searchParams.delete("batch");
    }
    url.searchParams.set("project", selectedProjectId);
    url.searchParams.set("section", activeSection);
    window.history.replaceState(null, "", url);
  }, [selectedProjectId, activeSection]);

  const handleCreateProject = async (name: string, description: string) => {
    setProjectCreateLoading(true);
    try {
      const res = await apiFetchWithRefresh("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description }),
      });
      if (res.ok) {
        const data = await res.json();
        onProjectCreated(data);
        setTables([]);
        setSelectedTableId("");
        toast.success("가게가 생성되었습니다");
      } else {
        throw new Error(await parseError(res));
      }
    } catch (error) {
      throw error instanceof Error ? error : new Error("가게 생성 중 오류가 발생했습니다.");
    } finally {
      setProjectCreateLoading(false);
    }
  };

  const handleDeleteProject = async (projectId: string) => {
    try {
      const res = await apiFetchWithRefresh(`/api/projects/${projectId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        onProjectDeleted(projectId);
        if (selectedProjectId === projectId) {
          setTables([]);
          setSelectedTableId("");
        }
        toast.success("가게가 삭제되었습니다");
      } else {
        toast.error("가게 삭제에 실패했습니다");
      }
    } catch {
      toast.error("가게 삭제 중 오류가 발생했습니다");
    }
  };

  // ── Tables ──

  const fetchTables = useCallback(async () => {
    if (!selectedProjectId) return;
    const request = ++tablesRequest.current;
    try {
      const res = await apiFetchWithRefresh(
        `/api/projects/${selectedProjectId}/tables`
      );
      if (res.ok) {
        const data = await res.json();
        if (!mounted.current || request !== tablesRequest.current) return;
        const list: TableMeta[] = data.tables || [];
        setTables(list);
        // A review link should also select its source's ledger in the header
        // and data preview. Preserve a selection made while this fetch ran.
        if (list.length > 0) {
          const params = new URLSearchParams(window.location.search);
          const linked = params.get("project") === selectedProjectId
            ? list.find((table) => table.ledger_source_id === params.get("source")) : undefined;
          setSelectedTableId((current) => current || linked?.id || list[0].id);
        }
      }
    } catch {
      // ignore
    }
  }, [selectedProjectId, apiFetchWithRefresh]);

  useEffect(() => {
    if (selectedProjectId) fetchTables();
  }, [selectedProjectId, fetchTables]);

  // Refresh tables when mutations are performed or schema changed by AI
  useEffect(() => {
    if ((analysis.stream.mutationsPerformed || analysis.stream.schemaChanged) && selectedProjectId) {
      fetchTables();
    }
  }, [analysis.stream.mutationsPerformed, analysis.stream.schemaChanged, selectedProjectId, fetchTables]);

  const handleSelectTable = (tableId: string) => {
    setSelectedTableId(tableId);
  };

  const handleDeleteTable = async (tableId: string) => {
    if (!selectedProjectId) return;
    try {
      const res = await apiFetchWithRefresh(
        `/api/projects/${selectedProjectId}/tables/${tableId}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        setTables((prev) => prev.filter((t) => t.id !== tableId));
        if (selectedTableId === tableId) {
          setSelectedTableId("");
        }
        toast.success("장부가 삭제되었습니다");
      } else {
        toast.error("장부 삭제에 실패했습니다");
      }
    } catch {
      toast.error("장부 삭제 중 오류가 발생했습니다");
    }
  };

  // ── CSV Import ──

  const handleImportCSV = async (file: File, tableName: string) => {
    if (!selectedProjectId) return;
    setUploadLoading(true);
    try {
      const formData = await uploadSourceForm(apiFetchWithRefresh, file, selectedProjectId!);
      formData.append("table_name", tableName);
      const res = await apiFetchWithRefresh(
        `/api/projects/${selectedProjectId}/tables/import`,
        {
          method: "POST",
          body: formData,
        }
      );
      if (res.ok) {
        const data = await res.json();
        await fetchTables();
        if (!mounted.current) return;
        setSelectedTableId(data.id);
        setActiveSection("tables");
        toast.success("파일을 성공적으로 가져왔습니다");
      } else {
        throw new Error(await parseError(res));
      }
    } finally {
      setUploadLoading(false);
    }
  };

  const navigate = (section: Section) => { setActiveSection(section); setMenuOpen(false); };
  const startAnalysis = (text = "") => {
    analysis.reset(text);
    setActiveSection("analysis");
    setChatOpen(true);
    setMenuOpen(false);
  };
  const openResult = (id: string) => { analysis.setResultId(id); setActiveSection("analysis"); if (window.matchMedia("(max-width: 1100px)").matches) setChatOpen(false); };
  const followWorkspaceLink = (event: React.MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as Element).closest("a");
    if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
    const target = new URL(anchor.href, window.location.href);
    if (target.origin !== window.location.origin || target.pathname !== "/dashboard" || target.searchParams.get("project") !== selectedProjectId || target.searchParams.get("section") !== "tables") return;
    event.preventDefault();
    window.history.replaceState(null, "", target);
    const linkedTable = tables.find((table) => table.ledger_source_id === target.searchParams.get("source"));
    if (linkedTable) setSelectedTableId(linkedTable.id);
    setDataTab("ledgers");
    setDataRevision((value) => value + 1);
    setActiveSection("tables");
    if (window.matchMedia("(max-width: 1100px)").matches) setChatOpen(false);
  };
  const sidebarProps = {
    activeSection, onSectionChange: navigate, collapsed: sidebarCollapsed, onCollapsedChange: setSidebarCollapsed,
    projects, selectedProjectId, onSelectProject, onCreateProject: () => { setMenuOpen(false); setProjectCreateOpen(true); },
    onNewAnalysis: () => startAnalysis(), email,
  };

  const openLibrary = (search = "") => { setLibrarySearch(search); setLibraryOpen(true); };
  const selectLibrary = (files: LibraryReference[]) => {
    if (analysis.loading || analysis.composer.file) return;
    analysis.setComposer((prev) => ({ ...prev, libraryFiles: files }));
    setLibraryOpen(false); setChatOpen(true);
  };
  const renderSection = () => {
    switch (activeSection) {
      case "dashboard":
        return (
          <DashboardSection key={dashboardRevision}
            focusWidgetId={focusWidgetId}
            onNavigateToChat={() => setChatOpen(true)}
            onNavigateToTables={() => setActiveSection("tables")}
            onCreateStore={() => setProjectCreateOpen(true)}
            onStartMetricChat={startAnalysis}
            onSampleReady={onSampleReady}
            onOpenLibrary={() => { setDataTab("files"); setActiveSection("tables"); }}
          />
        );
      case "analysis":
        return <div className="mx-auto max-w-5xl space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs text-muted-foreground">분석 작업 공간</p><h2 className="mt-2 text-xl font-bold">{analysis.result?.charts?.[0]?.title || "데이터에서 답을 찾아보세요"}</h2><p className="mt-2 text-sm text-muted-foreground">결과를 확인하고 필요한 차트를 대시보드에 저장하세요.</p></div><Button variant="outline" onClick={() => setChatOpen(true)} className="gap-2"><MessageSquare size={15} />대화 이어가기</Button></div>
          {analysis.result ? <AnalysisWorkspaceResult message={analysis.result} storeName={selectedProject?.name || ""} onOpenLibrary={openLibrary} state={chartSaving.state} onSave={chartSaving.save} onOpenWidget={(id) => { setFocusWidgetId(id); setActiveSection("dashboard"); if (window.matchMedia("(max-width: 1100px)").matches) setChatOpen(false); }} /> : <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--line-strong)] bg-card px-5 text-center"><BarChart3 className="mb-5 h-9 w-9 text-accent" /><h3 className="font-bold">{analysis.loading ? "요청한 내용을 분석하고 있어요" : analysis.messageLoading ? "분석 이력을 불러오고 있어요" : "어떤 매출이 궁금하신가요?"}</h3><p className="mt-3 max-w-sm text-sm leading-6 text-muted-foreground">오른쪽 채팅에서 가게의 장부와 파일을 바탕으로 분석을 요청하세요.</p><Button onClick={() => setChatOpen(true)} className="mt-6 gap-2">AI 채팅 열기<ArrowRight size={15} /></Button></div>}
          {analysis.error && <p role="status" className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">{analysis.error}</p>}
        </div>;
      case "history":
        return <div className="mx-auto max-w-4xl space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-bold">가게의 분석 이력</h2><p className="mt-2 text-sm text-muted-foreground">이전 질문과 결과를 다시 열고 대화를 이어가세요.</p></div><Button variant="outline" disabled={analysis.historyLoading} onClick={() => void analysis.refreshHistory()}>새로고침</Button></div>
          {analysis.historyLoading && <p role="status" className="text-sm text-muted-foreground">이력을 불러오는 중…</p>}
          {analysis.error && <p role="status" className="text-sm text-destructive">{analysis.error}</p>}
          {!analysis.historyLoading && !analysis.conversations.length ? <div className="rounded-xl border border-dashed border-[var(--line-strong)] bg-card px-5 py-16 text-center"><History className="mx-auto mb-4 h-8 w-8 text-muted-foreground" /><h3 className="font-bold">아직 분석 이력이 없습니다</h3><p className="mt-2 text-sm text-muted-foreground">첫 질문을 보내면 여기에 대화가 저장됩니다.</p><Button className="mt-5" onClick={() => startAnalysis()}>새 분석 시작</Button></div> : <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">{analysis.conversations.map((conversation) => <button key={conversation.conversation_id} onClick={() => { void analysis.openConversation(conversation.conversation_id); setActiveSection("analysis"); setChatOpen(true); }} className="flex w-full items-center gap-4 p-5 text-left hover:bg-secondary"><MessageSquare size={18} className="shrink-0 text-muted-foreground" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{conversation.title || "새 분석"}</span><span className="mt-1 block text-xs text-muted-foreground">{conversation.updated_at || conversation.created_at ? new Date(conversation.updated_at || conversation.created_at!).toLocaleDateString("ko-KR") : "저장된 대화"}</span></span><ArrowRight size={16} className="text-muted-foreground" /></button>)}</div>}
        </div>;
      case "tables":
        return <div className="space-y-6"><div className="flex gap-2 border-b border-border pb-3" aria-label="데이터 관리 보기"><Button variant={dataTab === "ledgers" ? "secondary" : "ghost"} onClick={() => setDataTab("ledgers")}>분석 장부</Button><Button variant={dataTab === "files" ? "secondary" : "ghost"} onClick={() => setDataTab("files")}>파일 보관함</Button></div>{dataTab === "files" ? <FileLibrary initial={analysis.composer.libraryFiles} onSelect={selectLibrary} onPrepared={() => void fetchTables()} disabled={analysis.loading || !!analysis.composer.file} /> : <TablesSection
            key={`${selectedProjectId}:${dataRevision}`}
            tables={tables}
            selectedTableId={selectedTableId}
            onSelectTable={handleSelectTable}
            onImportClick={() => setUploadModalOpen(true)}
            onDeleteTable={handleDeleteTable}
            onNavigateToChat={() => setChatOpen(true)}
            onTablesChange={fetchTables}
            onOpenDashboard={() => setActiveSection("dashboard")}
          />}</div>;
      case "settings":
        return (
          <SettingsSection
            email={email}
            selectedProject={selectedProject}
            onDeleteProject={handleDeleteProject}
            onLogout={async () => {
              await logout();
              router.replace("/");
            }}
          />
        );
      default:
        return null;
    }
  };

  return (
    <DashboardProvider selectedProjectId={selectedProjectId} apiFetch={apiFetchWithRefresh}>
      <div onClick={followWorkspaceLink} className="flex h-dvh min-h-0 overflow-hidden bg-background">
        <a href="#workspace-main" className="sr-only z-[100] rounded bg-card p-3 focus:not-sr-only focus:fixed focus:left-3 focus:top-3">본문으로 이동</a>
        <div className="hidden shrink-0 md:block"><Sidebar {...sidebarProps} /></div>
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}><SheetContent side="left" className="w-[280px] gap-0 bg-sidebar" onCloseAutoFocus={(event) => { event.preventDefault(); document.getElementById("workspace-menu-toggle")?.focus(); }}><SheetTitle className="sr-only">작업 메뉴</SheetTitle><SheetDescription className="sr-only">가게를 선택하거나 작업 화면을 이동합니다.</SheetDescription><Sidebar {...sidebarProps} mobile /></SheetContent></Sheet>
        <div className="flex min-w-0 flex-1 flex-col">
          <Header activeSection={activeSection} selectedProject={selectedProject} chatOpen={chatOpen} onToggleChat={() => setChatOpen((value) => !value)} onOpenMenu={() => setMenuOpen(true)} />
          <main id="workspace-main" tabIndex={-1} className="min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain p-4 sm:p-6 lg:p-8">
            <ErrorBoundary key={activeSection}>{renderSection()}</ErrorBoundary>
          </main>
        </div>
        <ChatDock onOpenLibrary={openLibrary} analysis={analysis} open={chatOpen} onOpenChange={setChatOpen} onOpenResult={openResult} storeName={selectedProject?.name || "가게 미선택"} disabled={!selectedProjectId} />
        <Dialog open={libraryOpen} onOpenChange={setLibraryOpen}><DialogContent className="max-h-[88dvh] overflow-y-auto sm:max-w-4xl"><DialogTitle>보관함에서 파일 선택</DialogTitle><DialogDescription>파일과 연결된 가게·장부를 확인하고 AI 채팅에 추가하세요.</DialogDescription><FileLibrary key={`${selectedProjectId}:${librarySearch}`} picker initialSearch={librarySearch} initial={analysis.composer.libraryFiles} onSelect={selectLibrary} onPrepared={() => void fetchTables()} disabled={analysis.loading || !!analysis.composer.file} /></DialogContent></Dialog>
        <ProjectCreateDialog open={projectCreateOpen} onClose={() => setProjectCreateOpen(false)} onCreate={handleCreateProject} loading={projectCreateLoading} />
        <FileUploadModal open={uploadModalOpen} onClose={() => setUploadModalOpen(false)} onUpload={handleImportCSV} loading={uploadLoading} />
      </div>
    </DashboardProvider>
  );
}
