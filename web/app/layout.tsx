import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import localFont from "next/font/local";
import { JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";

const spoqaHanSansNeo = localFont({
  src: [
    { path: "./fonts/spoqa-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/spoqa-500.woff2", weight: "500", style: "normal" },
    { path: "./fonts/spoqa-700.woff2", weight: "700", style: "normal" },
  ],
  display: "swap",
  variable: "--font-spoqa",
  adjustFontFallback: false,
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

const notoSansKR = localFont({
  src: [{ path: "./fonts/noto-variable.woff2", weight: "100 900", style: "normal" }],
  display: "swap",
  variable: "--font-noto-sans-kr",
  preload: false,
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: "DATAEZ",
  description: "소상공인을 위한 데이터 시각화 자동화 도구",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className="dark" suppressHydrationWarning>
      <body
        className={`${spoqaHanSansNeo.variable} ${jetbrainsMono.variable} ${notoSansKR.variable} font-sans antialiased`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          {children}
          <Toaster richColors position="bottom-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
