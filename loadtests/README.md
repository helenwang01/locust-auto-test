# Loadtests

压测脚本按类型拆分：

- `loadtests/http/`：单个 HTTP API 压测
- `loadtests/longconn/`：长连接（IM msync）压测

## HTTP 单接口压测（语音转写）

脚本：`loadtests/http/locustfile_speech_transcriptions.py`

示例：

```bash
locust -f loadtests/http/locustfile_speech_transcriptions.py --headless -u 20 -r 5 -t 5m --csv out/speech_transcriptions
```

一键脚本（推荐）：

```bash
scripts/run_speech_pressure.sh 20 5 5m
```

指定总 QPS（可选）：

```bash
scripts/run_speech_pressure.sh 1000 20 15m 180 0
```

也可直接在 locust 命令里传：

```bash
locust -f loadtests/http/locustfile_speech_transcriptions.py --headless -u 1000 -r 20 -t 15m --target-qps 180 --shape-hold-seconds 0 --csv out/speech_transcriptions
```

说明：

- 用户数与爬升由 `-u/-r` 控制（Load Shape 使用 common options）
- 用户行为模型会按 `target_qps / 当前在线用户数` 动态控速
- `shape-hold-seconds` 为 0 表示由 `-t` 控制结束时间

说明：

- 默认读取 `config/config.yaml` + `config/.env`（按 `active_env` 选择环境）
- 请求路径：`/api/sdk/v1/{org}/{app}/speech/transcriptions`
- 默认参数：
  - `username=tst`
  - `fileId=68bd8d90-3c96-11f1-9393-e527a72f81ce`
- 可通过 `config/config.yaml -> locust` 覆盖：
  - `speech_username`
  - `speech_file_id`

## 长连接单聊压测

脚本：`loadtests/longconn/locustfile_singlechat_online.py`

示例：

```bash
locust -f loadtests/longconn/locustfile_singlechat_online.py --headless -u 20 -r 1 -t 7m --csv out/singlechat_online
```
