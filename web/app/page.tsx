"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BarChart3, ArrowRight, Loader2, Upload, MessageSquare, LineChart } from "lucide-react";
import { useAuth } from "./hooks/use-auth";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const steps = [
  {
    icon: Upload,
    title: "업로드",
    desc: "CSV, XLSX 파일을 간편하게 업로드",
  },
  {
    icon: MessageSquare,
    title: "질문",
    desc: "자연어로 데이터에 대해 질문하세요",
  },
  {
    icon: LineChart,
    title: "시각화",
    desc: "AI가 자동으로 차트와 인사이트 생성",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const { isAuthenticated, initializing, login, signup, loading } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!initializing && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [initializing, isAuthenticated, router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!email.trim() || !password.trim()) {
      setError("이메일과 비밀번호를 입력하세요.");
      return;
    }
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await signup(email, password, name);
      }
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "인증에 실패했습니다");
    }
  };

  if (initializing) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    );
  }

  if (isAuthenticated) return null;

  return (
    <div className="min-h-screen flex">
      {/* Left branding panel */}
      <div className="hidden lg:flex lg:w-1/2 bg-card border-r border-border flex-col justify-between p-12 relative overflow-hidden">
        {/* Subtle background gradient */}
        <div className="absolute inset-0 bg-gradient-to-br from-accent/5 via-transparent to-chart-1/5 pointer-events-none" />

        <div className="relative">
          <div
            className="flex items-center gap-3 mb-2 animate-in fade-in slide-in-from-left-4 duration-700"
            style={{ animationFillMode: "both" }}
          >
            <div className="w-10 h-10 rounded-lg bg-white flex items-center justify-center">
              <BarChart3 className="h-5 w-5 text-accent-foreground" />
            </div>
            <span className="text-3xl font-bold tracking-tight text-foreground">
              DATAEZ
            </span>
          </div>
          <p
            className="text-muted-foreground text-lg animate-in fade-in slide-in-from-left-4 duration-700"
            style={{ animationDelay: "100ms", animationFillMode: "both" }}
          >
            소상공인을 위한 데이터 시각화 자동화 도구
          </p>
        </div>

        <div className="relative space-y-6">
          {steps.map((item, i) => {
            const Icon = item.icon;
            return (
              <div
                key={item.title}
                className="flex items-start gap-4 group animate-in fade-in slide-in-from-left-4 duration-700"
                style={{
                  animationDelay: `${200 + i * 150}ms`,
                  animationFillMode: "both",
                }}
              >
                <div className="mt-0.5 h-10 w-10 rounded-xl bg-secondary flex items-center justify-center group-hover:bg-accent/10 transition-colors duration-300">
                  <Icon className="h-5 w-5 text-accent" />
                </div>
                <div>
                  <p className="font-semibold text-foreground">{item.title}</p>
                  <p className="text-muted-foreground text-sm">{item.desc}</p>
                </div>
              </div>
            );
          })}
        </div>

        <p className="relative text-muted-foreground text-sm">
          &copy; 2025 DATAEZ
        </p>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center p-8 bg-background">
        <div
          className="w-full max-w-md animate-in fade-in slide-in-from-bottom-4 duration-700"
          style={{ animationFillMode: "both" }}
        >
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-2 mb-8">
            <div className="w-9 h-9 rounded-lg bg-white flex items-center justify-center">
              <BarChart3 className="h-5 w-5 text-accent-foreground" />
            </div>
            <span className="text-2xl font-bold tracking-tight text-foreground">
              DATAEZ
            </span>
          </div>

          <h1 className="text-2xl font-bold mb-1 text-foreground">
            {mode === "login"
              ? "다시 오신 것을 환영합니다"
              : "계정 만들기"}
          </h1>
          <p className="text-muted-foreground mb-8">
            {mode === "login"
              ? "로그인하여 데이터를 분석하세요"
              : "몇 분 안에 데이터 시각화를 시작하세요"}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Mode toggle */}
            <div className="flex rounded-lg bg-secondary p-1">
              <button
                type="button"
                onClick={() => { setMode("login"); setError(""); }}
                className={cn(
                  "flex-1 py-2 text-sm font-medium rounded-md transition-all duration-200",
                  mode === "login"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                로그인
              </button>
              <button
                type="button"
                onClick={() => { setMode("signup"); setError(""); }}
                className={cn(
                  "flex-1 py-2 text-sm font-medium rounded-md transition-all duration-200",
                  mode === "signup"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                회원가입
              </button>
            </div>

            {mode === "signup" && (
              <div className="space-y-1.5 animate-in fade-in slide-in-from-top-2 duration-300">
                <Label>이름</Label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="이름 (선택사항)"
                  className="transition-all duration-200 focus:border-accent"
                />
              </div>
            )}

            <div className="space-y-1.5">
              <Label>이메일</Label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@example.com"
                className="transition-all duration-200 focus:border-accent"
              />
            </div>

            <div className="space-y-1.5">
              <Label>비밀번호</Label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="비밀번호를 입력하세요"
                className="transition-all duration-200 focus:border-accent"
              />
            </div>

            {error && (
              <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive animate-in fade-in duration-200">
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-accent text-accent-foreground hover:bg-accent/90 transition-colors"
              size="lg"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  {mode === "login" ? "로그인" : "회원가입"}
                  <ArrowRight className="h-4 w-4 ml-2" />
                </>
              )}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
