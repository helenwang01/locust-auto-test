# Skill：Stress / locust_script

主规范： [docs/specs/core.md](../../docs/specs/core.md)

## 目标
- 编写或维护 Locust 压测脚本时，保证配置来源统一、指标一致。

## 当前脚本路径
- HTTP：`loadtests/http/locustfile_speech_transcriptions.py`
- 长连接：`locustfile_singlechat_online.py`（包装入口）

## 最小要求
1. 所有配置由公共配置类读取。
2. 缺失关键字段直接报错，不提供默认值。
3. 关键指标统一上报并可在 CSV 中查看。
