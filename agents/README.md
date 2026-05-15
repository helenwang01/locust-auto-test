# 总 Agent 执行入口

本文件定义“先看哪里、按什么顺序执行、遇到什么任务用哪个 skill”。

## 1. 统一入口顺序
1. 先读主规范：[docs/specs/core.md](../docs/specs/core.md)
2. 再按任务选择 skill：[skills/README.md](../skills/README.md)
3. 执行中若规则与 skill 文案冲突，以 `core.md` 为准

## 2. 本项目关键规则（总览）
1. 配置唯一来源：`config/config.yaml` + `config/.env`
2. 环境切换唯一开关：`active_env`
4. 造数据变量统一在 `data_seed`
5. 压测脚本配置读取必须走公共配置中心（`loadtests/common/config_center.py`）
7. 日志中禁止输出 Token 明文

## 3. 任务到 Skill 映射
1. Locust 压测脚本新增/改造：`skills/stress/locust_script.md`
2. 长连接登录/收发链路联调：`skills/im/build_chat_flow.md` + `skills/im/send_message.md`
3. 压测前连通性验证（token/connect/login/send）：`skills/stress/connection_test.md`
4. 补配置中心测试用例：`skills/pytest/generate_case.md`
5. 增加或修正断言模板：`skills/pytest/assert_template.md`

## 4. 执行要求
1. 任何涉及配置字段调整的改动，必须同步更新：
   - `docs/specs/core.md`
   - `docs/README.md`（若入口路径变化）
   - 对应 `skills/*` 引用路径与步骤
3. 新增功能时，优先复用现有 skill；只有现有 skill 无法覆盖时才新增。
