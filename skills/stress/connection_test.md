# Skill：Stress / connection_test

主规范： [docs/specs/core.md](../../docs/specs/core.md)

## 目标
- 压测前验证配置与登录链路是否可用。

## 步骤
1. 通过公共配置中心读取 `active_env` 对应的 REST 与长连接配置。
2. 先验证 token 获取，再验证连接/登录。
3. 发送 1 条测试消息，检查 ACK 指标。

## 通过标准
- 连接与登录成功。
- 失败日志包含明确阶段（token/connect/login/send）。
