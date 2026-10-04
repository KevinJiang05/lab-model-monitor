"use client";

import TestHeader from "../test-header";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import results from "@/lib/animation-results.json";
import styles from "./page.module.css";

type Sample = { requested_model: string; returned_model: string; status: string; html: string | null;
  elapsed_seconds: number; total_tokens: number | null; sha256: string | null; http_status: string | null };
const samples: Sample[] = results.samples;
const testedAt = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(results.created_at));
const thumbnails: Record<string, string> = {
  a8ab7ce7a24b6f5115f70f8ddf702cc147d6457117b0fd0a6f75337edc3112bd: "/animations/astra.png",
  b89dea6c15c119b266f6c6bb363f31ca0e20abd2fa48ce0112270fe9ec43a0c4: "/animations/sol.png",
};
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
  const [active, setActive] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const sample = active === null ? null : samples[active];
  useEffect(() => {
    if (active === null) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.showModal();
    return () => { document.body.style.overflow = overflow; };
  }, [active]);
  return <div className={styles.page}>
    <TestHeader active="animation" />
    <main className={styles.main}>
      <div className={`test-heading ${styles.heading}`}><h1>动画测试</h1><p>{results.prompt}</p></div>
      <div className={styles.grid}>{samples.map((s, index) => <article className={styles.card} key={s.requested_model}>
        <button className={styles.thumbnail} disabled={!s.html} onClick={() => setActive(index)} aria-label={`放大预览 ${s.requested_model}`}>
          {s.html && thumbnails[s.sha256 || ""] ? <Image src={thumbnails[s.sha256 || ""]} width={1366} height={900} alt={`${s.requested_model} 的绵羊潜艇动画截图`} unoptimized /> : <span>{s.html ? "点击预览动画" : labels[s.status] || s.status}</span>}
          {s.html && <span className={styles.play}>点击播放 ↗</span>}
        </button>
        <div className={styles.cardBody}><h2>{s.requested_model}</h2><p className={styles.runMeta}><time dateTime={results.created_at}>{testedAt} UTC+8</time><span>推理等级：{results.reasoning_effort}</span></p><p>{s.elapsed_seconds.toFixed(1)} 秒 · {s.total_tokens === null ? "用量未返回" : `${s.total_tokens.toLocaleString()} tokens`}</p><div><button disabled={!s.html} onClick={() => setActive(index)}>放大预览</button><button disabled={!s.html} onClick={() => download(s)}>下载 HTML</button></div></div>
      </article>)}</div>
      <p className={styles.note}>缩略图为本轮作品截图。点击后播放原始动画。</p>
      <dialog ref={dialog} className={styles.dialog} onClose={() => setActive(null)} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      {sample && <div className={styles.dialogBody}>
        <div className={styles.dialogHeading}><h2>{sample.requested_model}</h2><button autoFocus onClick={() => dialog.current?.close()} aria-label="关闭预览">关闭 ×</button></div>
        <div className={styles.toolbar}><span>{labels[sample.status] || sample.status}{sample.http_status ? ` · HTTP ${sample.http_status}` : ""}</span><span>{sample.elapsed_seconds.toFixed(1)} 秒 · {sample.total_tokens === null ? "用量未返回" : `${sample.total_tokens.toLocaleString()} tokens`}</span><div><button disabled={!sample.html} onClick={() => void document.getElementById("animation-preview")?.requestFullscreen().catch(() => {})}>全屏预览</button><button disabled={!sample.html} onClick={() => setRevision(n => n + 1)}>重播</button><button disabled={!sample.html} onClick={() => download(sample)}>下载 HTML</button></div></div>
        {sample.html ? <iframe id="animation-preview" key={`${active}-${revision}`} className={styles.frame} title={`${sample.requested_model} 生成的动画`} sandbox="allow-scripts" referrerPolicy="no-referrer" srcDoc={preview(sample.html)} /> : <div className={styles.empty}>{labels[sample.status] || "没有可预览的完整 HTML"}</div>}
        <details className={styles.details}><summary>原始 HTML</summary><pre>{sample.html || "没有完整交付物。原始响应保留在本地数据库。"}</pre></details>
        <details className={styles.details}><summary>测试记录与预览说明</summary><p>提示词原样发送；另附交付要求：{results.instructions}模型输出未经人工修补。HTML 已生成不等于视觉测试通过。</p><p>预览在隔离窗口运行，禁止外部资源与网络请求；下载内容是模型原稿，仅去除外围 Markdown 代码围栏。</p><p>运行时间 {new Date(results.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Taipei" })} UTC+8 · {results.reasoning_effort} · {results.stream ? "流式" : "非流式"} · 输出上限 {results.max_output_tokens} tokens</p><p>运行 ID：{results.run_id}<br/>接口声明模型：{sample.returned_model || "未返回"}<br/>文件 SHA256：{sample.sha256 || "—"}</p></details>
      </div>}
      </dialog>
    </main>
  </div>;
}
