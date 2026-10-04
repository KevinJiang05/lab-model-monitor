/* eslint-disable @next/next/no-html-link-for-pages -- Test navigation deliberately uses full document requests, independent of client hydration. */
export default function TestHeader({ active }: { active: "candy" | "animation" }) {
  return <header className="test-header">
    <a className="test-brand" href="/">实验室模型监测</a>
    <nav aria-label="测试类型">
      <a href="/" aria-current={active === "candy" ? "page" : undefined}>糖果测试</a>
      <a href="/animations" aria-current={active === "animation" ? "page" : undefined}>动画测试</a>
    </nav>
    <span className="test-access">公开看板</span>
  </header>;
}
