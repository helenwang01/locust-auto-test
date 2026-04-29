# 文档导航（统一入口）

本仓库文档统一从这里进入，避免 `agents/`、`docs/`、`skills/` 多头维护。

## 1. 主规范（唯一真相）
- [docs/specs/core.md](./specs/core.md)
  - 定义配置模型、压测脚本约束、指标、日志与安全要求。
  - 代码实现有变更时，先更新这里。

## 2. 规范目录
- [docs/specs/README.md](./specs/README.md)
  - 说明规范文件的职责边界与维护方式。

## 3. 角色规范（执行视角）
- [agents/README.md](../agents/README.md)
  - Coder / Reviewer / Tester 的职责与最小检查项。

## 4. 技能清单（操作视角）
- [skills/README.md](../skills/README.md)
  - 按任务类型给出可复用步骤模板（IM / Pytest / Stress）。

## 文档维护原则
- SSOT：业务与技术规则仅在 `docs/specs/core.md` 定义。
- 去重复：`agents/` 与 `skills/` 不重复写规则，只写“怎么执行”。
- 同步更新：脚本路径、配置字段变化时，`core.md` 与索引必须同一 PR 更新。
