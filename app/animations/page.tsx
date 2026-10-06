"use client";

import TestHeader from "../test-header";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { animationSnapshotSchema, type AnimationRun } from "@/lib/animation-schema";
import styles from "./page.module.css";

type Sample = AnimationRun["samples"][number];
const prompt = "创建一个 HTML，内容是 SVG 绘制一个绵羊驾驶潜艇的 2D 动画。";
function testedAt(value: string) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}
const thumbnails: Record<string, string> = {
  a8ab7ce7a24b6f5115f70f8ddf702cc147d6457117b0fd0a6f75337edc3112bd: "/animations/astra.png",
  b89dea6c15c119b266f6c6bb363f31ca0e20abd2fa48ce0112270fe9ec43a0c4: "/animations/sol.png",
};
const labels: Record<string, string> = { generated: "HTML 已生成 · 视觉待评价", incomplete: "输出截断", format_error: "未识别到唯一完整 SVG HTML", timeout: "请求超时", api_error: "接口失败" };
const statusLabels: Record<Sample["status"], string> = { generated: "已生成", incomplete: "输出截断", format_error: "格式错误", timeout: "请求超时", api_error: "接口失败" };
function delivered(sample: Sample) {
  return sample.status === "generated" || Boolean(sample.sha256);
}
function description(sample: Sample) {
  return delivered(sample) ? `HTML 已生成 · 视觉待评价${sample.format_note === "extra_text" ? " · 附带说明" : ""}` : labels[sample.status];
}
function requestedTime(value: string) {
  return new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value));
}

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
  const [runs, setRuns] = useState<AnimationRun[]>([]);
  const [syncError, setSyncError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [requestVersion, setRequestVersion] = useState(0);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    const timeout = setTimeout(() => controller.abort(), 20000);
    fetch("/api/snapshot?test=animation", { signal: controller.signal, cache: "no-store" })
      .then(response => { if (!response.ok) throw new Error("load failed"); return response.json(); })
      .then(data => {
        if (!data || typeof data !== "object" || !("success" in data) || data.success !== true) throw new Error("load failed");
        if (!("snapshot" in data)) throw new Error("invalid response");
        const snapshot = data.snapshot === null ? null : animationSnapshotSchema.parse(data.snapshot);
        if (!disposed) {
          setRuns(snapshot ? [...snapshot.runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)) : []);
          setSyncedAt(snapshot?.synced_at || null);
        }
      }).catch(() => { if (!disposed) setSyncError(true); })
      .finally(() => { clearTimeout(timeout); if (!disposed) setLoading(false); });
    return () => { disposed = true; clearTimeout(timeout); controller.abort(); };
  }, [requestVersion]);
  const [active, setActive] = useState<{ run: AnimationRun; sample: Sample } | null>(null);
  const [revision, setRevision] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const sample = active?.sample;
  const activeRun = active?.run;
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
      <div className={`test-heading ${styles.heading}`}><h1>动画测试</h1><p>绵羊驾驶潜艇 · SVG 2D 动画</p><span className={styles.syncMeta}>{!loading && !syncError ? `${runs.length} 轮检测 · 北京时间 UTC+8` : "北京时间 UTC+8"}</span></div>
      <details className={styles.method}><summary>提示词与检测规则 <span>已生成 ≠ 视觉通过</span></summary><div><p>固定提示词：{prompt}</p><p>每天北京时间 15:00、20:00 检测；每模型交付完整 HTML 后停止重试，未交付最多尝试 3 次。展示最近 20 轮检测，含失败记录。附带解释的完整 HTML 仍可预览，单独标注“附带说明”。已生成仅表示代码完整，视觉效果待评价。</p>{syncedAt && <p>结果同步：<time dateTime={syncedAt}>{testedAt(syncedAt)} UTC+8</time></p>}</div></details>
      {loading && <div className={styles.loading} role="status" aria-live="polite"><span>正在加载检测结果…</span>{[0, 1, 2].map(n => <div className={styles.skeleton} key={n} aria-hidden="true"><i /><div /><div /></div>)}</div>}
      {syncError && <div className={styles.loadState} role="alert"><div><strong>检测结果加载失败</strong><p>请重试加载最新记录。</p></div><button onClick={() => { setSyncError(false); setLoading(true); setRequestVersion(n => n + 1); }}>重新加载</button></div>}
      {!loading && !syncError && runs.length === 0 && <p className={styles.noResults} role="status">暂无已同步的动画检测记录。</p>}
      {!loading && !syncError && <div className={styles.runs}>{runs.map((run, runIndex) => <section className={styles.run} key={run.run_id} aria-labelledby={`run-${run.run_id}`}>
        <div className={styles.runHeading}><h2 id={`run-${run.run_id}`}><time dateTime={run.created_at}>{testedAt(run.created_at)}</time>{runIndex === 0 && <span className={styles.latest}>最新一轮</span>}</h2><span>推理 {run.reasoning_effort} · {run.samples.length} 次请求</span></div>
        {run.samples.length > 0 && <div className={styles.grid}>{Array.from(new Set(run.samples.map(s => s.requested_model))).map(model => <div className={styles.modelColumn} key={model}>{run.samples.filter(s => s.requested_model === model).map((s, index) => <article className={`${styles.card} ${!s.html ? styles.unavailable : ""}`} key={`${model}-${s.attempt || index + 1}`}>
          {s.html && <button className={styles.thumbnail} onClick={() => setActive({ run, sample: s })} aria-label={`预览 ${s.requested_model} · ${testedAt(s.requested_at || run.created_at)}`}>
            {(s.thumbnail || thumbnails[s.sha256 || ""]) ? <Image src={s.thumbnail || thumbnails[s.sha256 || ""]} width={1366} height={900} alt={`${s.requested_model} 的绵羊潜艇动画截图`} unoptimized /> : <span>点击播放动画</span>}
            <span className={styles.play} aria-hidden="true">▶</span>
          </button>}
          <div className={styles.cardBody}><div className={styles.cardTitle}><h3>{s.requested_model}</h3><span className={`${styles.status} ${delivered(s) ? styles.generated : styles.failed}`} title={description(s)}>{delivered(s) ? "已生成" : statusLabels[s.status]}</span>{s.format_note === "extra_text" && <span className={`${styles.status} ${styles.failed}`} title="完整 HTML 外附有说明文字，未满足只返回文件的格式要求">附带说明</span>}</div><p className={styles.facts}>{s.elapsed_seconds.toFixed(1)} 秒 <span>·</span> {s.total_tokens === null ? "用量未返回" : `${s.total_tokens.toLocaleString()} tokens`}</p><p className={styles.requestTime}>请求 <time dateTime={s.requested_at || run.created_at} title={`${testedAt(s.requested_at || run.created_at)} UTC+8`}>{requestedTime(s.requested_at || run.created_at)}</time>{s.attempt ? ` · 第 ${s.attempt} 次尝试` : ""}</p><div className={styles.actions}>{s.html ? <><button onClick={() => setActive({ run, sample: s })}>预览 ↗</button><button onClick={() => download(s)}>下载 HTML</button></> : <><span>{delivered(s) ? "HTML 较大，仅本地保存" : s.status === "format_error" ? "未识别到完整 HTML" : "无完整 HTML"}</span><button onClick={() => setActive({ run, sample: s })}>查看记录</button></>}</div></div>
        </article>)}</div>)}</div>}
        {run.samples.length === 0 && <p className={styles.noResults}>本轮暂无已同步的请求记录。</p>}
      </section>)}</div>}
      <dialog ref={dialog} className={styles.dialog} onClose={() => setActive(null)} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      {sample && activeRun && <div className={styles.dialogBody}>
        <div className={styles.dialogHeading}><h2>{sample.requested_model}</h2><button autoFocus onClick={() => dialog.current?.close()} aria-label="关闭预览">关闭 ×</button></div>
        <div className={styles.toolbar}><span>{description(sample)}{sample.http_status ? ` · HTTP ${sample.http_status}` : ""}</span><span>{sample.elapsed_seconds.toFixed(1)} 秒 · {sample.total_tokens === null ? "用量未返回" : `${sample.total_tokens.toLocaleString()} tokens`}</span><div><button disabled={!sample.html} onClick={() => void document.getElementById("animation-preview")?.requestFullscreen().catch(() => {})}>全屏预览</button><button disabled={!sample.html} onClick={() => setRevision(n => n + 1)}>重播</button><button disabled={!sample.html} onClick={() => download(sample)}>下载 HTML</button></div></div>
        {sample.html ? <iframe id="animation-preview" key={`${activeRun.run_id}-${sample.requested_model}-${sample.attempt}-${revision}`} className={styles.frame} title={`${sample.requested_model} 生成的动画`} sandbox="allow-scripts" referrerPolicy="no-referrer" srcDoc={preview(sample.html)} /> : <div className={styles.empty}>{labels[sample.status] || "没有可预览的完整 HTML"}</div>}
        <details className={styles.details}><summary>HTML 代码</summary><pre>{sample.html || "此处没有可展示的完整 HTML。原始响应保留在本地。"}</pre></details>
        <details className={styles.details}><summary>测试记录与预览说明</summary><p>原始提示词：{activeRun.prompt}</p><p>交付要求：{activeRun.instructions}HTML 已生成不等于视觉测试通过。</p>{sample.format_note === "extra_text" && <p>格式提示：模型在完整 HTML 外附加了解释文字，未满足“只返回文件”的要求；HTML 代码可以正常查看。</p>}{sample.status === "format_error" && delivered(sample) && <p>原始判定：格式错误。历史判定保持不变，现已提取其中的完整 HTML 供预览。</p>}<p>预览在隔离窗口运行，禁止外部资源与网络请求；下载保留模型 HTML 代码，仅移除代码围栏及围栏外的说明，不修补代码内容。完整原始响应保留在本地。</p><p>运行时间 {new Date(activeRun.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Taipei" })} UTC+8 · {activeRun.reasoning_effort} · {activeRun.stream ? "流式" : "非流式"} · 输出上限 {activeRun.max_output_tokens} tokens</p><p>请求时间 {new Date(sample.requested_at || activeRun.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Taipei" })} UTC+8{sample.attempt ? ` · 第 ${sample.attempt} 次尝试` : ""}</p><p>运行 ID：{activeRun.run_id}<br/>接口声明模型：{sample.returned_model || "未返回"}<br/>文件 SHA256：{sample.sha256 || "—"}</p></details>
      </div>}
      </dialog>
    </main>
  </div>;
}
