import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "实验室模型监测",
  description: "GPT-6 Astra 与 GPT-6.1 Sol 的糖果推理测试、动画生成作品和运行记录。",
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
