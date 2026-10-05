# 实验室模型监测

独立项目：`D:\Develop\MyApp\lab-model-monitor`。
每天北京时间 15:00、20:00 检测 `gpt-6-astra` 和 `gpt-6.1-sol`。每个时段糖果测试各独立请求三次；动画每模型成功生成一次即停止，失败最多尝试三次。飞书沿用糖果摘要，Sites 自动同步两类结果。Python 后端只使用标准库，网站沿用原来的 Sites 项目和 D1 展示数据。

## 本机使用

双击项目根目录的 `启动控制台.cmd`，即可启动控制台并打开默认浏览器；重复启动会复用现有服务。启动失败时窗口会保留错误信息。脚本也支持传入 `--no-browser` 或 `--port 8766`。

在本项目目录执行：

```powershell
.venv\Scripts\python.exe scripts\start_console.py
.venv\Scripts\python.exe -m lab_model_monitor status
.venv\Scripts\python.exe -m lab_model_monitor run
.venv\Scripts\python.exe -m lab_model_monitor run-all
.venv\Scripts\python.exe -m lab_model_monitor sync
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Status
```

本地控制台默认地址 `http://127.0.0.1:8765/`，启动器会隐藏启动 Python 服务并打开浏览器，再次执行可复用现有服务。可用 `--port 8766` 指定端口、`--no-browser` 只启动服务；前台运行使用 `.venv\Scripts\python.exe -m lab_model_monitor console --port 8765`，Ctrl+C 退出。控制台只在启动后运行，无额外开机或云端任务。

控制台支持检测启停、时间、模型与采样次数、推理与超时、API 端点/协议、提示词/参考答案、API/Site/飞书凭据配置；“保存并应用”会更新本机 Windows 计划任务。密钥输入框永不回填，留空保留，勾选清除才删除本机保存值；环境变量依然优先。配置或计划更新失败会尝试恢复原配置和任务状态，页面显示实际状态。运行中禁止保存配置或启动其他操作。

页面分为概览、检测设置、API 与通知、运行记录。推理参数、题面和通知配置默认折叠；配置页固定显示保存栏，支持 Ctrl+S 和撤销修改。切换页签保留未保存的输入；校验失败会跳到对应页签并展开字段。运行记录可按状态筛选，完整回答按样本展开。

`run-all` 手动触发糖果和动画完整一轮，使用与定时任务相同的采样规则，记录为手动运行，不占用定时时段。

“立即检测”及 `run` 会调用模型；“同步结果”及 `sync` 仅同步既有结果并重试待发送日报。API 连接测试只获取模型列表，不发出题目请求。已导入的历史记录不会补发日报。本地控制台可查看完整回答和各轮原始题面；公开 Sites 网页只负责展示结果。

配置在 `runtime/settings.json`；修改计划时间后重新安装 Windows 任务。`configs/settings.example.json` 为非敏感示例。
模型 API、Site 写凭据、飞书应用与接收目标通过本机 `runtime/credentials.json` 或进程环境变量设置：`OPENAI_API_KEY`、`MONITOR_SITE_TOKEN`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_CHAT_ID`。这些值不得写入源码、命令行参数或日志。手动配置可运行 `.venv\Scripts\python.exe scripts/configure_credentials.py`，输入会隐藏。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Install
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Disable
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Enable
```

计划任务名为 `LabModelMonitor-Daily`，使用本项目 `.venv` 和隐藏启动器。需要此 Windows 用户登录；机器关机或休眠时无法按时检测，恢复后 Windows 可补启动。按北京时间日期、时段、测试类型去重；同一时段重复启动不补测已执行的测试。错过时段后只执行当天最近一个已到时间段，不连跑积压轮次。两项测试并行运行，每种测试内部按顺序请求模型（最多两条模型请求并发）；糖果失败不阻断动画。中断保留已完成样本，不自动补测。本地日志保存在 `runtime/logs/`。启用前必须配置模型及已启用汇报渠道的凭据。暂停后仍可手动检测。暂停或改时间后，如需立即更新云端计划展示，点击“同步结果”。

## 数据和判分

固定题面 `candy-shape-selection-v1`：可凭手感选择形状，不能选择口味，参考答案 21。第一行必须是纯阿拉伯整数。默认使用 `medium`、32768 输出 token 上限、300 秒网络超时，不调用工具，不对失败样本自动重试。通过这道公开题不能认证模型身份。

控制台可配置自定义整数题：变更指令、题面或参考答案后使用 `custom-integer-v1` 合同，按实际指令和题面生成哈希，保存完整题面，不混入旧合同的比较窗口。标准糖果题及已有记录保持不变，可一键恢复标准题。当前判分只支持首行整数，图像/SVG 的视觉判分尚未实现。自定义结果在本地查看并可发飞书，Site 同步自动跳过自定义题；云端糖果看板只投影标准糖果题记录。

- `runtime/monitor.sqlite3` 是原始结果的唯一活动 owner，保留完整回答、用量与执行合同。
- 模型失败、超时、截断与答错分别记录；回答正确率与接口可用率分别统计。
- 比较窗口要求完整合同相同；端点参与合同哈希，但不上传网页。
- Sites D1 的糖果数据只保存最近90天、最多120轮的展示副本，单次回答最多1600字符。
- 飞书只发送摘要。通知或 Site 上传失败不会改写检测判分；恢复同步不会补测模型。
- 导入记录保留原始 ID、时间、合同和全部样本；原量化任务库只保留历史证据。

## 动画测试

`.venv\Scripts\python.exe -m lab_model_monitor animation` 使用同一个客户端、执行锁和 SQLite 记录，每个已配置模型调用一次。固定提示词为“创建一个 HTML，内容是 SVG 绘制一个绵羊驾驶潜艇的 2D 动画。”；单独的交付指令只要求返回完整 HTML。手动命令仍每模型仅一次；定时任务同时执行糖果和动画，动画每模型最多三次尝试，成功即停止，不发送单独的动画飞书日报。

Responses 模式下的动画和整数题均默认使用流式请求，Chat Completions 保留非流式兼容路径。收到文本后每秒最多写入一次 SQLite，完成事件强制保存；运行中可查看已接收字符数。网络等待超时约束单次网络等待，不是整个生成任务的总时限。完成事件到达立即结束读取，连接中断保留已收到文本；停止本地进程不保证上游取消或停止计费。`generated` 只表示收到含 SVG 的完整 HTML，不代表视觉质量通过；接口失败、截断、格式错误独立记录。导出时只去除外围 Markdown 围栏，不修补模型作品。

`.venv\Scripts\python.exe scripts/export_animation.py <run_id>` 从既有数据库导出 HTML 和缩略图到 `runtime/artifacts/<run_id>/`，不会调用模型。网页从云端读取已同步结果，首次打开显示加载占位；加载失败可重试，不再使用源码中的旧静态快照。旧导出参数 `--site` 已移除；需要更新云端时执行独立的 `sync` 命令。定时任务和 `sync` 会从 SQLite 自动同步动画到现有 D1 的独立展示行，无需重新发布网站。动画展示最多最近 12 轮、总计 900 KB；超过 120 KB 的单个 HTML 只展示元数据，原文件仍保存在本地证据中。发布后本机关机仍可浏览和下载已同步动画。

Site 的 `/animations` 提供结果卡片、隔离预览、重播、源码和 HTML 下载。预览禁止外部资源与网络请求；下载保留模型原稿。网站沿用现有访问权限。

## 网站构建

`.openai/hosting.json` 保留现有 Site 身份。当前域名和访问权限沿用现有发布设置。`npm run dev` 本地预览；网站发布使用 Sites 插件流程，既有 D1 迁移保持不变。
后端原始数据、凭据、`.venv`、日志、构建缓存均被 Git 忽略，运行时不会依赖量化项目。

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next
```

Python 3.12+；网站依赖版本由现有 `package-lock.json` 固定。迁移验证见 `docs/migration.md`。

## 目录与生成物

日常入口是根目录的 `启动控制台.cmd`。Python 检测程序与公开网站放在同一个项目内，各自使用独立环境。

| 路径 | 用途 |
| --- | --- |
| `lab_model_monitor/` | Python 检测、调度、存储、通知和本地控制台，含控制台静态资源 |
| `app/`、`lib/`、`public/` | 公开网站页面、展示数据合同和静态资源 |
| `db/`、`drizzle/` | Sites D1 展示副本的接口、表定义与迁移 |
| `build/` | Sites 与 Vite 的构建适配源码；构建产物在 `dist/` |
| `scripts/` | 控制台启动、计划任务、动画导出和网站环境工具 |
| `tests/`、`configs/`、`docs/` | 回归测试、非敏感配置示例和项目文档 |
| `runtime/` | 本机配置、凭据、唯一活动数据库、日志、原始动画文件与 QA/发布生成物，全部忽略提交 |
| `.openai/hosting.json` | 现有站点身份与逻辑存储绑定 |

未使用的 UI 组件库、示例页面、默认装饰图标和静态动画快照已退休。框架要求的配置文件仍放在根目录。

生成物约定：

- 截图、临时验证脚本和展示测试数据统一放在 `runtime/qa/`，不再新增根目录 `work/`。
- 网站发布包使用 `runtime/releases/current-site.tar.gz`；发布前保留上一份为 `previous-site.tar.gz`。此次整理前的旧包已归档至 `runtime/releases/archive/`，不再新增根目录 `outputs/`。
- `node_modules/`、`.venv/` 是开发依赖；`.sites-runtime/`、`.wrangler/`、`.next/`、`.vinext/` 和 `dist/` 是工具状态或可重建产物。TypeScript 增量缓存写入 `.sites-runtime/`。
- `.wrangler/` 可含本地 D1 调试数据；`runtime/` 保存原始证据和运行配置，均不参与普通缓存清理。整理前的截图及小型缓存保存在 `runtime/qa/legacy-work/` 和 `runtime/qa/legacy-cache/`。

## 自动交付动画文件

动画完成后会自动把原始 HTML 导出至 `runtime/artifacts/<run_id>/model-<样本序号>.html`，并生成按 HTML SHA256 命名的 PNG 缩略图；`display.json` 保存展示信息，`artifacts.json` 保存文件处理状态。文件编号对应本轮全部尝试的原始顺序。截图使用本机 Edge（或 Chrome）无头模式、独立临时浏览器配置和禁止外部资源的隔离预览，不依赖量化项目或第三方 Python 包。

手动 `animation`、`run-all` 和定时检测均接入自动导出；`sync` 只从已有证据补齐文件/截图并上传，不重跑模型。缩略图失败单独记录，可通过 `sync` 重试，不改变模型判定。缩略图随 D1 展示结果同步，后续新结果无需重新发布网站。原 HTML 不修改，缩略图为生成作品运行约 3 秒时的画面。
