# GitHub 公开准备记录

审计日期：2026-10-23（Asia/Taipei）。仓库：`KevinJiang05/lab-model-monitor`。

## 结论与定位

适合公开，作为个人主页上的 LLM 工程实验作品。值得展示的是从请求、流式完成与失败分类，到原始证据留存、本地操作、调度和网页交付的完整链路。已有可访问的演示站和实际结果，便于访客理解项目。

定位为“LLM 行为与接口可用性监测”，避免称为模型鉴定器或通用能力排行榜。固定公开题、少量采样和端点声明都不足以证明模型身份或整体能力。动画的 `generated` 仅表示完成交付格式检查。

## 本次审计

| 范围 | 结果与边界 |
| --- | --- |
| 当前源码与本地可达历史 | 基于 `5b5a894`，覆盖全部本地 refs 可达的 18 个提交、264 个文本 blob 版本，以及本次待提交文件；历史无凭据存储、运行时数据库或日志路径入库 |
| 敏感模式检查 | 未发现明确真实密钥、私钥、带真实凭据的 URL；候选命中核对为 9 处环境变量名、20 处测试占位值、2 处无效 URL 测试样例；不在报告中复制其值 |
| 私有配置 | 未打开真实 `runtime/` 配置、凭据或原始数据库，也未打开 `.env*`、`.dev.vars*` 的内容；相关路径被忽略 |
| 提交署名 | 已核对作者和提交者邮箱，均使用 GitHub/OpenAI 的 `noreply` 域名；未发现真实个人邮箱，无需为此改写历史 |
| 远端状态 | 查询时为 private，仅 `main`、无 tag、无 PR、无 Actions 运行或上传产物；远端 main 与审计时本地 HEAD 一致 |
| Site 身份与访问权限 | `.openai/hosting.json` 保持原值；未部署、修改域名或更改访问权限 |
| 许可 | 用户明确选择 MIT；新增项目许可证与元数据，保留 vendored OpenAI MIT 原文并补第三方说明 |

检查覆盖本地可达对象及上述远端清单，不是对未知格式密钥或 GitHub 全部内部对象的无泄露保证。没有执行历史改写、删除记录或凭据轮换。

## 已准备内容

- README 改为访客可读的项目定位、工程亮点、真实截图、快速安装、数据流与测试入口。
- 完整运行说明保留至 `docs/operations.md`，历史迁移文档明确标注日期和适用范围。
- 配置示例关闭计划与飞书，Site 地址为空；首次安装先复制示例，避免未配置通知阻碍本地使用。本机实际配置未修改。
- 补齐全新网站环境的本地 D1 建表步骤；原来的“直接启动即为空状态”不适用于尚未建表的数据库。
- 加入 MIT、第三方来源说明，以及临时目录、常见私钥导出和 SQLite 文件的忽略规则。
- 未改变题面、判分、模型执行、原始证据或同步实现；未执行模型采样、通知、线上同步或计划任务操作。

## 验证结果

在本项目现有 Windows 开发环境中执行：

| 检查 | 结果 |
| --- | --- |
| `.venv\Scripts\python.exe -m unittest discover -s tests -v` | 70 项通过 |
| `node node_modules/typescript/bin/tsc --noEmit` | 通过 |
| `npm run lint` | 通过 |
| `npm run test:site` | 5 项通过 |
| `npm run build` | 通过；工具输出插件耗时提示和路由静态分类限制，未阻断构建 |
| 示例配置校验、文档本地链接、`git diff --check` | 通过 |
| 首次本地 D1 建表与空表查询 | 在 `runtime/qa/public-d1-smoke-20261023/` 的独立测试库验证；未触及现有 `.wrangler/state` 或远端 D1 |

本次没有重新安装全部依赖，也没有在全新机器上做端到端安装。网站截图来自已经公开的演示站；截图时间与记录时间分别标注，不把静态截图当实时结果。

## 可用于 GitHub 和个人主页的文案

GitHub About description：

> LLM behavior and API availability monitoring with reproducible run evidence, a local console, and a public dashboard.

Website：<https://kevin-lab-model-monitor.kevinjiang1018.chatgpt.site/>

Topics：`llm`、`model-monitoring`、`observability`、`python`、`sqlite`、`react`、`cloudflare-d1`。

个人主页中文介绍：

> **Lab Model Monitor** — 一个使用 Python 标准库构建的 LLM 行为与接口可用性监测项目。通过固定整数题与 SVG 动画任务保留可追溯的运行证据，提供 Windows 本地控制台和公开结果看板，并区分回答错误、接口失败与生成中断。

个人主页英文介绍：

> **Lab Model Monitor** — A Python standard-library LLM monitoring project with reproducible run evidence, a Windows local console, and a public React dashboard. Tracks fixed-prompt behavior and API availability while keeping wrong answers, request failures, and incomplete generations distinct.

## 发布边界

以上远端状态是公开前审计快照。准备阶段未 commit、push 或更改仓库可见性；用户随后于 2026-10-23 明确授权提交、推送并公开现有仓库。发布流程为先提交并推送这批明确列出的文件，检查远端 README、许可证和图片，再将现有仓库切换为 Public，并设置 About、Website 和 Topics。主页置顶可作为后续展示操作。

公开会使源码与保留的历史可见，Actions 历史也属于公开范围；见 [GitHub 可见性说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)。MIT 授权范围以根目录原文为准；公开源码与授予开源许可的区别见 [GitHub 许可说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。若以后发现历史敏感内容，应先按 [GitHub 敏感数据处理说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) 单独处理，而不是仅删除最新文件。
