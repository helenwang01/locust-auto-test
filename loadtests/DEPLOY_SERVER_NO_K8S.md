# 服务器部署指南（非 K8s）

本指南用于把当前项目打包上传到 Linux 服务器并运行 Locust 压测脚本。  
不包含 Kubernetes 部署。

## 1. 本地打包

在本机项目根目录执行：

```bash
cd /Users/easemob/Data/PythonProject/locust-auto-test
tar --exclude-vcs --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' -czf locust-auto-test.tar.gz .
```

## 2. 上传到服务器

```bash
scp locust-auto-test.tar.gz <user>@<server_ip>:/data/
```

## 3. 服务器解压

```bash
ssh <user>@<server_ip>
cd /data
mkdir -p locust-auto-test
tar -xzf locust-auto-test.tar.gz -C locust-auto-test
cd locust-auto-test
```

## 4. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 5. 配置文件准备

需要确认两个文件：

- `config/config.yaml`
- `config/.env`

重点检查：

1. `active_env` 指向要压测的环境（例如 `qa` / `hsb`）。
2. `locust` 下 `mode/host/port/path/use_ssl` 是否和目标环境一致。
3. `data_seed.user_prefix/user_password/room_id` 是否可用。

## 6. 启动前最小自检

```bash
python3 -m py_compile utils/msync_client.py \
  loadtests/longconn/locustfile_singlechat_online.py \
  loadtests/longconn/locustfile_chatroom_online.py
```

## 7. 运行方式 A：前台（推荐先联调）

### 7.1 单聊长连接

```bash
locust -f loadtests/longconn/locustfile_singlechat_online.py
```

### 7.2 聊天室长连接

```bash
locust -f loadtests/longconn/locustfile_chatroom_online.py
```

浏览器访问：

- `http://<server_ip>:8089`

Web UI 里设置：

- Users (`-u`)
- Spawn rate (`-r`)
- Duration (`-t`，无头模式时使用)

说明：

- `-u/-r/-t` 以 Locust 运行参数为主。
- 聊天室脚本的场景参数可用命令行覆盖，也可走 `config.yaml` 默认值。

## 8. 运行方式 B：后台（nohup）

### 8.1 单聊

```bash
nohup locust -f loadtests/longconn/locustfile_singlechat_online.py \
  --headless -u 20 -r 1 -t 10m \
  --csv out/singlechat_online > out/singlechat_online.log 2>&1 &
```

### 8.2 聊天室

```bash
nohup locust -f loadtests/longconn/locustfile_chatroom_online.py \
  --headless -u 1200 -r 100 -t 10m \
  --room-count 10 \
  --users-per-room 120 \
  --sender-per-room 1 \
  --room-msg-rps 18 \
  --chatroom-message "ROOM_CHAT_PAYLOAD" \
  --csv out/chatroom_online > out/chatroom_online.log 2>&1 &
```

查看日志：

```bash
tail -f out/chatroom_online.log
```

## 9. 可选：Docker 单机运行（非 K8s）

使用现有 Dockerfile 构建镜像：

```bash
docker build -f loadtests/longconn/Dockerfile.singlechat -t locust-auto-test:latest .
```

单聊脚本：

```bash
docker run --rm -it -p 8089:8089 \
  -v $(pwd)/config/config.yaml:/app/config/config.yaml \
  -v $(pwd)/config/.env:/app/config/.env \
  locust-auto-test:latest
```

聊天室脚本（覆盖 entrypoint）：

```bash
docker run --rm -it -p 8089:8089 \
  -v $(pwd)/config/config.yaml:/app/config/config.yaml \
  -v $(pwd)/config/.env:/app/config/.env \
  --entrypoint locust \
  locust-auto-test:latest \
  -f loadtests/longconn/locustfile_chatroom_online.py
```

## 10. 常见问题

1. `RuntimeError: login failed for yc1`
- 先确认 `active_env`、`token_url`、`app_key`、`host/port/path/use_ssl`。
- 再确认 `data_seed.user_password` 与压测用户密码一致。

2. `send_error TimeoutError('timed out')`
- 常见于网络抖动或服务端 ACK 回包变慢。
- 先降低 `-u/-r` 做小流量联调，再逐步爬升。

3. Web UI 无法访问
- 检查服务器安全组/防火墙是否放通 `8089`。
- 检查 Locust 是否已启动并监听 `0.0.0.0:8089`。
