# IM 压测与联调

本仓库用于两类工作：
- REST 数据准备与管理（`apis/`）
- Locust 压测（HTTP + IM 长连接）

统一规则见主规范：
- [docs/specs/core.md](./docs/specs/core.md)

统一文档入口：
- [docs/README.md](./docs/README.md)

## 快速开始
1. 配置
- 编辑 `config/config.yaml` 与 `config/.env`（YAML）
- 统一通过 `active_env` 选择环境
- `rest` 与 `locust` 必须是按环境分组结构

2. HTTP 单接口压测（语音转写）
```bash
locust -f loadtests/http/locustfile_speech_transcriptions.py --headless -u 20 -r 5 -t 5m --csv out/speech_transcriptions
```

3. 长连接单聊压测
```bash
locust -f locustfile_singlechat_online.py --headless -u 20 -r 1 -t 7m --csv out/singlechat_online
```

## 目录
- `docs/specs/core.md`：唯一主规范（SSOT）
- `docs/`：文档导航与规范目录说明
- `agents/`：角色职责清单（不重复规则）
- `skills/`：操作模板（不重复规则）
- `loadtests/`：HTTP 与长连接压测脚本
- `apis/`：REST API 封装
- `utils/`：配置与基础能力
- `tests/`：回归与校验
