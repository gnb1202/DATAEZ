"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../hooks/use-auth";
import { useStreaming } from "../hooks/use-streaming";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Header } from "@/components/dashboard/header";
import { ProjectCreateDialog } from "@/components/dashboard/project-create-dialog";
import FileUploadModal from "@/app/components/file-upload-modal";
import { ErrorBoundary } from "@/components/error-boundary";
import { DashboardProvider } from "../contexts/dashboard-context";
import type { Project, TableMeta, ChartData } from "../lib/api";

const SectionLoader = () => (
  <div className="flex items-center justify-center py-24">
    <Loader2 className="h-8 w-8 animate-spin text-accent" />
  </div>
);

const DashboardSection = dynamic(
  () => import("@/components/dashboard/sections/dashboard-section").then((m) => ({ default: m.DashboardSection })),
  { loading: SectionLoader }
);
const AiChatSection = dynamic(
  () => import("@/components/dashboard/sections/ai-chat-section").then((m) => ({ default: m.AiChatSection })),
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

export type Section = "dashboard" | "ai-chat" | "tables" | "settings";

export default function DashboardPage() {
  const router = useRouter();
  const { isAuthenticated, initializing, token, email, logout, apiFetchWithRefresh } =
    useAuth();
  const { loading: streamLoading, streamingSteps, mutationsPerformed, schemaChanged, error: streamError, sendMessage } =
    useStreaming({ getToken: () => token });

  // Navigation
  const [activeSection, setActiveSection] = useState<Section>("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Projects
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
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
  const selectedTable = tables.find((t) => t.id === selectedTableId) || null;

  // Auth guard
  useEffect(() => {
    if (!initializing && !isAuthenticated) {
      router.replace("/");
    }
  }, [initializing, isAuthenticated, router]);

  // ── Projects ──

  const fetchProjects = useCallback(async () => {
    try {
      const res = await apiFetchWithRefresh("/api/projects");
      if (res.ok) {
        const data = await res.json();
        const list: Project[] = data.projects || [];
        setProjects(list);
        // Auto-select first project if none selected
        if (!selectedProjectId && list.length > 0) {
          setSelectedProjectId(list[0].id);
        }
      }
    } catch {
      // ignore
    }
  }, [apiFetchWithRefresh, selectedProjectId]);

  useEffect(() => {
    if (isAuthenticated) fetchProjects();
  }, [isAuthenticated, fetchProjects]);

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
        setProjects((prev) => [data, ...prev]);
        setSelectedProjectId(data.id);
        setTables([]);
        setSelectedTableId("");
        toast.success("프로젝트가 생성되었습니다");
      } else {
        toast.error("프로젝트 생성에 실패했습니다");
      }
    } catch {
      toast.error("프로젝트 생성 중 오류가 발생했습니다");
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
        setProjects((prev) => prev.filter((p) => p.id !== projectId));
        if (selectedProjectId === projectId) {
          setSelectedProjectId("");
          setTables([]);
          setSelectedTableId("");
        }
        toast.success("프로젝트가 삭제되었습니다");
      } else {
        toast.error("프로젝트 삭제에 실패했습니다");
      }
    } catch {
      toast.error("프로젝트 삭제 중 오류가 발생했습니다");
    }
  };

  const handleSelectProject = (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedTableId("");
    setTables([]);
  };

  // ── Tables ──

  const fetchTables = useCallback(async () => {
    if (!selectedProjectId) return;
    try {
      const res = await apiFetchWithRefresh(
        `/api/projects/${selectedProjectId}/tables`
      );
      if (res.ok) {
        const data = await res.json();
        const list: TableMeta[] = data.tables || [];
        setTables(list);
        // Auto-select first table if none selected
        if (!selectedTableId && list.length > 0) {
          setSelectedTableId(list[0].id);
        }
      }
    } catch {
      // ignore
    }
  }, [selectedProjectId, apiFetchWithRefresh, selectedTableId]);

  useEffect(() => {
    if (selectedProjectId) fetchTables();
  }, [selectedProjectId, fetchTables]);

  // Refresh tables when mutations are performed or schema changed by AI
  useEffect(() => {
    if ((mutationsPerformed || schemaChanged) && selectedProjectId) {
      fetchTables();
    }
  }, [mutationsPerformed, schemaChanged, selectedProjectId, fetchTables]);

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
      const formData = new FormData();
      formData.append("file", file);
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
        setSelectedTableId(data.id);
        setActiveSection("tables");
        toast.success("파일을 성공적으로 가져왔습니다");
      } else {
        toast.error("파일 가져오기에 실패했습니다");
      }
    } catch {
      toast.error("파일 가져오기 중 오류가 발생했습니다");
    } finally {
      setUploadLoading(false);
    }
  };

  // ── Mutation callback ──

  const handleMutationPerformed = useCallback(() => {
    if (selectedProjectId) {
      fetchTables();
    }
  }, [selectedProjectId, fetchTables]);

  // ── Pin chart to dashboard ──

  const handlePinChart = useCallback(
    async (chart: ChartData) => {
      if (!selectedProjectId) return;
      try {
        const widgetCount = await apiFetchWithRefresh(
          `/api/dashboard/widgets?project_id=${selectedProjectId}`
        ).then((r) => r.json()).then((d) => (d.widgets || []).length);

        const pinRes = await apiFetchWithRefresh("/api/dashboard/widgets", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: selectedProjectId,
            widget_type: "chart",
            title: chart.title,
            widget_data: {
              chart_type: chart.chart_type,
              x_key: chart.x_key,
              y_key: chart.y_key,
              data: chart.data,
            },
            layout: {
              x: (widgetCount * 4) % 12,
              y: Math.floor((widgetCount * 4) / 12) * 4,
              w: 6,
              h: 4,
            },
          }),
        });
        if (pinRes.ok) {
          toast.success("차트를 대시보드에 고정했습니다");
        }
      } catch {
        toast.error("차트 고정에 실패했습니다");
      }
    },
    [selectedProjectId, apiFetchWithRefresh]
  );

  // ── Render ──

  if (initializing) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  if (!isAuthenticated) return null;

  const renderSection = () => {
    switch (activeSection) {
      case "dashboard":
        return (
          <DashboardSection
            onNavigateToChat={() => setActiveSection("ai-chat")}
            onNavigateToTables={() => setActiveSection("tables")}
          />
        );
      case "ai-chat":
        return (
          <AiChatSection
            sendMessage={sendMessage}
            streamLoading={streamLoading}
            streamingSteps={streamingSteps}
            streamError={streamError}
            onMutationPerformed={handleMutationPerformed}
            onPinChart={handlePinChart}
          />
        );
      case "tables":
        return (
          <TablesSection
            tables={tables}
            selectedTableId={selectedTableId}
            onSelectTable={handleSelectTable}
            onImportClick={() => setUploadModalOpen(true)}
            onDeleteTable={handleDeleteTable}
            onNavigateToChat={() => setActiveSection("ai-chat")}
          />
        );
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
      <div className="flex min-h-screen bg-background">
        <Sidebar
          activeSection={activeSection}
          onSectionChange={setActiveSection}
          collapsed={sidebarCollapsed}
          onCollapsedChange={setSidebarCollapsed}
          projects={projects}
          selectedProjectId={selectedProjectId}
          onSelectProject={handleSelectProject}
          onCreateProject={() => setProjectCreateOpen(true)}
        />
        <div
          className={`flex-1 flex flex-col transition-all duration-300 ease-out ${
            sidebarCollapsed ? "ml-[72px]" : "ml-[260px]"
          }`}
        >
          <Header
            activeSection={activeSection}
            selectedProject={selectedProject}
            selectedTable={selectedTable}
            onNavigateHome={() => setActiveSection("dashboard")}
            email={email}
          />
          <main className="flex-1 p-6 overflow-auto">
            <ErrorBoundary key={activeSection}>
              <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                {renderSection()}
              </div>
            </ErrorBoundary>
          </main>
        </div>

        <ProjectCreateDialog
          open={projectCreateOpen}
          onClose={() => setProjectCreateOpen(false)}
          onCreate={handleCreateProject}
          loading={projectCreateLoading}
        />

        <FileUploadModal
          open={uploadModalOpen}
          onClose={() => setUploadModalOpen(false)}
          onUpload={handleImportCSV}
          loading={uploadLoading}
        />
      </div>
    </DashboardProvider>
  );
}
