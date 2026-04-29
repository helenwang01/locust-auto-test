# Core Spec（唯一规范）

版本：v2.0  日期：2026-04-22

## 1. 目标
- 统一 REST 与 Locust 压测的配置来源、执行方式和可观测标准。
- 统一通过 `active_env` 选择环境，避免不同脚本使用不同环境。

## 2. 配置规范（SSOT）

### 2.1 配置文件
- 非敏感配置：`config/config.yaml`
- 敏感配置：`config/.env`（YAML）

### 2.2 读取方式
- 统一通过 `utils/config.py` 的 `load_yaml_config()` 读取。
- 读取顺序：`config.yaml` -> `.env` 覆盖同路径键。
- 禁止在业务代码中手工拼读取逻辑。

### 2.3 环境选择
- 顶层 `active_env` 为唯一环境开关。
- `rest` 与 `locust` 必须按环境分组（如 `qa/hsb/ebs`）。
- 不再支持平铺单环境结构。

### 2.4 默认值策略
- 关键压测参数缺失必须直接报错。
- 不允许“静默默认值”掩盖配置问题。

## 3. 公共配置中心

### 3.1 统一入口
- `loadtests/common/config_center.py`

### 3.2 作用
- REST 压测读取 `rest.<active_env>` + `locust` 公共字段。
- 长连接压测读取 `locust.<active_env>` 连接字段 + `locust` 公共字段。
- 向上层脚本提供结构化配置对象。

### 3.3 约束
- 所有压测脚本必须复用该公共类。
- 禁止每个脚本各自重新解析配置。

## 4. 压测脚本规范

### 4.1 HTTP 压测
- 脚本：`loadtests/http/locustfile_speech_transcriptions.py`
- `host` 必须从 `rest.<active_env>.rest_url` 派生。
- 失败日志必须包含可定位信息（状态码、URL、错误类型、响应片段）。

### 4.2 长连接压测
- 入口脚本：`locustfile_singlechat_online.py`
- 连接脚本：`loadtests/longconn/locustfile_singlechat_online.py`
- 连接参数必须来自 `locust.<active_env>`。
- 其它行为参数来自 `locust` 公共字段。

### 4.3 指标要求
- 至少包含：`send_to_ack`、`end_to_end`、`send_error`、`online_users`（如场景需要）。
- 需支持 Locust CSV 输出并可复盘。

## 5. 安全规范
- 日志与异常中不得输出明文 Token。
- Token 仅允许存放在 `config/.env`。
- 文档示例中的敏感字段必须脱敏。

## 6. 测试规范
- 必须覆盖：
  - `active_env` 环境选择正确性
  - 公共配置类正常路径
  - 缺失字段直接报错路径
- 推荐测试文件：
  - `tests/test_config_loader.py`
  - `tests/test_loadtests_config_center.py`

## 7. 文档维护规范
- 规则只写在本文件；`agents/` 与 `skills/` 仅写执行清单。
- 脚本路径或配置字段变化时，本文件与 `docs/README.md` 必须同步更新。
