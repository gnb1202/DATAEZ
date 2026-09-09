"use client";

import { FormEvent, useCallback, useState, DragEvent } from "react";
import { Upload, FileSpreadsheet, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type FileUploadModalProps = {
  open: boolean;
  onClose: () => void;
  onUpload: (file: File, tableName: string) => Promise<void>;
  loading: boolean;
};

const MAX_FILE_SIZE_MB = 20;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;
const ALLOWED_EXTENSIONS = [".csv", ".xlsx", ".xls"];

function validateFile(f: File): string | null {
  const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return "CSV 또는 XLSX 파일만 업로드 가능합니다.";
  }
  if (f.size > MAX_FILE_SIZE_BYTES) {
    return `파일 크기가 ${MAX_FILE_SIZE_MB}MB를 초과합니다. (${(f.size / 1024 / 1024).toFixed(1)}MB)`;
  }
  return null;
}

export default function FileUploadModal({ open, onClose, onUpload, loading }: FileUploadModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [tableName, setTableName] = useState("");
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (!dropped) return;
    const err = validateFile(dropped);
    if (err) {
      setFileError(err);
      setFile(null);
      return;
    }
    setFileError(null);
    setFile(dropped);
    if (!tableName) {
      const nameWithoutExt = dropped.name.replace(/\.(csv|xlsx?)$/i, "");
      setTableName(nameWithoutExt);
    }
  }, [tableName]);

  const handleFileSelect = (f: File | null) => {
    if (f) {
      const err = validateFile(f);
      if (err) {
        setFileError(err);
        setFile(null);
        return;
      }
    }
    setFileError(null);
    setFile(f);
    if (f && !tableName) {
      const nameWithoutExt = f.name.replace(/\.(csv|xlsx?)$/i, "");
      setTableName(nameWithoutExt);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || !tableName.trim()) return;
    setFileError(null);
    try {
      await onUpload(file, tableName.trim());
      setFile(null);
      setTableName("");
      onClose();
    } catch (err) {
      setFileError(err instanceof Error ? err.message : "파일을 가져오지 못했습니다.");
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { onClose(); setFile(null); setTableName(""); } }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5 text-accent" />
            CSV 가져오기
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="table-name">장부 이름</Label>
            <Input
              id="table-name"
              value={tableName}
              onChange={(e) => setTableName(e.target.value)}
              placeholder="예: 매출장부"
            />
          </div>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            className={cn(
              "border-2 border-dashed rounded-xl p-8 text-center transition-colors relative",
              dragging
                ? "border-accent bg-accent/5"
                : file
                ? "border-success/50 bg-success/5"
                : "border-border hover:border-muted-foreground"
            )}
          >
            {file ? (
              <div className="flex flex-col items-center gap-2">
                <FileSpreadsheet className="h-10 w-10 text-success" />
                <p className="text-sm font-medium text-foreground">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
                <button
                  type="button"
                  onClick={() => setFile(null)}
                  className="text-xs text-destructive hover:text-destructive/80"
                >
                  삭제
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <Upload className="h-10 w-10 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium text-foreground">
                    파일을 끌어다 놓으세요
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    또는 클릭하여 선택 (CSV, XLSX)
                  </p>
                </div>
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={(e) => handleFileSelect(e.target.files?.[0] || null)}
                  className="absolute inset-0 opacity-0 cursor-pointer"
                />
              </div>
            )}
          </div>

          {fileError && (
            <p role="alert" className="text-sm text-destructive">{fileError}</p>
          )}

          <Button
            type="submit"
            disabled={!file || !tableName.trim() || loading}
            className="w-full bg-accent text-accent-foreground hover:bg-accent/90"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Upload className="h-4 w-4" />
                가져오기
              </>
            )}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
