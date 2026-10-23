# Lab Model Monitor · 实验室模型监测

LLM behavior & API availability monitoring, with a local console and a public dashboard.

一个面向个人实验室的模型行为与接口可用性监测项目。用固定整数题和 SVG 动画生成任务观察特定端点在相同执行条件下的表现，记录原始回答、完成状态、耗时与用量，再将有限的展示副本同步到网页。

[在线糖果看板](https://kevin-lab-model-monitor.kevinjiang1018.chatgpt.site/) · [动画作品与记录](https://kevin-lab-model-monitor.kevinjiang1018.chatgpt.site/animations) · [操作与数据合同](docs/operations.md) · [MIT License](LICENSE)

![公开糖果看板：回答正确率、接口可用率与历史趋势](docs/images/public-dashboard.png)

*公开演示站截图，摄于 2026-10-23；画面中的模型名、分数和时间仅代表当时的实验记录。*

<details>
<summary>查看动画测试：作品与失败记录并列保留</summary>

![公开动画测试页：同轮模型作品与接口失败记录](docs/images/public-animations.png)

*同日公开站截图；生成成功与失败尝试均按原始记录展示。*

</details>

## 项目亮点

- **检测过程可追溯**：SQLite 保存原始回答、运行 ID、时间、题面与执行参数合同；不同合同分开比较。
- **结果语义清楚**：将答错、接口失败、超时与不完整回答分开记录，回答正确率与接口可用率分别统计。
- **本地控制台可操作**：管理模型与计划，查看流式进度、历史样本，暂停后续计划或停止当前手动任务。
- **交付可以重试**：通知、缩略图与网站同步失败后，从既有证据恢复，不重复调用模型。
- **动画可以检查**：保留原始 HTML，提供缩略图、隔离预览、源码与下载；生成成功与视觉质量分开判断。
- **运行依赖少**：Python 端仅使用标准库；Windows 计划任务执行采样，React 网站展示 D1 中的有界副本。

## 观察范围

标准糖果题 `candy-shape-selection-v1` 明确允许凭手感选择形状、不能选择口味，要求首行整数，参考答案为 **21**。题面与判分合同固定；本地自定义整数题采用独立合同，不混入公开糖果看板。

动画任务要求生成“SVG 绘制一个绵羊驾驶潜艇的 2D 动画”的完整 HTML。`generated` 表示收到了符合交付格式的作品，不表示视觉质量通过。

这是个人实验项目。单道公开题和少量样本不能代表模型整体能力，也不能认证后端模型身份；页面中的模型名来自本地配置与 API 返回声明，均不能证明后端身份。本项目不隶属于模型厂商，不构成官方评测或服务承诺。

## 快速开始

本地控制台和自动调度面向 **Windows**，需要 **Python 3.12+**。开发网站另需 **Node.js 22.13+** 和 npm。

```powershell
git clone https://github.com/KevinJiang05/lab-model-monitor.git
cd lab-model-monitor
py -3.12 -m venv .venv
New-Item -ItemType Directory -Path runtime -Force | Out-Null
Copy-Item configs\settings.example.json runtime\settings.json
.venv\Scripts\python.exe scripts\start_console.py
```

也可以双击根目录的 `启动控制台.cmd`。控制台地址为 `http://127.0.0.1:18765/`；Python 无第三方运行依赖。

克隆、安装和打开控制台不会发起模型采样，也不会安装检测计划。先在控制台配置自己的端点、模型名和密钥，再手动检测或启用计划。实际检测会消耗所配置 API 的额度，费用与支持的模型/参数由该端点决定。作者演示部署使用 UTC+8 每日 15:00 / 20:00，这不是克隆后的自动任务。

上面的配置复制步骤用于全新克隆；已有本机配置时通过控制台修改。示例中的计划与飞书均关闭，Site 地址为空。仅在本地检测时保留这两个通知渠道关闭；需要通知或网站同步时再配置自己的渠道与凭据。真实凭据只通过控制台、隐藏输入脚本或环境变量配置，详见[操作说明](docs/operations.md)。

全新克隆首次预览网站时，安装依赖、构建并初始化本地展示表：

```powershell
npm run install:ci
npm run build
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --config dist/server/wrangler.json --local --persist-to .wrangler/state --file drizzle/0000_right_maria_hill.sql
npm run dev
```

打开 `http://127.0.0.1:5173/`。建表命令只用于尚未初始化的本地库，已有本地库时跳过；日常启动只需 `npm run dev`。未初始化时网站会显示结果暂时不可用，建表后没有结果才显示空状态。上述命令使用本地 D1，不连接线上数据库，也不调用模型。

线上演示数据不随仓库分发。部署自己的副本需要独立配置 Sites 与 D1；仓库保留作者现有 `.openai/hosting.json` 身份，克隆不会赋予其管理权限。

## 工作方式

```text
Windows 计划任务 / 本地控制台
          │
          ▼
Python 检测入口 ──► 配置的模型 API
          │
          ▼
本地 SQLite：原始回答、合同与交付状态
          │
          ├──► 原始 HTML 与缩略图
          ├──► 飞书摘要（可选）
          └──► Sites D1：有界展示副本 ──► 公开看板
```

本地数据库是原始证据的唯一活动来源。`run`、`animation`、`run-all` 会调用模型；`sync` 只处理已有结果、补齐缩略图并重试交付。公开网站不持有模型 API 密钥，也不执行采样。

## 开发与验证

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node node_modules/typescript/bin/tsc --noEmit
npm run lint
npm run test:site
npm run build
```

现有回归测试使用临时存储与模拟请求，覆盖题目下界、失败分类、流式中断、合同隔离、调度去重、通知与同步，以及控制台操作。不要用真实模型请求代替测试。

| 路径 | 职责 |
| --- | --- |
| `lab_model_monitor/` | 检测、流式客户端、SQLite、交付与本地控制台 |
| `app/`、`lib/` | React 网站、结果展示与数据合同 |
| `db/`、`drizzle/` | D1 展示副本与迁移 |
| `scripts/`、`build/` | 启动、调度、导出与 Sites 构建适配 |
| `tests/`、`configs/` | 回归测试与不含凭据的配置示例 |
| `runtime/` | 本机配置、凭据、数据库、日志与生成物，全部忽略提交 |

详细行为、命令与回退限制见[操作与数据合同](docs/operations.md)；最初拆分经过见[历史迁移记录](docs/migration.md)。

## 许可与来源

项目原创代码按 [MIT](LICENSE) 许可发布。第三方适配源码、依赖与模型生成作品的来源及边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
