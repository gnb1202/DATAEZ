"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  TableProperties,
  Plus,
  Upload,
  Trash2,
  Loader2,
  Database,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { useDashboard } from "@/app/contexts/dashboard-context";
import type { TableMeta } from "@/app/lib/api";

const ROW_HEIGHT = 36;
const MAX_TABLE_HEIGHT = 520;

function VirtualizedTable({
  data,
  columns,
  numericColumns,
  containerRef,
}: {
  data: Record<string, unknown>[];
  columns: string[];
  numericColumns: Set<string>;
  containerRef: React.RefObject<HTMLDivElement | null>;
}) {
  const visibleCols = columns.filter((c) => c !== "_row_id");
  const rowVirtualizer = useVirtualizer({
    count: data.length,
    getScrollElement: () => containerRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  });

  return (
    <div
      ref={containerRef}
      className="rounded-xl border border-border bg-card overflow-auto"
      style={{ maxHeight: MAX_TABLE_HEIGHT }}
    >
      <Table>
        <TableHeader>
          <TableRow className="border-border hover:bg-transparent">
            {visibleCols.map((col) => (
              <TableHead
                key={col}
                className={cn("whitespace-nowrap", numericColumns.has(col) && "text-right")}
              >
                {col}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.length <= 30 ? (
            data.map((row, idx) => (
              <TableRow key={idx} className="border-border hover:bg-secondary/30 transition-colors">
                {visibleCols.map((col) => {
                  const isNum = numericColumns.has(col);
                  const display = String(row[col] ?? "");
                  return (
                    <TableCell
                      key={col}
                      className={cn(
                        "text-sm whitespace-nowrap",
                        isNum ? "text-right font-semibold tabular-nums text-foreground" : "text-foreground/90"
                      )}
                    >
                      {isNum && display && !isNaN(Number(display)) ? Number(display).toLocaleString() : display}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))
          ) : (
            <>
              <tr style={{ height: rowVirtualizer.getVirtualItems()[0]?.start ?? 0 }} />
              {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                const row = data[virtualRow.index];
                return (
                  <TableRow
                    key={virtualRow.index}
                    ref={rowVirtualizer.measureElement}
                    data-index={virtualRow.index}
                    className="border-border hover:bg-secondary/30 transition-colors"
                  >
                    {visibleCols.map((col) => {
                      const isNum = numericColumns.has(col);
                      const display = String(row[col] ?? "");
                      return (
                        <TableCell
                          key={col}
                          className={cn(
                            "text-sm whitespace-nowrap",
                            isNum ? "text-right font-semibold tabular-nums text-foreground" : "text-foreground/90"
                          )}
                        >
                          {isNum && display && !isNaN(Number(display)) ? Number(display).toLocaleString() : display}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
              <tr style={{ height: rowVirtualizer.getTotalSize() - (rowVirtualizer.getVirtualItems().at(-1)?.end ?? 0) }} />
            </>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

interface TablesSectionProps {
  tables: TableMeta[];
  selectedTableId: string;
  onSelectTable: (tableId: string) => void;
  onImportClick: () => void;
  onDeleteTable: (tableId: string) => Promise<void>;
  onNavigateToChat: () => void;
}

export function TablesSection({
  tables,
  selectedTableId,
  onSelectTable,
  onImportClick,
  onDeleteTable,
  onNavigateToChat,
}: TablesSectionProps) {
  const { selectedProjectId: projectId, apiFetch } = useDashboard();
  const [previewData, setPreviewData] = useState<Record<string, unknown>[]>([]);
  const [previewColumns, setPreviewColumns] = useState<string[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewTotal, setPreviewTotal] = useState(0);
  const [previewPage, setPreviewPage] = useState(0);
  const pageSize = 100;
  const tableContainerRef = useRef<HTMLDivElement>(null);

  const selectedTable = tables.find((t) => t.id === selectedTableId);

  const fetchPreview = useCallback(
    async (tableId: string, page: number) => {
      if (!projectId || !tableId) return;
      setPreviewLoading(true);
      try {
        const offset = page * pageSize;
        const res = await apiFetch(
          `/api/projects/${projectId}/tables/${tableId}/data?limit=${pageSize}&offset=${offset}`
        );
        if (res.ok) {
          const data = await res.json();
          setPreviewData(data.rows || []);
          const cols = (data.columns || []) as (string | { name: string })[];
          setPreviewColumns(
            cols.map((c) => (typeof c === "string" ? c : c.name))
          );
          setPreviewTotal(data.total_count ?? 0);
        }
      } catch {
        // ignore
      } finally {
        setPreviewLoading(false);
      }
    },
    [projectId, apiFetch]
  );

  useEffect(() => {
    if (selectedTableId) {
      setPreviewPage(0);
      fetchPreview(selectedTableId, 0);
    } else {
      setPreviewData([]);
      setPreviewColumns([]);
    }
  }, [selectedTableId, fetchPreview]);

  const handlePageChange = (newPage: number) => {
    setPreviewPage(newPage);
    fetchPreview(selectedTableId, newPage);
  };

  const totalPages = Math.ceil(previewTotal / pageSize);

  // 숫자 컬럼 자동 감지 (첫 5행 샘플링)
  const numericColumns = new Set<string>();
  if (previewData.length > 0) {
    for (const col of previewColumns) {
      if (col === "_row_id") continue;
      const sample = previewData.slice(0, 5);
      const allNumeric = sample.every((row) => {
        const v = row[col];
        if (v === null || v === undefined || v === "") return true;
        return !isNaN(Number(v));
      });
      const hasValue = sample.some(
        (row) => row[col] !== null && row[col] !== undefined && row[col] !== ""
      );
      if (allNumeric && hasValue) numericColumns.add(col);
    }
  }

  if (!projectId) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="h-20 w-20 rounded-2xl bg-secondary flex items-center justify-center mb-6">
          <Database className="h-10 w-10 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold text-foreground mb-2">
          프로젝트를 먼저 선택해주세요
        </h3>
        <p className="text-sm text-muted-foreground max-w-md">
          사이드바에서 프로젝트를 선택하면 장부를 관리할 수 있습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-accent/10 flex items-center justify-center">
            <TableProperties className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-foreground">장부 관리</h2>
            <p className="text-sm text-muted-foreground">
              장부를 생성하고 데이터를 관리하세요
            </p>
          </div>
        </div>
        <Button
          onClick={onImportClick}
          className="gap-2 bg-accent text-accent-foreground hover:bg-accent/90"
        >
          <Upload className="h-4 w-4" />
          CSV 가져오기
        </Button>
      </div>

      {/* Table cards */}
      {tables.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center py-16 text-center border border-dashed border-border rounded-xl animate-in fade-in slide-in-from-bottom-4 duration-500"
          style={{ animationDelay: "100ms", animationFillMode: "both" }}
        >
          <div className="h-16 w-16 rounded-2xl bg-secondary flex items-center justify-center mb-4">
            <TableProperties className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-base font-semibold text-foreground mb-2">
            아직 장부가 없습니다
          </h3>
          <p className="text-sm text-muted-foreground mb-4 max-w-sm">
            CSV 파일을 가져오거나 빈 장부를 생성해보세요.
          </p>
          <Button
            onClick={onImportClick}
            size="sm"
            className="gap-2 bg-accent text-accent-foreground hover:bg-accent/90"
          >
            <Upload className="h-4 w-4" />
            CSV 가져오기
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {tables.map((t, index) => (
            <div
              key={t.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelectTable(t.id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelectTable(t.id); }}
              className={cn(
                "group relative text-left p-4 rounded-xl border transition-all duration-300 cursor-pointer overflow-hidden animate-in fade-in slide-in-from-bottom-4",
                t.id === selectedTableId
                  ? "border-accent bg-accent/5 ring-1 ring-accent/20"
                  : "border-border bg-card hover:border-accent/50"
              )}
              style={{
                animationDelay: `${index * 100}ms`,
                animationFillMode: "both",
              }}
            >
              {/* Hover gradient */}
              <div className="absolute inset-0 bg-gradient-to-br from-accent/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

              <div className="relative">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2 mb-2">
                    <TableProperties
                      className={cn(
                        "h-4 w-4 transition-colors duration-200",
                        t.id === selectedTableId
                          ? "text-accent"
                          : "text-muted-foreground group-hover:text-accent"
                      )}
                    />
                    <span className="font-medium text-foreground text-sm">
                      {t.name}
                    </span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteTable(t.id);
                    }}
                    aria-label={`${t.name} 삭제`}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-destructive/10 transition-all"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                  </button>
                </div>
                {t.description && (
                  <p className="text-xs text-muted-foreground mb-2 line-clamp-1">
                    {t.description}
                  </p>
                )}
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="text-xs font-mono">
                    {t.row_count.toLocaleString()}행
                  </Badge>
                  <Badge variant="secondary" className="text-xs font-mono">
                    {t.columns_schema.length}열
                  </Badge>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Data preview */}
      {selectedTable && (
        <div
          className="space-y-3 animate-in fade-in slide-in-from-bottom-4 duration-500"
          style={{ animationDelay: "200ms", animationFillMode: "both" }}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">
              데이터 미리보기 — {selectedTable.name}
            </h3>
            <Button
              onClick={onNavigateToChat}
              variant="outline"
              size="sm"
              className="gap-2 hover:border-accent/50 transition-colors"
            >
              <Plus className="h-4 w-4" />
              AI로 분석
            </Button>
          </div>

          {previewLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-accent" />
            </div>
          ) : previewData.length === 0 ? (
            <div className="text-center py-12 text-sm text-muted-foreground border border-dashed border-border rounded-xl">
              데이터가 없습니다
            </div>
          ) : (
            <>
              <VirtualizedTable
                data={previewData}
                columns={previewColumns}
                numericColumns={numericColumns}
                containerRef={tableContainerRef}
              />

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-secondary/30 rounded-b-xl">
                  <span className="text-sm text-muted-foreground">
                    {previewPage * pageSize + 1} -{" "}
                    {Math.min((previewPage + 1) * pageSize, previewTotal)} /{" "}
                    {previewTotal.toLocaleString()}행
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={previewPage === 0}
                      onClick={() => handlePageChange(previewPage - 1)}
                      className="hover:border-accent/50 transition-colors"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="px-3 py-1.5 rounded-lg text-sm bg-accent text-accent-foreground font-medium">
                      {previewPage + 1}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      / {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={previewPage >= totalPages - 1}
                      onClick={() => handlePageChange(previewPage + 1)}
                      className="hover:border-accent/50 transition-colors"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
