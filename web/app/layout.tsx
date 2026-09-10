import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import localFont from "next/font/local";
import { JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";

const vercelHost = process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL;
const siteUrl = process.env.NEXT_PUBLIC_SITE_URL?.trim() ||
  (vercelHost ? `https://${vercelHost}` : "http://localhost:3000");

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
  metadataBase: new URL(siteUrl),
  title: "DATA:EZ — 흩어진 매출을, 한눈에",
  description: "매출 파일을 모으고, 대화로 지표를 만들고, 내 대시보드에 저장하세요.",
  applicationName: "DATA:EZ",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "DATA:EZ — 흩어진 매출을, 한눈에",
    description: "매출 파일을 모으고, 대화로 지표를 만들고, 내 대시보드에 저장하세요.",
    images: [
      {
        url: "/og-dataez.png",
        width: 1200,
        height: 630,
        alt: "DATA:EZ — 흩어진 매출을, 한눈에",
      },
    ],
    type: "website",
    locale: "ko_KR",
  },
  twitter: {
    card: "summary_large_image",
    title: "DATA:EZ — 흩어진 매출을, 한눈에",
    description: "매출 파일을 모으고, 대화로 지표를 만들고, 내 대시보드에 저장하세요.",
    images: ["/og-dataez.png"],
  },
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
