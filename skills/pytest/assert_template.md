# Skill：Pytest / assert_template

主规范： [docs/specs/core.md](../../docs/specs/core.md)

## HTTP 断言模板
- `200 <= status_code < 300`
- 若响应体含 `code` 字段：`code in {0, 200}`

## 压测相关断言模板
- 配置缺失字段时应抛 `RuntimeError`。
- `active_env` 对应分组不存在时应抛明确错误。

## 日志模板
- 输出请求名、状态码、URL、错误类型。
- 不输出 Token 明文。
