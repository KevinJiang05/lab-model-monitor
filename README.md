# 实验室模型监测

独立项目：`D:\Develop\MyApp\lab-model-monitor`。
每天台北时间 16:00 检测 `gpt-6-astra` 和 `gpt-6.1-sol`，各独立请求三次，飞书发送日报，Sites 看板展示结果。Python 后端只使用标准库，网站沿用原来的 Sites 项目和 D1 展示数据。

## 本机使用

在本项目目录执行：

```powershell
.venv\Scripts\python.exe -m lab_model_monitor status
.venv\Scripts\python.exe -m lab_model_monitor run
.venv\Scripts\python.exe -m lab_model_monitor sync
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Status
```

`run` 会付费调用模型；`sync` 仅同步既有结果并重试待发送日报。已导入的历史记录不会补发日报。网页不调用模型，也不修改检测计划。

配置在 `runtime/settings.json`；修改计划时间后重新安装 Windows 任务。`configs/settings.example.json` 为非敏感示例。
模型 API、Site 写凭据、飞书应用与接收目标通过本机 `runtime/credentials.json` 或进程环境变量设置：`OPENAI_API_KEY`、`MONITOR_SITE_TOKEN`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_CHAT_ID`。这些值不得写入源码、命令行参数或日志。手动配置可运行 `.venv\Scripts\python.exe scripts/configure_credentials.py`，输入会隐藏。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Install
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Disable
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\schedule.ps1 -Action Enable
```

计划任务名为 `LabModelMonitor-Daily`，使用本项目 `.venv` 和隐藏启动器。需要此 Windows 用户登录；机器关机或休眠时无法按时检测，恢复后 Windows 可补启动。同一当地日期只执行一次定时检测；中断保留已完成样本，不自动补测。本地日志保存在 `runtime/logs/`。启用前必须配置模型、Site 和飞书凭据。

## 数据和判分

固定题面 `candy-shape-selection-v1`：可凭手感选择形状，不能选择口味，参考答案 21。第一行必须是纯阿拉伯整数。使用 `high`、32768 输出 token 上限、300 秒网络超时，不调用工具，不对失败样本自动重试。通过这道公开题不能认证模型身份。

- `runtime/monitor.sqlite3` 是原始结果的唯一活动 owner，保留完整回答、用量与执行合同。
- 模型失败、超时、截断与答错分别记录；回答正确率与接口可用率分别统计。
- 比较窗口要求完整合同相同；端点参与合同哈希，但不上传网页。
- Sites D1 只保存最近90天、最多120轮的展示副本，单次回答最多1600字符。
- 飞书只发送摘要。通知或 Site 上传失败不会改写检测判分；恢复同步不会补测模型。
- 导入记录保留原始 ID、时间、合同和全部样本；原量化任务库只保留历史证据。

## 网站开发与验证

`.openai/hosting.json` 保留现有 Site 身份。当前域名和访问权限沿用现有发布设置。`npm run dev` 本地预览；网站发布使用 Sites 插件流程，既有 D1 迁移保持不变。
后端原始数据、凭据、`.venv`、日志、构建缓存均被 Git 忽略，运行时不会依赖量化项目。

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next
```

Python 3.12+；网站依赖版本由现有 `package-lock.json` 固定。迁移验证见 `docs/migration.md`。
