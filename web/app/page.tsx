"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { useAuth } from "./hooks/use-auth";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DataEzLogo } from "@/components/brand/dataez-logo";
import { API_CONFIGURED } from "./lib/api";

const steps = [
  {
    number: "01",
    title: "매출 파일을 모으고",
    desc: "CSV·XLSX 원본을 가게별로 보관해요.",
  },
  {
    number: "02",
    title: "필요한 숫자를 물어보고",
    desc: "일상적인 말로 기간과 계산 기준을 정해요.",
  },
  {
    number: "03",
    title: "내 대시보드에 저장해요",
    desc: "계산 근거를 확인한 차트와 지표를 다시 사용해요.",
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
    <div className="flex min-h-dvh">
      {/* Left branding panel */}
      <div className="brand-login-panel relative hidden overflow-hidden border-r lg:flex lg:w-[54%] lg:flex-col lg:justify-between lg:gap-10 lg:p-14 xl:p-18">
        <div className="brand-login-panel__image pointer-events-none absolute inset-0" />
        <div className="brand-login-panel__scrim pointer-events-none absolute inset-0" />

        <div className="relative z-10">
          <div
            className="animate-in fade-in slide-in-from-left-4 duration-700"
            style={{ animationFillMode: "both" }}
          >
            <DataEzLogo tone="dark" className="w-48" />
          </div>
        </div>

        <div className="relative z-10 max-w-xl">
          <p className="brand-login-panel__eyebrow mb-5 text-sm font-bold tracking-[0.18em]">GATHERED LEDGER</p>
          <h1 className="text-balance text-5xl font-bold leading-[1.12] tracking-[-0.045em] xl:text-6xl">
            흩어진 매출을,<br />한눈에.
          </h1>
          <p className="brand-login-panel__body mt-6 max-w-lg text-lg leading-8">
            여러 파일과 가게의 숫자를 모아 묻고, 확인하고,<br className="hidden xl:block" /> 내 방식대로 저장하세요.
          </p>

          <div className="mt-12 space-y-5">
            {steps.map((item, i) => (
              <div
                key={item.title}
                className="group flex items-start gap-4 animate-in fade-in slide-in-from-left-4 duration-700"
                style={{
                  animationDelay: `${200 + i * 150}ms`,
                  animationFillMode: "both",
                }}
              >
                <span className="brand-login-panel__step-number mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-[11px] font-bold transition-colors duration-300">
                  {item.number}
                </span>
                <div className="pt-0.5">
                  <p className="brand-login-panel__step-title font-bold">{item.title}</p>
                  <p className="brand-login-panel__step-desc mt-1 text-sm">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="brand-login-panel__footer relative z-10 text-xs tracking-[0.12em]">
          &copy; 2026 DATA:EZ
        </p>
      </div>

      {/* Right form panel */}
      <div className="flex min-w-0 flex-1 items-center justify-center bg-background p-8">
        <div
          className="w-full max-w-md animate-in fade-in slide-in-from-bottom-4 duration-700"
          style={{ animationFillMode: "both" }}
        >
          {/* Mobile logo */}
          <div className="mb-10 lg:hidden">
            <DataEzLogo className="w-40" />
          </div>

          <h1 className="mb-2 break-keep text-3xl font-bold tracking-[-0.035em] text-foreground">
            {mode === "login"
              ? "우리 가게의 숫자를 확인해보세요"
              : "내 대시보드를 시작하세요"}
          </h1>
          <p className="mb-8 break-keep text-muted-foreground">
            {mode === "login"
              ? "로그인하면 저장한 파일과 지표를 이어서 볼 수 있어요."
              : "가게와 매출 파일을 등록하고 첫 지표를 만들어보세요."}
          </p>

          {!API_CONFIGURED && (
            <div role="status" className="mb-6 rounded-xl border border-border bg-card px-4 py-4 text-sm leading-6">
              <p className="font-semibold text-foreground">체험 서비스를 준비하고 있어요</p>
              <p className="mt-1 text-muted-foreground">준비가 끝나면 매출 파일을 올리고, AI와 대화하며 대시보드를 만들 수 있습니다.</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <fieldset disabled={!API_CONFIGURED} className="space-y-4">
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
                <Label htmlFor="auth-name">이름</Label>
                <Input
                  id="auth-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="이름 (선택사항)"
                  className="transition-all duration-200 focus:border-accent"
                />
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="auth-email">이메일</Label>
              <Input
                id="auth-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@example.com"
                className="transition-all duration-200 focus:border-accent"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="auth-password">비밀번호</Label>
              <Input
                id="auth-password"
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
              disabled={loading || !API_CONFIGURED}
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
            </fieldset>
          </form>
        </div>
      </div>
    </div>
  );
}
