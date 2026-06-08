# Locust 分布式压测实操记录（1 个 Kubernetes 集群）

目标：
- 使用镜像 `locust-auto-test-singlechat:latest`
- 在 1 个 Kubernetes 集群中部署 `1 master + N worker`
- 用 Web UI 发起压测并验证 worker 横向扩展

下面命令都可以直接复制执行；只需要改第 0 步变量。

## 0. 设置变量

```bash
# 可选:
# - docker-desktop（本次实测使用）
# - kind-<cluster-name>（如果你使用 kind）
export KUBE_CONTEXT=docker-desktop
export NS=locust
export IMG=locust-auto-test-singlechat:latest
export ROOT=/Users/easemob/Data/PythonProject/locust-auto-test
```

## 1. 确认集群与镜像

```bash
kubectl config get-contexts -o name
docker image ls | grep locust-auto-test-singlechat
```

## 2. 将本地镜像导入集群（仅 kind 需要）

```bash
# docker-desktop 可跳过该步骤
kind load docker-image ${IMG} --name <your-kind-cluster-name>
```

## 3. 创建命名空间

```bash
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/namespace.yaml
```

## 4. 创建 Secret（挂载 config/.env）

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} create secret generic locust-config-env \
  --from-file=.env=${ROOT}/config/.env \
  --dry-run=client -o yaml | kubectl --context ${KUBE_CONTEXT} apply -f -
```

## 5. 创建 ConfigMap（挂载 config.yaml）

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} create configmap locust-config-yaml \
  --from-file=config.yaml=${ROOT}/config/config.yaml \
  --dry-run=client -o yaml | kubectl --context ${KUBE_CONTEXT} apply -f -
```

## 6. 部署 master Service + Deployment

```bash
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/master-service.yaml
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/master-deployment.yaml
```

## 7. 部署 worker Deployment（默认 2 副本）

```bash
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/worker-deployment.yaml
```

## 7.1 部署 locust-exporter（Prometheus 打点）

locust-exporter 从 Locust master 的 `/stats/requests` API 拉取数据，暴露为 Prometheus 标准 `/metrics` 端点（端口 9646）。

```bash
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/locust-exporter-deployment.yaml
kubectl --context ${KUBE_CONTEXT} apply -f ${ROOT}/loadtests/longconn/k8s/distributed/locust-exporter-service.yaml
```

验证 exporter 正常运行：

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} get pods -l app=locust-exporter
# 端口转发查看 metrics
kubectl --context ${KUBE_CONTEXT} -n ${NS} port-forward svc/locust-exporter 9646:9646
# 浏览器或 curl 访问 http://127.0.0.1:9646/metrics
```

### Prometheus 配置

在 Prometheus 的 `scrape_configs` 中添加：

```yaml
scrape_configs:
  - job_name: 'locust'
    scrape_interval: 5s
    static_configs:
      - targets: ['locust-exporter.locust.svc.cluster.local:9646']
```

如果集群中已部署 Prometheus Operator 并启用了 Pod annotation 自动发现（`prometheus.io/scrape: "true"`），则无需额外配置，Prometheus 会自动抓取。

### 暴露的主要指标

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `locust_requests_total` | Counter | 总请求数（按 name/method 分） |
| `locust_failures_total` | Counter | 失败请求数 |
| `locust_response_times` | Histogram | 响应时间分布 |
| `locust_users` | Gauge | 当前在线虚拟用户数 |
| `locust_requests_current_rps` | Gauge | 当前 RPS |
| `locust_requests_current_fail_per_sec` | Gauge | 当前失败速率 |

## 8. 检查 Pod 启动

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} get pods -o wide
kubectl --context ${KUBE_CONTEXT} -n ${NS} get svc
```

若初始状态是 `ContainerCreating`，先等待 10~60 秒再看。

## 9. 看 worker 是否已连上 master

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} logs deploy/locust-master --tail=200
kubectl --context ${KUBE_CONTEXT} -n ${NS} logs deploy/locust-worker --tail=200
```

成功标志：
- `reported as ready`
- `N workers connected`

## 10. 打开 Locust Web UI

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} port-forward svc/locust-master 8089:8089
```

浏览器打开：
- http://127.0.0.1:8089

在页面设置：
- Number of users：20
- Spawn rate：1
- Host：可留空（脚本自身走配置）

点击 Start swarming。

## 11. 验证压测是否正常

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} logs deploy/locust-master --tail=200 -f
```

看是否持续输出统计数据，且无大量 connect_error。

## 12. 验证横向扩展

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} scale deploy/locust-worker --replicas=4
kubectl --context ${KUBE_CONTEXT} -n ${NS} get pods -l app=locust-worker
```

观察 master 日志，确认新增 worker 加入：
- `4 workers connected`
- `Sending spawn jobs ... to 4 ready workers`

## 13. 故障演练（可选）

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete pod -l app=locust-worker --grace-period=0 --force
```

看 worker 是否自动重建，master 是否继续工作。

## 14. 清理

```bash
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete deploy locust-worker locust-master locust-exporter
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete svc locust-master locust-exporter
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete secret locust-config-env
kubectl --context ${KUBE_CONTEXT} -n ${NS} delete configmap locust-config-yaml
kubectl --context ${KUBE_CONTEXT} delete ns ${NS}
```

## 本次验证结论

- master 启动正常，Web UI 正常。
- worker 成功接入，初始 2 worker 正常发压。
- 扩容到 4 worker 后，master 识别到 `4 workers connected`，并将任务分发到 4 worker。
- 说明该镜像在 Kubernetes 分布式模式下可用，Locust 与 K8s 兼容性通过。

## 遇到的问题与处理

1. `zsh: command not found: kind`
- 原因：本机未安装 kind。
- 处理：`brew install kind`。
- 备注：若使用 `docker-desktop` context，可不依赖 kind。

2. `No kind clusters found`
- 原因：没有创建独立 kind 集群。
- 处理：
  - 使用 Docker Desktop 自带 K8s：直接用 `docker-desktop` context。
  - 或创建 kind：`kind create cluster --name <name>`。

3. Pod 初始 `ContainerCreating`
- 原因：镜像拉取/卷挂载初始化中，属正常过渡状态。
- 处理：等待后再 `kubectl get pods` 复查。

4. 添加 worker 后是否必须重启压测
- 结论：不必须。
- 建议：为让新 worker 更快、均匀接管，可在 Web UI 里 `Stop` 后再 `Start` 一轮。

5. 日志“很安静”是否异常
- 结论：通常正常。
- 解释：脚本运行稳定时不会持续打印大量日志，重点看 master 的分发与 worker 连接状态即可。
