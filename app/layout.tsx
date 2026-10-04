import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "实验室模型监测 · Candy Test",
  description: "GPT-6 Astra 与 GPT-6.1 Sol 的每日糖果题结果、接口可用性和历史记录。",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
