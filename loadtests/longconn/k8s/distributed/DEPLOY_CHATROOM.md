# 聊天室压测分布式部署完整指南

本文档涵盖：镜像构建 → 推送镜像仓库 → K8s 分布式部署（1 master + N worker）→ locust-exporter 接入 Prometheus。

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                         │
│                                                                   │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     │
│  │ locust-master│◄────│ locust-worker│     │ locust-worker│     │
│  │  (1 replica) │     │  (replica 1) │     │  (replica N) │     │
│  │  port: 8089  │     └──────────────┘     └──────────────┘     │
│  │  port: 5557  │                                                │
│  │  port: 5558  │                                                │
│  └──────┬───────┘                                                │
│         │ HTTP API (/stats/requests)                             │
│         ▼                                                        │
│  ┌──────────────────┐         ┌────────────────┐                │
│  │ locust-exporter  │────────►│  Prometheus    │                │
│  │  port: 9646      │ scrape  │                │                │
│  └──────────────────┘         └───────┬────────┘                │
│                                       │                          │
│                                       ▼                          │
│                               ┌────────────────┐                │
│                               │    Grafana      │                │
│                               └────────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

**核心思路**：
1. 将聊天室压测脚本及其依赖打成 Docker 镜像
2. 推送到镜像仓库（Harbor / ACR / ECR / Docker Hub）
3. 在 K8s 中以 master-worker 模式部署，worker 可动态扩缩容
4. locust-exporter 从 master 拉取指标，暴露给 Prometheus
5. 用户通过 Locust Web UI 或 headless 模式发起压测

---

## 第一步：构建镜像

```bash
# 进入项目根目录
cd /path/to/locust-auto-test

# 构建镜像（注意 context 是项目根目录，Dockerfile 指定路径）
docker build \
  -f loadtests/longconn/Dockerfile.chatroom \
  -t locust-chatroom-online:latest \
  .
```

验证镜像：

```bash
docker run --rm locust-chatroom-online:latest
# 应输出 locust 帮助信息
```

---

## 第二步：推送镜像到仓库

```bash
# 设置变量（根据实际仓库修改）
export REGISTRY=your-registry.example.com
export IMAGE_TAG=v1.0.0

# 打 tag
docker tag locust-chatroom-online:latest ${REGISTRY}/locust-chatroom-online:${IMAGE_TAG}

# 登录仓库
docker login ${REGISTRY}

# 推送
docker push ${REGISTRY}/locust-chatroom-online:${IMAGE_TAG}
```

---

## 第三步：准备 K8s 配置

### 3.1 设置环境变量

```bash
export KUBE_CONTEXT=your-kube-context    # kubectl context
export NS=locust                          # 命名空间
export REGISTRY=your-registry.example.com
export IMAGE_TAG=v1.0.0
export IMG=${REGISTRY}/locust-chatroom-online:${IMAGE_TAG}
export ROOT=/path/to/locust-auto-test
```

### 3.2 创建命名空间

```bash
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/namespace.yaml
```

### 3.3 创建 Secret（.env 敏感配置）

`.env` 文件中存放 token/密钥等敏感信息：

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} create secret generic locust-config-env \
  --from-file=.env=${ROOT}/config/.env \
  --dry-run=client -o yaml | kubectl --context ${KUBE_CONTEXT} apply -f -
```

### 3.4 创建 ConfigMap（config.yaml）

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} create configmap locust-config-yaml \
  --from-file=config.yaml=${ROOT}/config/config.yaml \
  --dry-run=client -o yaml | kubectl --context ${KUBE_CONTEXT} apply -f -
```

---

## 第四步：部署分布式 Locust

### 4.1 修改 master-deployment.yaml

将镜像和 entrypoint 改为聊天室场景：

```yaml
# master-deployment.yaml 关键修改点
spec:
  template:
    spec:
      containers:
        - name: master
          image: ${REGISTRY}/locust-chatroom-online:${IMAGE_TAG}  # 替换为实际镜像
          imagePullPolicy: Always
          args:
            - --master
            - --host
            - http://placeholder
            # 聊天室参数（也可在 Web UI 中设置 -u 后生效）
            - --room-count
            - "10"
            - --users-per-room
            - "50"
            - --sender-per-room
            - "1"
            - --room-msg-rps
            - "10"
```

### 4.2 修改 worker-deployment.yaml

```yaml
# worker-deployment.yaml 关键修改点
spec:
  replicas: 5  # worker 数量，根据压测规模调整
  template:
    spec:
      containers:
        - name: worker
          image: ${REGISTRY}/locust-chatroom-online:${IMAGE_TAG}  # 替换为实际镜像
          imagePullPolicy: Always
          args:
            - --worker
            - --master-host
            - locust-master
```

### 4.3 部署

```bash
# 部署 master
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/master-service.yaml
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/master-deployment.yaml

# 部署 worker
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/worker-deployment.yaml
```

### 4.4 验证部署

```bash
# 查看 Pod 状态
kubectl --context ${KUBE_CONTEXT} -n ${NS} get pods -o wide

# 查看 master 日志，确认 worker 连入
kubectl --context ${KUBE_CONTEXT} -n ${NS} logs deploy/locust-master --tail=50

# 期望看到：X workers connected
```

---

## 第五步：部署 locust-exporter（Prometheus 打点）

### 5.1 部署 exporter

```bash
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/locust-exporter-deployment.yaml
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/locust-exporter-service.yaml
```

### 5.2 验证 exporter

```bash
# 查看 Pod
kubectl --context ${KUBE_CONTEXT} -n ${NS} get pods -l app=locust-exporter

# 端口转发测试
kubectl --context ${KUBE_CONTEXT} -n ${NS} port-forward svc/locust-exporter 9646:9646

# 另一个终端验证
curl http://127.0.0.1:9646/metrics
# 应看到 locust_users、locust_requests_total 等指标
```

### 5.3 配置 Prometheus 抓取

**方式 A：静态配置**（手动添加到 prometheus.yml）

```yaml
scrape_configs:
  - job_name: 'locust-chatroom'
    scrape_interval: 5s
    static_configs:
      - targets: ['locust-exporter.locust.svc.cluster.local:9646']
```

**方式 B：ServiceMonitor**（如果使用 Prometheus Operator）

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: locust-exporter
  namespace: locust
  labels:
    release: prometheus  # 匹配你的 Prometheus Operator selector
spec:
  selector:
    matchLabels:
      app: locust-exporter
  endpoints:
    - port: metrics
      interval: 5s
      path: /metrics
```

**方式 C：Pod Annotation 自动发现**

已在 exporter deployment 的 Pod annotations 中设置：
```yaml
prometheus.io/scrape: "true"
prometheus.io/port: "9646"
prometheus.io/path: "/metrics"
```

如果 Prometheus 配置了 `kubernetes_sd_configs` 并过滤 annotation，无需额外配置。

---

## 第六步：发起压测

### 方式 A：Web UI

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} port-forward svc/locust-master 8089:8089
# 浏览器访问 http://127.0.0.1:8089
```

在 Web UI 设置：
- **Number of users (-u)**：必须等于 `room_count × users_per_room`（如 10×50=500）
- **Spawn rate**：建议 10~50（每秒启动用户数）
- **Host**：留空（脚本从 config.yaml 读取）

### 方式 B：Headless 模式

在 master args 中追加：

```yaml
args:
  - --master
  - --headless
  - -u
  - "500"          # room_count * users_per_room
  - -r
  - "20"           # spawn rate
  - -t
  - "10m"          # 压测时长
  - --room-count
  - "10"
  - --users-per-room
  - "50"
  - --sender-per-room
  - "1"
  - --room-msg-rps
  - "10"
```

---

## 第七步：扩缩容

```bash
# 扩容 worker 到 10 个
kubectl --context ${KUBE_CONTEXT} -n ${NS} scale deploy/locust-worker --replicas=10

# 缩容
kubectl --context ${KUBE_CONTEXT} -n ${NS} scale deploy/locust-worker --replicas=3
```

用户会**自动均匀分配**到所有 worker（通过 `global_user_index_for_worker` 交错算法）。

扩容后建议在 Web UI 点 Stop → 重新 Start，让用户在新 worker 上重新分配更均匀。

---

## 关键配置说明

### 分布式用户分配规则

```
总用户数 = room_count × users_per_room
每个 worker 分到 = 总用户数 / worker_count
```

用户通过交错取模分配，保证：
- 每个 worker 负载均衡
- 同一房间的用户分散在不同 worker 上
- 发送者和接收者在 worker 间均匀分布

### config.yaml 中的场景参数

压测参数优先级：**命令行 args > config.yaml 中 scenes 配置 > 默认值**

```yaml
locust:
  scenes:
    - name: chatroom-online-small
      room_count: 10         # 聊天室数量
      users_per_room: 50     # 每房在线人数
      sender_per_room: 1     # 每房发送者
      room_msg_rps: 10       # 每房发送速率(条/秒)
      message: hello         # 消息内容
```

### 资源建议

| 组件 | CPU | Memory | 备注 |
|------|-----|--------|------|
| master | 500m~1000m | 512Mi~1Gi | 主要做协调，压力不大 |
| worker | 1000m~2000m | 1Gi~2Gi | 每个 worker 承载 ~100-500 长连接 |
| exporter | 50m~200m | 64Mi~128Mi | 轻量，仅 HTTP 拉取 |

---

## 清理

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete deploy locust-worker locust-master locust-exporter
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete svc locust-master locust-exporter
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete secret locust-config-env
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete configmap locust-config-yaml
kubectl --context ${KUBE_CONTEXT} delete ns ${NS}
```

---

## 常见问题

### Q: worker 启动后报 "locust -u 必须等于 room_count * users_per_room"
A: `-u` 参数只在 master 上传递，worker 通过 master 分发获取。确保 master args 中的 `-u` 等于 `room_count × users_per_room`。

### Q: 如何修改压测参数而不重新构建镜像？
A: 两种方式：
1. 修改 ConfigMap 中的 config.yaml，然后重启 Pod
2. 在 master deployment 的 args 中通过命令行参数覆盖（`--room-count`、`--users-per-room` 等）

### Q: exporter 显示指标全是 0？
A: 压测未启动时指标为 0 是正常的。在 Web UI 点击 Start 后，等待用户全部上线即可看到数据。

### Q: 如何查看实时 Prometheus 指标？
A: 主要关注以下指标：
- `locust_users`：当前在线虚拟用户数
- `locust_requests_current_rps`：当前 RPS
- `locust_response_times`：响应时间分布
- `locust_failures_total`：失败数
