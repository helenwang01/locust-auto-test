# Skill：IM / send_message

主规范： [docs/specs/core.md](../../docs/specs/core.md)

## 目标
- 在长连接场景中稳定发送单聊消息并上报指标。

## 执行清单
1. 从公共配置对象取 `host/port/mode/use_ssl/path`。
2. 连接并登录（token 获取失败要抛错，不兜底）。
3. 发送消息：失败上报 `send_error`。
4. 回调指标：`send_to_ack`、`end_to_end`。
