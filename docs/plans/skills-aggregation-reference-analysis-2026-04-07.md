---
date: 2026-04-07
topic: skills-aggregation-reference-analysis
status: active
references:
  - docs/plans/skills-management-reference-comparative-analysis-2026-04-06.md
  - docs/plans/skills-management-next-step-implementation-plan-2026-04-06.md
  - docs/plans/software-skill-unified-management-plan.md
  - docs/brainstorms/software-skill-unified-management-requirements.md
---

# OneSync Skills 聚合管理专项分析

## 背景

上一轮方案已经明确 OneSync 要走 source-first 和 package-first，不回退到 leaf-first。

但当前还有一个更具体、也更容易让 UI 与后端一起失真的问题没有被单独建模：

- 有些 skills 明显应该作为一个 npm 包或一个 source group 统一维护，例如 `ce:*`
- 有些 skills 当前被错误地平铺成多个独立项，例如 `dhh-rails-style`、`dhh-rails-reviewer`
- 有些历史 bundle 又被错误地聚成一个过大的 root pack，例如 `Codex Skill Pack`

所以本轮分析不再讨论“要不要聚合”，而是讨论 OneSync 应该如何区分三种不同层级：

1. 叶子 skill
2. 安装单元
3. 前端展示用聚合组

这三层如果继续混在一起，后端会同时出现两种错误：

- 过度聚合：把共享根目录下不相关的东西误认为一个包
- 聚合不足：把同一个 npm 单包里的多个 skills 误认为需要分别更新和维护

## 当前 OneSync 的具体缺口

结合当前实现，问题已经比较明确：

- `inventory_core.py` 只对少量显式 namespace 规则做 `npx_bundle` 聚合，例如 `ce:*`
- 对其余 `npx` 结果，大多仍回落到 `npx_single`
- `skills_sources_core.py` 虽然已经支持 `registry_package_name`、`member_count`、`management_hint`，但这些字段还不是完整的安装单元模型
- `skills_core.py` 仍然主要围绕 `source` 和 `deploy_target` 运转，没有独立的 `install_unit` 或 `collection_group` 层
- 历史 root bundle 的兼容清理逻辑还在，说明系统已经遇到过“错误聚大包”的真实问题

直接后果是：

- 同一 npm 包内的多个 skills 无法稳定统一更新
- UI 无法同时做到“默认不平铺”和“不过度伪聚合”
- doctor、refresh、deploy 仍然主要针对 source，而不是针对真正的维护边界

## 参考仓库一：skill-flow

### 它真正解决了什么

`skill-flow` 的关键不是“按条管理 skill”，而是“一个 source 保持为一个工作流组”。

从实现上看，它有几个值得 OneSync 正式借鉴的点：

- `packages/core-engine/src/services/source-service.ts`
  - source 是一等对象，注册、更新、快照都围绕 source 展开
- `packages/core-engine/src/services/inventory-service.ts`
  - leaf inventory 是 source 下属结果，不是系统主对象
- `packages/core-engine/src/services/deployment-planner.ts`
  - deploy 先 plan，再决定 create/update/remove/blocked
- `packages/core-engine/src/services/doctor-service.ts`
  - doctor 基于 source、leaf、target 的关系图做诊断，而不是只看某个目录是否存在
- `packages/integration/src/utils/naming.ts`
  - projected name 冲突通过 group identity 解决，不靠拍脑袋重命名

这说明 `skill-flow` 已经把下面这件事做对了：

- group 是真对象
- leaf 是 group 的成员
- target 是 projection output

### 它没有直接解决什么

`skill-flow` 对 OneSync 的价值很高，但它没有直接解决当前这个“npm 聚合管理”问题。

原因是它的 group 更接近“导入 source”：

- 一个 Git repo 是一个 group
- 一个 local root 是一个 group
- 一个 clawhub source 是一个 group

而 OneSync 当前痛点更具体：

- 同一个共享根目录下可能包含多个 npm 包
- 同一个 npm 包又可能包含多个 leaf skills
- 用户要维护的是“单包更新边界”，而不是只知道“这个目录下面有若干 leaf”

换句话说，`skill-flow` 给 OneSync 的启发是“group 应该存在”，但它没有现成回答“group 到底该按 source 还是按 package 来切”。

### 对 OneSync 的批判性借鉴

应该借：

- source 或 group 作为长期资产，而不是扫描快照
- group 下挂 leaf inventory，而不是反过来从 leaf 拼 group
- planner / doctor / projection 的统一语义
- group-aware naming，避免 deploy 端名称冲突

不应照搬：

- 不应把主交互改成 leaf-first
- 不应把“导入 source”直接等同于“用户真正想管理的安装单元”
- 不应在当前阶段复制它的 TUI、桌面端和完整多端壳层

## 参考仓库二：ai-toolbox

### 它真正解决了什么

`ai-toolbox` 的核心不是 group 管理，而是“工具宿主治理中心”。

它在下面这些方面很成熟：

- `tauri/src/coding/tools/detection.rs`
  - built-in + custom tool 的检测、skills path、MCP path 统一建模
- `tauri/src/coding/tools/custom_store.rs`
  - custom tool 是正式数据模型，不是临时配置
- `tauri/src/coding/runtime_location.rs`
  - runtime path、WSL path、宿主路径变化都有明确解析逻辑
- `tauri/src/coding/skills/commands.rs`
  - tool status、central repo、sync、update 都有稳定命令边界
- `web/features/coding/skills/stores/skillsStore.ts`
  - 页面刷新只拉必要状态，不自动触发重扫描

这些能力对 OneSync 很重要，因为 OneSync 也在做“多宿主统一管理”，而且范围比 Claude Code 更广。

### 它没有直接解决什么

`ai-toolbox` 在 skills 管理上，后端真相其实仍然是 flat skill row。

从实现可以看到：

- `tauri/src/coding/skills/types.rs`
  - 核心记录是 `Skill`
- `tauri/src/coding/skills/skill_store.rs`
  - 数据库存的是一条条 managed skill
- `tauri/src/coding/skills/installer.rs`
  - 一个 Git repo 如果包含多个 skills，会抛出 `MULTI_SKILLS`，要求用户提供具体 subpath
- `web/features/coding/skills/pages/SkillsPage.tsx`
  - grouped view 主要是前端按 `source_ref`、`source_type` 临时分组

这套模型适合它自己的场景：

- central repo 中每个 skill 都是独立受管目录
- 各工具目录只是 sync target
- UI 允许拖拽排序、批量勾选、按工具启停

但它不适合 OneSync 当前的聚合诉求，因为它会把“单包中的多个 leaf skills”过早拆散成多条管理记录。

### 对 OneSync 的批判性借鉴

应该借：

- host registry 与 custom host 的建模方式
- runtime path / detect path / skills root 的明确解析
- 宿主路径变化后触发 resync 的事件思想
- 页面只拉必要状态，不在每次打开时做重扫描

不应照搬：

- 不应把 flat managed skill row 作为 OneSync 的主数据模型
- 不应把 grouped view 只做成前端层视觉折叠
- 不应把“多 skill repo 必须选具体 subpath”当成默认工作方式

## 关键结论：两个参考仓库都不能直接给出答案，但它们刚好补齐了 OneSync 缺的两半

更准确地说：

- `skill-flow` 解决了 “group 需要是一等对象”
- `ai-toolbox` 解决了 “tool host 需要是一等对象”

但 OneSync 当前缺的是第三层，也是两个参考仓库都没有直接提供的层：

- `install_unit`

这层才是当前聚合管理真正的维护边界。

## OneSync 应采用的四层模型

### 1. Leaf Skill

最小 deploy 单元。

例子：

- `ce:brainstorm`
- `dhh-rails-style`
- `design-iterator`

职责：

- 参与 target projection
- 承载叶子级 metadata
- 在 detail 中可见，但不应默认成为主面板对象

### 2. Install Unit

真实安装与更新边界。

例子：

- `@every-env/compound-plugin`
- 某个包含多个 reviewer skill 的 npm 包
- 某个 Git repo 的一个 skills 子树

职责：

- 统一 refresh / update / version check
- 统一显示 registry package、包管理器、管理命令
- 统一计算成员 leaf 数量和兼容宿主

这层才应该回答用户那句“这些不是一个 skill，而是一个单包”的问题。

### 3. Collection Group

前端上的高层聚合对象，用于压缩 UI 复杂度。

它可以与 install unit 一对一，也可以把多个 install units 做成一个更可读的视图组，但必须是显式或可解释的，不允许再退回 root-directory 伪聚合。

例子：

- `Compound Engineering`
  - 对应一个 install unit：`@every-env/compound-plugin`
- `DHH Rails`
  - 可能对应一个 install unit
  - 也可能是未来多个 install units 的 curated collection
- `Design Review Pack`
  - 如果未来多个 design reviewer 包存在，可以作为 collection group

### 4. Host Target

部署目标。

例子：

- `codex:global`
- `claude_code:workspace`
- `zeroclaw:global`

职责：

- 解析 target path
- 判断 installed / managed / ready / drift
- 展开 install unit 下的 leafs 做 projection

## 为什么必须区分 Install Unit 和 Collection Group

如果只有 bundle/group 一个概念，系统会再次回到现在的问题：

- 既想表示真实安装边界
- 又想压缩 UI 数量
- 结果只能用一个字段同时承担两件事

然后就会出现两种错误：

- 把共享根目录误当 install unit
- 把语义上应该归一组的同包 leafs 误当独立 source

所以 OneSync 必须明确：

- install unit 是维护边界
- collection group 是展示边界

两者可以重合，但不应该强制重合。

## 建议借鉴与避免清单

### 应明确借鉴

来自 `skill-flow`：

- group/source 一等建模
- leaf inventory 挂在 group 下
- planner / doctor / projection 统一语义
- group-aware naming collision 处理

来自 `ai-toolbox`：

- host/tool registry
- custom host 数据模型
- runtime location 与 skills root 解析
- 变更后事件驱动 resync

### 应明确避免

来自 `skill-flow`：

- 默认 leaf-first 交互
- 把 source 直接等于用户最终管理对象

来自 `ai-toolbox`：

- flat skill row 作为主真相源
- 仅在前端做 grouping，后端仍然逐条 skill 管理
- 遇到 multi-skill source 就强迫用户按 subpath 逐条导入

## 对当前 OneSync 的直接发展判断

下一步最重要的不是继续新增 bundle 规则，而是把聚合从“硬编码命名规则”升级为“有 provenance 的安装单元模型”。

更具体地说，下一阶段应该这样推进：

1. 不再恢复 root-directory synthetic bundle
2. 继续保留现有显式 namespace 规则作为过渡兜底
3. 新增 install-unit 解析层，让 `npx_single` 也能被回填到真实 npm 包
4. 在 install unit 之上再做 collection group，而不是反过来

## 结论

对当前问题，两个参考仓库给 OneSync 的正确借鉴方式不是“选一个抄”，而是：

- 用 `skill-flow` 的思路解决“聚合组必须有真实状态”
- 用 `ai-toolbox` 的思路解决“宿主软件必须有正式注册表”
- 由 OneSync 自己补上“install unit”这一层，作为 npm 单包、git 子树和 local source 的统一维护边界

只有这样，OneSync 才能同时解决下面三件事：

- `Codex Skill Pack` 这种历史大包不能再伪聚合
- `dhh-rails-*`、`design-*` 这类同包成员不再被错误平铺
- 用户在前端看到的是少量可维护对象，而不是一屏叶子名称
