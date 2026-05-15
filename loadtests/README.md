# Loadtests

压测脚本按类型拆分：

- `loadtests/http/`：单个 HTTP API 压测
- `loadtests/longconn/`：长连接（IM msync）压测
- 服务器部署（非 K8s）：`loadtests/DEPLOY_SERVER_NO_K8S.md`

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

配置说明（当前结构）：
- 公共参数（不分环境）在 `locust` 下平铺，例如：
  - `client_resource`、`debug`、`console_log`
  - `message`、`singlechat_*`
  - `speech_username`、`speech_file_id`
- 环境差异参数在 `locust.<active_env>`：
  - `mode`、`host`、`port`、`path`、`use_ssl`

## 长连接聊天室压测

脚本：`loadtests/longconn/locustfile_chatroom_online.py`

示例：

```bash
# 完全用命令行覆盖场景参数
locust -f loadtests/longconn/locustfile_chatroom_online.py --headless \
  -u 1200 -r 100 -t 10m \
  --room-count 10 \
  --users-per-room 120 \
  --sender-per-room 1 \
  --room-msg-rps 18 \
  --chatroom-message live-custom-message \
  --csv out/chatroom_online
```

```bash
# 仅使用 config/config.yaml 的场景默认值（chatroom-online-small）
# 只需要传 locust 核心运行参数 -u/-r/-t
locust -f loadtests/longconn/locustfile_chatroom_online.py --headless \
  -u 1200 -r 100 -t 10m \
  --csv out/chatroom_online
```

配置说明：
- 聊天室场景读取 `locust.scenes` 中 `name: jingqi-chatroom`
- `-u/-r/-t` 以 Locust 运行参数为准（命令行或 Web UI）
- 其余聊天室参数支持“命令行扩展参数覆盖 + config 场景默认值”：
  - `room_count` / `users_per_room` / `sender_per_room` / `room_msg_rps`
- 聊天室 ID 由 `data_seed.room_id` + `room_count` 自动生成
  - 例如 `room_id=room_1`、`room_count=20` -> `room_1..room_20`
