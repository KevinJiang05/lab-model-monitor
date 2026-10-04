"use client";

import Link from "next/link";
import { useState } from "react";
import results from "@/lib/animation-results.json";
import styles from "./page.module.css";

type Sample = { requested_model: string; returned_model: string; status: string; html: string | null;
  elapsed_seconds: number; total_tokens: number | null; sha256: string | null; http_status: string | null };
const samples: Sample[] = results.samples;
const labels: Record<string, string> = { generated: "HTML 已生成 · 视觉待评价", incomplete: "输出截断", format_error: "未返回完整 SVG HTML", timeout: "请求超时", api_error: "接口失败" };

function preview(html: string) {
  // The original file is downloadable unchanged. Only the isolated preview gets a CSP.
  const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">`;
  return /<head\b[^>]*>/i.test(html) ? html.replace(/<head\b[^>]*>/i, match => match + policy)
    : html.replace(/<html\b[^>]*>/i, match => match + "<head>" + policy + "</head>");
}

function download(sample: Sample) {
  if (!sample.html) return;
  const url = URL.createObjectURL(new Blob([sample.html], { type: "text/html;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url; link.download = `${sample.requested_model}-sheep-submarine.html`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Animations() {
  const [active, setActive] = useState(0);
  const [revision, setRevision] = useState(0);
  const sample = samples[active];
  return <div className={styles.page}>
    <header className={styles.header}><Link href="/">实验室模型监测</Link><nav><Link href="/">糖果测试</Link><Link href="/animations" aria-current="page">动画测试</Link></nav></header>
    <main className={styles.main}>
      <div className={styles.title}><h1>绵羊驾驶潜艇</h1><span>SVG / HTML · 每模型 1 次</span></div>
      <p className={styles.prompt}>{results.prompt}</p>
      <div className={styles.tabs} role="tablist" aria-label="模型">{samples.map((s, index) => <button key={s.requested_model} role="tab" aria-selected={active === index} onClick={() => setActive(index)}>{s.requested_model}<span>{s.html ? "有交付物" : "无完整交付物"}</span></button>)}</div>
      {sample && <>
        <div className={styles.toolbar}><span>{labels[sample.status] || sample.status}{sample.http_status ? ` · HTTP ${sample.http_status}` : ""}</span><span>{sample.elapsed_seconds.toFixed(1)} 秒 · {sample.total_tokens === null ? "用量未返回" : `${sample.total_tokens.toLocaleString()} tokens`}</span><div><button disabled={!sample.html} onClick={() => void document.getElementById("animation-preview")?.requestFullscreen().catch(() => {})}>全屏预览</button><button disabled={!sample.html} onClick={() => setRevision(n => n + 1)}>重播</button><button disabled={!sample.html} onClick={() => download(sample)}>下载 HTML</button></div></div>
        {sample.html ? <iframe id="animation-preview" key={`${active}-${revision}`} className={styles.frame} title={`${sample.requested_model} 生成的动画`} sandbox="allow-scripts" referrerPolicy="no-referrer" srcDoc={preview(sample.html)} /> : <div className={styles.empty}>{labels[sample.status] || "没有可预览的完整 HTML"}</div>}
        <details className={styles.details}><summary>原始 HTML</summary><pre>{sample.html || "没有完整交付物。原始响应保留在本地数据库。"}</pre></details>
        <details className={styles.details}><summary>测试记录与预览说明</summary><p>提示词原样发送；另附交付要求：{results.instructions}模型输出未经人工修补。HTML 已生成不等于视觉测试通过。</p><p>预览在隔离窗口运行，禁止外部资源与网络请求；下载内容是模型原稿，仅去除外围 Markdown 代码围栏。</p><p>运行时间 {new Date(results.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Taipei" })} UTC+8 · {results.reasoning_effort} · {results.stream ? "流式" : "非流式"} · 输出上限 {results.max_output_tokens} tokens</p><p>运行 ID：{results.run_id}<br/>接口声明模型：{sample.returned_model || "未返回"}<br/>文件 SHA256：{sample.sha256 || "—"}</p></details>
      </>}
    </main>
  </div>;
}
