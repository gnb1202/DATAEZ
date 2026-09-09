"use client";

import { useState } from "react";
import {
  LogOut,
  Mail,
  User,
  Trash2,
  AlertTriangle,
  Moon,
  Shield,
  Bell,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeSelect } from "../header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { Project } from "@/app/lib/api";

interface SettingsSectionProps {
  email: string;
  selectedProject: Project | null;
  onDeleteProject: (projectId: string) => Promise<void>;
  onLogout: () => void;
}

export function SettingsSection({
  email,
  selectedProject,
  onDeleteProject,
  onLogout,
}: SettingsSectionProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleDeleteProject = async () => {
    if (!selectedProject) return;
    setDeleting(true);
    try {
      await onDeleteProject(selectedProject.id);
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="max-w-3xl animate-in fade-in slide-in-from-bottom-4 duration-500">
      <Tabs defaultValue="profile" className="space-y-6">
        <TabsList className="bg-secondary">
          <TabsTrigger value="profile" className="gap-2">
            <User className="h-4 w-4" />
            프로필
          </TabsTrigger>
          <TabsTrigger value="appearance" className="gap-2">
            <Moon className="h-4 w-4" />
            화면 설정
          </TabsTrigger>
          {selectedProject && (
            <TabsTrigger value="project" className="gap-2">
              <Shield className="h-4 w-4" />
              가게
            </TabsTrigger>
          )}
        </TabsList>

        {/* Profile Tab */}
        <TabsContent
          value="profile"
          className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300"
        >
          <Card className="border-border">
            <CardHeader>
              <CardTitle className="text-base">계정 정보</CardTitle>
              <CardDescription>
                로그인된 계정의 기본 정보입니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-accent flex items-center justify-center text-sm font-bold text-accent-foreground">
                  {email ? email.slice(0, 2).toUpperCase() : "U"}
                </div>
                <div>
                  <p className="font-medium text-foreground">{email || "—"}</p>
                  <p className="text-sm text-muted-foreground">무료 플랜</p>
                </div>
              </div>

              <Separator />

              <div className="grid gap-4">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center">
                    <Mail className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">이메일</p>
                    <p className="text-sm font-medium text-foreground font-mono">
                      {email || "—"}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center">
                    <User className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">플랜</p>
                    <p className="text-sm font-medium text-foreground">무료</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border">
            <CardHeader>
              <CardTitle className="text-base">세션</CardTitle>
              <CardDescription>
                현재 세션에서 로그아웃합니다.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                onClick={onLogout}
                variant="destructive"
                size="sm"
                className="gap-2"
              >
                <LogOut className="h-4 w-4" />
                로그아웃
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Appearance Tab */}
        <TabsContent
          value="appearance"
          className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300"
        >
          <Card className="border-border">
            <CardHeader>
              <CardTitle className="text-base">테마</CardTitle>
              <CardDescription>
                인터페이스의 외관을 설정합니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Moon className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      화면 테마
                    </p>
                    <p className="text-xs text-muted-foreground">
                      다크·라이트 또는 시스템 설정을 따릅니다.
                    </p>
                  </div>
                </div>
                <ThemeSelect />
              </div>
            </CardContent>
          </Card>

          <Card className="border-border">
            <CardHeader>
              <CardTitle className="text-base">알림</CardTitle>
              <CardDescription>
                알림 설정을 관리합니다. (준비 중)
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-3 text-muted-foreground">
                <Bell className="h-5 w-5" />
                <p className="text-sm">알림 기능은 추후 추가될 예정입니다.</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Project Tab */}
        {selectedProject && (
          <TabsContent
            value="project"
            className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300"
          >
            <Card className="border-destructive/20">
              <CardHeader>
                <CardTitle className="text-base text-destructive">
                  가게 삭제
                </CardTitle>
                <CardDescription>
                  현재 선택된 가게{" "}
                  <span className="font-medium text-foreground">
                    &ldquo;{selectedProject.name}&rdquo;
                  </span>
                  을(를) 삭제합니다. 가게에 포함된 모든 장부와 데이터가
                  영구적으로 삭제됩니다.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!confirmDelete ? (
                  <Button
                    onClick={() => setConfirmDelete(true)}
                    variant="destructive"
                    size="sm"
                    className="gap-2"
                  >
                    <Trash2 className="h-4 w-4" />
                    가게 삭제
                  </Button>
                ) : (
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-destructive/10 border border-destructive/20 animate-in fade-in duration-200">
                    <AlertTriangle className="h-5 w-5 text-destructive shrink-0" />
                    <p className="text-sm text-destructive flex-1">
                      정말로 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.
                    </p>
                    <div className="flex gap-2 shrink-0">
                      <Button
                        onClick={() => setConfirmDelete(false)}
                        variant="outline"
                        size="sm"
                        disabled={deleting}
                      >
                        취소
                      </Button>
                      <Button
                        onClick={handleDeleteProject}
                        variant="destructive"
                        size="sm"
                        disabled={deleting}
                      >
                        {deleting ? "삭제 중..." : "삭제 확인"}
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
