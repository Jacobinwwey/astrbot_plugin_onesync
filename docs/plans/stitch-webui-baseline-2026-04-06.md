---
date: 2026-04-06
topic: stitch-webui-baseline
status: active
---

# OneSync WebUI Stitch 基线记录（2026-04-06）

## 背景
为 OneSync 的统一资产管理页面（软件 + skills）做前端视觉基线校正。  
本次使用 Stitch MCP 产出桌面与移动稿，再将视觉 token 映射到现有 `webui/index.html`，不改后端 API 语义与交互流程。

## Stitch 资源
- Project: `projects/13653968230990294035`
- Primary desktop screen: `projects/13653968230990294035/screens/3ed0716291bf49c4ac5ff29285fe9a2d`
- Alternate desktop screen: `projects/13653968230990294035/screens/3e9b21c57cd14d2cbacaf6df641118b6`
- Mobile screen: `projects/13653968230990294035/screens/85e1aced3cbf400e8f4bc005343302bd`

本地缓存文件（调试与回放）：
- `/tmp/stitch_primary.html`
- `/tmp/stitch_alt.html`
- `/tmp/stitch_mobile.html`
- `/tmp/stitch_primary.png`
- `/tmp/stitch_alt.png`
- `/tmp/stitch_mobile.png`

## 调整映射（已落地）
已在 `webui/index.html` 做以下映射：

1. 颜色与深浅层级 token 重建  
   - 统一蓝/绿运维基调，避免默认紫色倾向。  
   - 新增 `--panel-strong`、`--chip-bg`、`--shadow-lg`，强化层次感。

2. 主容器与板块边界强化  
   - `container`、`table-wrap`、`inventory-panel`、`debug-panel` 使用更清晰的边框与阴影。  
   - `debug-log-wrap` 使用高对比控制台风格背景提升可读性。

3. 信息密度与扫描效率优化  
   - 指标 chips 改为 `auto-fit` 网格。  
   - hover、focus、状态色映射增强，减少“灰平面”观感。

4. 主题与默认体验  
   - 默认主题改为 `light`。  
   - 主题轮换顺序改为 `light -> slate -> ocean`。

## Stitch 不稳定性观测
`generate_variants` 在当前网络环境下存在断流（`ExceptionGroup` / `RemoteProtocolError`）：

- 现象：请求链路中断，但 `list_screens` / `get_screen` 常可正常读取已生成结果。
- 结论：不要在断流后立即重复触发 destructive 生成，先用 `list_screens` 轮询确认是否已落库。

## 建议的稳定调用顺序
1. `list_screens(projectId)` 记录基线 screen 集合。
2. 发起 `generate_screen_from_text` 或 `generate_variants` 一次。
3. 若连接异常，等待 20-60 秒后轮询 `list_screens`（最多 5-10 分钟）。
4. 发现新 screen 后用 `get_screen(name, projectId, screenId)` 拉取 `screenshot/htmlCode`。
5. 再进行本地样式映射，不要直接以“调用是否报错”判断生成失败。

## 一键执行脚本（已新增）
仓库新增脚本：

- `scripts/stitch_mcp_runner.py`

用途：

- `projects`：列出 Stitch 项目（读操作，带重试）。
- `baseline`：单次 destructive 调用（可选跳过）+ 轮询 `list_screens` + 自动下载 screen 的 html/png。

示例（列项目）：

```bash
python3 scripts/stitch_mcp_runner.py projects --limit 10
```

示例（只轮询，不发 destructive）：

```bash
python3 scripts/stitch_mcp_runner.py baseline \
  --project-id 13653968230990294035 \
  --mode variants \
  --base-screen-id 3ed0716291bf49c4ac5ff29285fe9a2d \
  --prompt "keep structure, improve chip and panel readability" \
  --skip-generate \
  --download all \
  --poll-attempts 3 \
  --poll-interval-s 10
```

示例（发起变体并轮询）：

```bash
python3 scripts/stitch_mcp_runner.py baseline \
  --project-id 13653968230990294035 \
  --mode variants \
  --base-screen-id 3ed0716291bf49c4ac5ff29285fe9a2d \
  --prompt "Create refined operations-console variants with stronger hierarchy and clearer panel boundaries." \
  --variant-count 3 \
  --creative-range EXPLORE \
  --aspects LAYOUT,COLOR_SCHEME \
  --download new \
  --poll-attempts 18 \
  --poll-interval-s 20
```

脚本输出：

- `screens_before.json`
- `screens_after.json`
- `screens_fetched_meta.json`
- `screens/<screen_id>.json|png|html`
- `summary.json`

## 最新实跑记录（Inline Execution）
执行时间（UTC）：
- 开始：`2026-04-06T08:07:25.567191+00:00`
- 结束：`2026-04-06T08:15:55.395251+00:00`

命令：

```bash
python3 scripts/stitch_mcp_runner.py baseline \
  --project-id 13653968230990294035 \
  --mode variants \
  --base-screen-id 3ed0716291bf49c4ac5ff29285fe9a2d \
  --prompt "Refine the software and skills unified management dashboard for Onesync web UI..." \
  --variant-count 3 \
  --creative-range EXPLORE \
  --aspects LAYOUT,COLOR_SCHEME,TEXT_FONT \
  --device-type DESKTOP \
  --model-id GEMINI_3_1_PRO \
  --poll-attempts 18 \
  --poll-interval-s 20 \
  --download all \
  --output-dir /tmp/stitch-run-live-20260406
```

结果摘要：
- `generation_exception = ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`
- `before_count = 3`
- `after_count = 3`
- `new_screen_ids = []`
- 即使生成阶段异常，读路径仍稳定，可成功下载现有 screens 的 `png/html` 到 `/tmp/stitch-run-live-20260406/screens/`

本次结论：
- 继续坚持“单次 destructive + 轮询读取 + 后处理映射”的流程。
- 不以 destructive 调用链路中断直接判定“没有生成”，先看 `list_screens` 的最终落库结果。
