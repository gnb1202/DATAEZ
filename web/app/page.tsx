"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { useAuth } from "./hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DataEzLogo } from "@/components/brand/dataez-logo";
import { API_CONFIGURED } from "./lib/api";

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
      <div className="brand-login-panel relative hidden overflow-hidden border-r lg:flex lg:min-h-[760px] lg:w-[54%] lg:flex-col lg:justify-between lg:gap-10 lg:p-12 xl:p-14">
        <div aria-hidden="true" className="brand-login-panel__image pointer-events-none absolute inset-0" />
        <div aria-hidden="true" className="brand-login-panel__scrim pointer-events-none absolute inset-0" />

        <div className="relative z-10">
          <div
            className="animate-in fade-in slide-in-from-left-4 duration-700"
            style={{ animationFillMode: "both" }}
          >
            <DataEzLogo tone="dark" className="w-48" />
          </div>
        </div>

        <div className="relative z-10 mt-auto max-w-xl pt-72">
          <h1 className="text-balance text-5xl font-bold leading-[1.12] tracking-[-0.045em] xl:text-6xl">
            우리 가게 매출,<br />한눈에.
          </h1>
          <p className="brand-login-panel__body mt-6 max-w-lg text-lg leading-8">
            매출 파일을 모으고, 궁금한 것을 물어보세요.<br />
            내 가게에 필요한 통계가 대시보드로 완성됩니다.
          </p>

        </div>

        <p className="brand-login-panel__footer relative z-10 text-xs tracking-[0.12em]">
          &copy; 2026 DATA:EZ
        </p>
      </div>

      {/* Right form panel */}
      <div className="flex min-w-0 flex-1 items-center justify-center bg-card px-7 py-12 sm:px-12 lg:px-16">
        <div
          className="w-full max-w-md animate-in fade-in slide-in-from-bottom-4 duration-700"
          style={{ animationFillMode: "both" }}
        >
          {/* Mobile logo */}
          <div className="mb-10 lg:hidden">
            <DataEzLogo className="w-40" />
          </div>

          <h1 className="mb-2.5 break-keep text-[28px] font-bold leading-snug tracking-[-0.035em] text-foreground">
            {mode === "login"
              ? "내 가게의 숫자를 만나보세요"
              : "우리 가게 매출, 여기서 시작해요"}
          </h1>
          <p className="mb-10 break-keep text-sm leading-7 text-muted-foreground">
            {mode === "login"
              ? <>로그인하고 우리 가게의 매출을 살펴보세요.<br />저장한 파일과 대시보드를 이어서 볼 수 있어요.</>
              : <>계정을 만들고 매출 파일을 모아보세요.<br />궁금한 숫자를 물어보며 첫 대시보드를 만들어보세요.</>}
          </p>

          {!API_CONFIGURED && (
            <div role="status" className="mb-6 rounded-xl border border-border bg-card px-4 py-4 text-sm leading-6">
              <p className="font-semibold text-foreground">체험 서비스를 준비하고 있어요</p>
              <p className="mt-1 text-muted-foreground">준비가 끝나면 매출 파일을 올리고, AI와 대화하며 대시보드를 만들 수 있습니다.</p>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <fieldset disabled={!API_CONFIGURED || loading} className="space-y-5">

            {mode === "signup" && (
              <div className="space-y-2.5 animate-in fade-in slide-in-from-top-2 duration-300">
                <Label htmlFor="auth-name" className="text-[13px] font-normal">이름</Label>
                <Input
                  id="auth-name"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="이름 (선택사항)"
                  className="h-[50px] rounded-[7px] border-border bg-transparent px-3.5 text-sm shadow-none dark:bg-transparent"
                />
              </div>
            )}

            <div className="space-y-2.5">
              <Label htmlFor="auth-email" className="text-[13px] font-normal">이메일</Label>
              <Input
                id="auth-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="h-[50px] rounded-[7px] border-border bg-transparent px-3.5 text-sm shadow-none dark:bg-transparent"
              />
            </div>

            <div className="space-y-2.5">
              <Label htmlFor="auth-password" className="text-[13px] font-normal">비밀번호</Label>
              <Input
                id="auth-password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="비밀번호를 입력하세요"
                className="h-[50px] rounded-[7px] border-border bg-transparent px-3.5 text-sm shadow-none dark:bg-transparent"
              />
            </div>

            {error && (
              <div role="alert" className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive animate-in fade-in duration-200">
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={loading || !API_CONFIGURED}
              className="mt-1 h-[52px] w-full rounded-[7px] bg-accent font-bold text-accent-foreground hover:bg-accent/90 transition-colors"
              size="lg"
            >
              {loading ? (
                <><Loader2 className="h-4 w-4 animate-spin" /><span>처리 중...</span></>
              ) : (
                <>
                  {mode === "login" ? "로그인" : "회원가입"}
                  <ArrowRight className="h-4 w-4 ml-2" />
                </>
              )}
            </Button>
            </fieldset>
          </form>
          <p className="mt-6 text-center text-xs leading-6 text-muted-foreground">
            {mode === "login" ? "아직 계정이 없으신가요?" : "이미 계정이 있으신가요?"}
            <button
              type="button"
              disabled={loading}
              onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}
              className="ml-2 rounded-sm font-medium text-foreground underline-offset-4 hover:underline disabled:opacity-50"
            >
              {mode === "login" ? "회원가입" : "로그인"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
