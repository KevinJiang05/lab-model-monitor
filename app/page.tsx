"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, ArrowUpRight, ChevronDown, Clock3, RefreshCw } from "lucide-react";
import { z } from "zod";
import TestHeader from "./test-header";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { complete, day, formatTime, freshness, snapshotSchema, statusText, summarize, type Snapshot } from "@/lib/monitor";

const colors = ["#bd7316", "#13857a"];
const label = (m: string) => m === "gpt-6-astra" ? "GPT-6 Astra" : m === "gpt-6.1-sol" ? "GPT-6.1 Sol" : m;
const percent = (n: number | null) => n === null ? "—" : `${Number(n.toFixed(1))}%`;
export default function Home() {
  const [data, setData] = useState<Snapshot | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [days, setDays] = useState(7), [metric, setMetric] = useState<"accuracy" | "availability">("accuracy"), [now, setNow] = useState(() => new Date());
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/snapshot", { cache: "no-store" });
      if (!response.ok) throw new Error("unavailable");
      const result = z.object({ success: z.boolean(), snapshot: z.unknown() }).parse(await response.json());
      if (result.success !== true) throw new Error("unavailable");
      setData(result.snapshot === null ? null : snapshotSchema.parse(result.snapshot)); setNow(new Date());
    } catch { setError("暂时无法读取监测结果，请稍后刷新。"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { const start = setTimeout(() => void load(),0); const timer = setInterval(() => setNow(new Date()),60000); return () => { clearTimeout(start); clearInterval(timer); }; }, [load]);
  const latest = data?.runs[0], models = data?.schedule.models || ["gpt-6-astra","gpt-6.1-sol"];
  const state = data ? freshness(data, now) : "empty";
  const cutoff = day(new Date(now.getTime()-(days-1)*86400000).toISOString());
  const runs = useMemo(() => (data?.runs || []).filter(r => day(r.created_at) >= cutoff), [data,cutoff]);
  const comparable = runs.filter(r => r.contract_id === latest?.contract_id);
  const chart = Array.from({ length: days }, (_,i) => {
    const date = day(new Date(now.getTime()-(days-1-i)*86400000).toISOString());
    const p: Record<string, string | number | null> = { date: date.slice(5).replace("-","/") };
    models.forEach(m => { p[m] = summarize(comparable.filter(r => day(r.created_at) === date).flatMap(r => r.samples).filter(s => s.requested_model === m))[metric]; }); return p;
  });
  return <div className="monitor-page">
    <div className="monitor-workspace"><TestHeader active="candy" />
      <main><div className="heading test-heading"><div><h1>糖果测试</h1><p>回答正确率、接口状态与历史记录</p></div><button className="refresh" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "spin" : ""}/>刷新结果</button></div>
        <div className="statusline"><span className={`signal ${state}`}><span className="dot"/>{state === "fresh" ? "已收到最近测试" : state === "stale" ? "等待更新 · 数据可能过期" : state === "paused" ? "定时检测已暂停" : "等待首次同步"}</span><span><Clock3 size={15}/>{data?.schedule.enabled === false ? "检测已暂停" : `每日 ${data?.schedule.daily_time || "16:00"}`} · UTC+8</span><span>最近测试 {formatTime(latest?.ended_at || latest?.created_at || null)}</span></div>
        {error && <div className="notice" role="alert"><AlertTriangle size={18}/>{error}{data && " 当前显示上次读取的数据。"}</div>}
        {!data && <div className="empty" role="status"><Activity size={28}/><h2>{loading ? "正在读取监测结果" : error ? "结果暂时不可用" : "尚未收到检测结果"}</h2><p>{loading ? "稍等片刻。" : "同步成功后，这里会展示真实的模型回答与历史记录。"}</p></div>}
        {data && <>
          <div className="cards">{models.map((m,i) => {
            const samples = (latest?.samples || []).filter(s => s.requested_model === m), s = summarize(samples), failed = samples.length-s.completed;
            return <section className="model-card" key={m} style={{ "--model-color": colors[i%2] } as React.CSSProperties}>
              <div className="card-top"><span className="model-mark">{i === 0 ? "A" : "S"}</span><div><h2>{label(m)}</h2><span className="model-id">{m}</span></div><span className={`badge ${failed ? "warn" : samples.length && s.passed === samples.length ? "ok" : "neutral"}`}>{failed ? `${failed} 次接口异常` : samples.length && s.passed === samples.length ? "本轮全部通过" : samples.length ? "存在未通过回答" : "暂无样本"}</span></div>
              <div className="score"><span>本轮回答正确率</span><strong>{percent(s.accuracy)}</strong><span>{s.passed} / {s.completed} 个完成回答通过</span></div>
              <div className="card-facts"><div><span>接口可用率</span><strong>{percent(s.availability)}<small>{s.completed}/{s.attempts} 次请求</small></strong></div><div><span>平均请求耗时</span><strong>{s.latency === null ? "—" : s.latency.toFixed(1)}<small>{s.latency === null ? "" : "秒"}</small></strong></div></div>
              <div className="sample-strip"><span>本轮请求</span><div>{samples.map(x => <span key={x.attempt} className={`sample ${x.status}`} title={`第 ${x.attempt} 次：${statusText[x.status]}${x.http_status ? ` · HTTP ${x.http_status}` : ""}`}>{x.attempt}</span>)}</div><span>{samples.length} 个样本</span></div>
            </section>;
          })}</div>
          <div className="definition">回答正确率仅统计已完成回答，格式错误计为未通过；接口失败、超时和截断单独计入可用率。</div>
          <section className="panel"><div className="section-top"><div><div className="eyebrow">HISTORY</div><h2>每日表现趋势</h2></div><div className="segmented" aria-label="历史时间范围">{[7,30].map(n => <button key={n} onClick={() => setDays(n)} aria-pressed={days === n}>{n} 天</button>)}</div></div>
            <div className="chart-controls"><div className="metric-tabs">{(["accuracy","availability"] as const).map(m => <button key={m} onClick={() => setMetric(m)} aria-pressed={metric === m}>{m === "accuracy" ? "回答正确率" : "接口可用率"}</button>)}</div><div className="legend">{models.map((m,i) => <span key={m}><i style={{ background: colors[i%2] }}/>{label(m)}</span>)}</div></div>
            <div className="chart" role="img" aria-label={`${days} 天趋势，无记录的日期留空`}><ResponsiveContainer width="100%" height="100%"><LineChart data={chart} margin={{ top:15,right:18,left:-12,bottom:0 }}><CartesianGrid vertical={false} stroke="#e8ecef"/><XAxis dataKey="date" tick={{ fontSize:12,fill:"#72808c" }} axisLine={false} tickLine={false} minTickGap={30}/><YAxis domain={[0,100]} ticks={[0,25,50,75,100]} tickFormatter={n => `${n}%`} tick={{ fontSize:12,fill:"#72808c" }} axisLine={false} tickLine={false}/><Tooltip formatter={v => percent(Number(v))} contentStyle={{ borderRadius:10,border:"1px solid #e1e7eb",fontSize:14 }}/>{models.map((m,i) => <Line key={m} name={label(m)} dataKey={m} stroke={colors[i%2]} strokeWidth={2.5} dot={{ r:4,strokeWidth:2,fill:"#fff" }} activeDot={{ r:6 }} connectNulls={false} isAnimationActive={false}/>)}</LineChart></ResponsiveContainer></div>
            <div className="window-stats">{models.map((m,i) => { const s = summarize(comparable.flatMap(r => r.samples).filter(x => x.requested_model === m)); return <div key={m}><i style={{ background:colors[i%2] }}/><span>{label(m)}</span><strong>{s.passed}/{s.completed}</strong><span>回答通过</span><strong>{s.completed}/{s.attempts}</strong><span>接口完成</span></div>; })}</div>
            <p className="chart-note">按 UTC+8 日期汇总，只比较与最近一轮相同的题目、端点及参数。没有检测记录的日期留空。</p>
          </section>
          <section className="panel history"><div className="section-top"><div><div className="eyebrow">RUN LOG</div><h2>检测记录 <span className="count">{runs.length}</span></h2></div><span className="secondary">最近 {days} 天</span></div>
            {!runs.length && <p className="history-empty">所选时间范围内没有检测记录。</p>}
            {runs.map(r => <details className="run" key={r.run_id}><summary><span className="run-date">{formatTime(r.created_at)}<small>UTC+8</small></span><div className="run-models">{models.map(m => { const s = summarize(r.samples.filter(x => x.requested_model === m)); return <span key={m}><b>{label(m)}</b><span>{s.passed}/{s.completed} 回答通过 · {s.completed}/{s.attempts} 接口完成</span></span>; })}</div><span className={`badge ${r.status === "success" ? "ok" : "warn"}`}>{r.status === "success" ? "全部通过" : r.status === "cancelled" ? "已取消" : "有异常"}</span><ChevronDown size={18} className="chevron"/></summary>
              <div className="run-body"><div className="run-meta">测试 ID：{r.run_id} · {r.contract.reasoning_effort} · {r.contract.api_mode}{r.contract_id !== latest?.contract_id && <strong> · 参数版本不同，不计入当前趋势</strong>}</div>{!r.samples.length && <p>任务未产生可评分样本。</p>}{r.samples.map((s,i) => <div className="answer" key={i}><div className="answer-heading"><strong>{label(s.requested_model)} <span>第 {s.attempt} 次</span></strong><span className={`answer-status ${s.status}`}>{statusText[s.status]}{s.http_status ? ` · HTTP ${s.http_status}` : ""}</span><span>{s.elapsed_seconds.toFixed(1)} 秒</span><span>{s.total_tokens === null ? "用量未返回" : `${s.total_tokens.toLocaleString()} tokens`}</span></div><div className="answer-meta">首行答案：{s.answer ?? "—"} · 接口声明模型：{s.returned_model || "未返回"}</div><pre>{s.response_text || (complete.has(s.status) ? "返回了空文本。" : "本次没有完整回答。")}</pre>{s.response_truncated && <p className="secondary">页面展示前 1600 字符；完整记录保留在本地任务库。</p>}</div>)}</div>
            </details>)}
          </section>
          <details className="panel method"><summary><div><div className="eyebrow">METHODOLOGY</div><h2>测试方法与固定参数</h2></div><ChevronDown size={18}/></summary><div className="method-body"><p>单道题监测适合观察波动，不用于认证模型身份或衡量完整推理能力。接口声明的模型名不能证明后端模型身份。</p><div className="parameters"><span>推理强度 <b>{latest?.contract.reasoning_effort || "—"}</b></span><span>每模型 <b>{data.schedule.attempts_per_model} 次</b></span><span>输出上限 <b>{latest?.contract.max_output_tokens.toLocaleString() || "—"} tokens</b></span><span>网络等待超时 <b>{latest?.contract.timeout_seconds || "—"} 秒</b></span><span>响应方式 <b>{latest?.contract.stream ? "流式" : "非流式"}</b></span><span>联网 <b>{latest?.contract.web_search ? "开启" : "关闭"}</b></span><span>失败自动重试 <b>{latest?.contract.stream_failure_retry ? "开启" : "关闭"}</b></span></div><p>允许凭手感选择糖果形状。参考答案为 21：预先选择 9 个圆形与 12 个五角星形；固定盲抽属于不同题目。</p><pre>{data.method.instructions}{"\n\n"}{data.method.prompt}</pre></div></details>
          <footer><span>最近同步 {formatTime(data.synced_at)} · 历史保留 {data.retention_days} 天{data.history_limited ? "，当前显示最近 120 轮" : ""}</span><span>Lab model monitor <ArrowUpRight size={14}/></span></footer>
        </>}
      </main>
    </div>
  </div>;
}
