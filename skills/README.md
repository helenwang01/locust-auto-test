# Skills 导航

技能文档用于“操作步骤模板”，规则来源统一是主规范：
- [docs/specs/core.md](../docs/specs/core.md)

## 分类
- `im/`：IM 连接与收发流程模板
- `pytest/`：测试断言与用例骨架模板
- `stress/`：压测执行与健康检查模板

## 触发建议（与总 Agent 对齐）
1. Locust 脚本开发与改造：优先用 `stress/locust_script.md`
2. 压测前链路验证：优先用 `stress/connection_test.md`
3. 长连接发消息链路：组合使用 `im/build_chat_flow.md` 与 `im/send_message.md`
4. 配置中心测试补齐：组合使用 `pytest/generate_case.md` 与 `pytest/assert_template.md`

## 维护原则
- 技能只写步骤与命令，不重复规则定义。
- 引用脚本路径必须与仓库当前真实路径一致。
