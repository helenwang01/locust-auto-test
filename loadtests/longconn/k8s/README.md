# Kubernetes 运行（singlechat）

本目录用于运行：
- `loadtests/longconn/locustfile_singlechat_online.py`
- 镜像：`locust-auto-test-singlechat:latest`

## 1. 准备 Secret（挂载 config/.env）

```bash
kubectl --context <ctx> -n default create secret generic locust-config-env \
  --from-file=.env=/Users/easemob/Data/PythonProject/locust-auto-test/config/.env \
  --dry-run=client -o yaml | kubectl --context <ctx> apply -f -
```

## 2. 提交 Job

```bash
kubectl --context <ctx> apply -f /Users/easemob/Data/PythonProject/locust-auto-test/loadtests/longconn/k8s/job-singlechat.yaml
```

## 3. 查看执行状态和日志

```bash
kubectl --context <ctx> get job locust-singlechat
kubectl --context <ctx> logs -f job/locust-singlechat
```

## 4. 重跑

```bash
kubectl --context <ctx> delete job locust-singlechat --ignore-not-found
kubectl --context <ctx> apply -f /Users/easemob/Data/PythonProject/locust-auto-test/loadtests/longconn/k8s/job-singlechat.yaml
```

## 双集群执行示例

先查看 context：

```bash
kubectl config get-contexts -o name
```

分别替换 `<ctx-a>`、`<ctx-b>` 执行上面 1~4 步即可。

