"use client";

import { FormEvent, useState } from "react";
import { Loader2, FolderKanban } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type ProjectCreateDialogProps = {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string, description: string) => Promise<void>;
  loading: boolean;
};

export function ProjectCreateDialog({
  open,
  onClose,
  onCreate,
  loading,
}: ProjectCreateDialogProps) {
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setError("");
    try {
      await onCreate(name.trim(), description.trim());
      setName(""); setDescription(""); onClose();
    } catch (e) { setError(e instanceof Error ? e.message : "가게를 만들지 못했습니다."); }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v && !loading) { setError(""); onClose(); }
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderKanban className="h-5 w-5 text-accent" />
            새 가게
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="project-name">가게 이름</Label>
            <Input
              id="project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예: 우리 카페"
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-desc">설명 (선택)</Label>
            <Input
              id="project-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="예: 강남점 매출/재고 관리"
            />
          </div>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <Button
            type="submit"
            disabled={!name.trim() || loading}
            className="w-full bg-accent text-accent-foreground hover:bg-accent/90"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              "만들기"
            )}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
