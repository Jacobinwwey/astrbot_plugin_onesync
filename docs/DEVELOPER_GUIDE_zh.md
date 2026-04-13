# OneSync 开发指南（中文）

> 语言 / Language: [中文](./DEVELOPER_GUIDE_zh.md) | [English](./DEVELOPER_GUIDE_en.md)

| 当前版本 | 最后更新 | 适用对象 | 建议先读 |
| --- | --- | --- | --- |
| `v0.2.2` | `2026-04-13` | 维护者、贡献者、二次开发者 | [README.md](../README.md) |

这份文档给准备改代码的人看。它不重复用户安装步骤，重点是告诉你：代码在哪，状态落在哪，改动后怎么验证，哪些边界现在不能轻易打破。

| 如果你要做什么 | 先看哪里 |
| --- | --- |
| 找主入口和模块职责 | [1. 仓库结构](#1-仓库结构) |
| 先理解状态模型 | [2. 当前状态模型](#2-当前状态模型) |
| 本地跑回归和 WebUI | [4. 本地开发流程](#4-本地开发流程) |
| 增加策略或 Skills 宿主支持 | [5. 关键扩展点](#5-关键扩展点) |
| 判断这轮改动要改哪些文档 | [7. 文档维护边界](#7-文档维护边界) |

| 相关文档 | 用途 |
| --- | --- |
| [README.md](../README.md) | 项目定位、快速开始 |
| [安装与配置指南（中文）](./INSTALL_AND_CONFIG_zh.md) | 用户安装与配置 |
| [操作与同步手册（中文）](./OPERATIONS_AND_SYNC_zh.md) | 发布、同步、维护者操作 |
| [接口参考（中文）](./API_REFERENCE_zh.md) | WebUI API 路由与调用顺序 |

## 1. 仓库结构

核心文件与目录：

- `main.py`
  - 插件主入口。
  - 承担 WebUI 业务编排、调度执行、状态持久化、Skills 控制面动作。
- `webui_server.py`
  - 内嵌 FastAPI 服务。
  - 暴露 `/api/*` 路由，并处理可选登录鉴权。
- `webui/index.html`
  - 单文件前端控制台。
  - 负责运维面板、配置中心、Skills 管理、批量进度与检查器交互。
- `updater_core.py`
  - 软件更新核心执行逻辑。
- `inventory_core.py`
  - 软件/技能发现兼容层。
- `skills_core.py`
  - Skills overview 构建与状态聚合入口。
- `skills_aggregation_core.py`
  - install-unit / collection-group / provenance 聚合逻辑。
- `skills_sources_core.py`
  - source registry 的规范化、合并、持久化辅助逻辑。
- `skills_hosts_core.py`
  - 宿主软件能力与 host row 组装逻辑。
- `tests/`
  - Python 回归测试。
- `docs/`
  - 用户、运维、开发、接口与方案文档。

## 2. 当前状态模型

OneSync 的 Skills 控制面围绕以下状态层工作：

- `manifest`
  - operator intent。
  - 记录 deploy target 选择、source 选择、scope 等声明式信息。
- `lock`
  - resolved runtime state。
  - 记录聚合、freshness、projection、doctor 等结果。
- `registry`
  - source truth。
  - 记录来源、locator、manager、sync 元数据、managed checkout 等。
- `install_atom_registry`
  - 安装原子/证据账本。
- `inventory_snapshot`
  - discovery / compatibility input。
  - 仍然存在，但正在逐步从 authority role 收口为输入与兼容层。

当前重要边界：

- `webui_update_inventory_bindings()` 已切到 manifest-first 投影。
- deploy target mutation 也已复用 manifest-first projection helper。
- `skill_bindings` 仍保留，但已定位为 compatibility projection，而不是长期真相源。

## 3. 本地运行数据

插件运行时会在 AstrBot `plugin_data` 目录下生成状态文件，重点包括：

- `skills/manifest.json`
- `skills/lock.json`
- `skills/registry.json`
- `skills/install_atom_registry.json`
- `skills/audit.log.jsonl`
- `skills/sources/*.json`
- `skills/generated/*.json`
- `state.json`
- `events.jsonl`

开发与排障时，应优先明确是：

- `manifest` 意图错误
- `registry` 元数据错误
- `lock/overview` 聚合错误
- 还是 UI 展示误判

## 4. 本地开发流程

### 4.1 建议前置

- Python 3 环境可用
- AstrBot 开发环境可运行
- 若要验证 WebUI，确保本机可访问 `127.0.0.1:8099`

### 4.2 常用命令

语法检查：

```bash
python3 -m py_compile main.py skills_core.py webui_server.py
```

全量回归：

```bash
pytest -q
```

只跑 Skills 主链路：

```bash
pytest -q tests/test_main_git_checkout_runtime.py tests/test_skills_core.py tests/test_webui_server.py
```

### 4.3 前端修改后建议

- 检查 `webui/index.html` 是否存在明显语法错误。
- 验证 8099 页面能正常打开。
- 至少检查一次：
  - Skills 管理展开/收起
  - Source / Bundle 详情
  - Deploy Target 详情
  - 批量进度区
  - 右侧 Inspector

## 5. 关键扩展点

### 5.1 更新策略

当前主更新策略包括：

- `cargo_path_git`
- `command`
- `system_package`

若扩新策略，优先检查：

- schema 是否允许配置
- `updater_core.py` 是否已有执行能力
- UI 是否需要新增用户输入项

### 5.2 Skills Source / Host

当前 source 相关扩展通常会触及：

- `skills_sources_core.py`
- `skills_core.py`
- `main.py`
- `webui_server.py`
- `webui/index.html`
- 对应测试

当前 host 相关扩展通常会触及：

- `skills_hosts_core.py`
- `skills_core.py`
- AstrBot 专项时还会触及 `skills_astrbot_*`

建议原则：

- 先定义 capability / normalized row。
- 再补 route 与 UI。
- 最后补文档与测试。

### 5.3 WebUI API

新增或修改接口时：

1. 先更新 `webui_server.py`。
2. 再在 `main.py` 补充对应 `webui_*` 业务方法。
3. 更新 [接口参考（中文）](./API_REFERENCE_zh.md) 与 [API Reference (English)](./API_REFERENCE_en.md)。
4. 补 `tests/test_webui_server.py`。

## 6. 当前重点风险

当前主线风险不在“有没有聚合模型”，而在：

- authority boundary 仍未完全从 inventory 切离
- runtime reliability 仍受 manager、checkout、source sync 稳定性影响
- `manual_only` / repo-metadata / git-backed source 的语义需要持续保持一致

开发时应避免：

- 把 UI 临时判断再次做成新的真相源
- 让 `inventory` 重新承担本不该承担的 authority 职责
- 为单一宿主/单一 manager 继续堆不可复用的特判

## 7. 文档维护边界

文档职责建议固定为：

- `README.md`
  - 项目首页、核心特色、安装入口、快速使用、文档导航
- `docs/INSTALL_AND_CONFIG_*`
  - 完整安装与配置说明
- `docs/OPERATIONS_AND_SYNC_*`
  - 发布、同步、运维维护
- `docs/DEVELOPER_GUIDE_*`
  - 开发结构、扩展点、验证流程
- `docs/API_REFERENCE_*`
  - `/api/*` 接口说明
- `docs/plans/*` / `docs/brainstorms/*`
  - 方案、路线图、分析与历史决策

不要再把以下内容塞回 README：

- 大量 API 路由清单
- 维护者发布流程
- 长篇架构复盘
- 历史路线图细节

## 8. 相关文档

- [README.md](../README.md)
- [安装与配置指南（中文）](./INSTALL_AND_CONFIG_zh.md)
- [操作与同步手册（中文）](./OPERATIONS_AND_SYNC_zh.md)
- [接口参考（中文）](./API_REFERENCE_zh.md)
- [开发指南（English）](./DEVELOPER_GUIDE_en.md)
