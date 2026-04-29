# Skill：IM / build_chat_flow

主规范： [docs/specs/core.md](../../docs/specs/core.md)

## 目标
- 建立“连接 -> 登录 -> 收发 -> 指标”最小闭环。

## 步骤
1. 用 `utils/config.py` + 公共配置类读取连接参数（禁止脚本内硬编码环境）。
2. 建立连接并登录。
3. 发送消息并监听 ACK / 送达回调。
4. 输出关键指标并安全断开连接。

## 结果要求
- 失败日志可定位（用户、阶段、异常类型）。
- 日志不泄露 Token。
