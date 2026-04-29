# Skill：Pytest / generate_case

主规范： [docs/specs/core.md](../../docs/specs/core.md)

## 目标
- 快速补齐“配置加载 + 公共配置类”回归用例。

## 建议结构
1. 构造临时 `config.yaml`（按 `active_env` + 多环境分组）。
2. 用 `monkeypatch` 让测试目标读取临时配置。
3. 覆盖正常路径与缺失字段异常路径。

## 重点
- 不依赖本地真实 `config/` 内容。
- 断言错误信息包含具体缺失字段路径。
