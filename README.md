# Cerebras 批量自动注册工具

By Isla7940

使用 Python + Playwright 自动化注册 Cerebras Cloud 账号，集成临时邮箱自动接收验证邮件。

## 功能

- Web 管理界面 + 命令行双模式
- 自动创建临时邮箱、填写注册表单
- 自动接收并处理验证邮件（支持验证链接和验证码）
- 自动获取 API Key，未获取到自动标记失败
- 批量注册，支持并行流水线
- 反检测：随机延迟、User-Agent 伪装、WebDriver 隐藏
- IP 切换提醒、Key 批量测试、一键导出

## 一键启动

```bash
uv run main.py
```
首次运行会自动安装依赖，然后启动 Web 管理界面。
浏览器打开 `http://localhost:5000` 即可操作。

> 需要先安装 [uv](https://docs.astral.sh/uv/)：`pip install uv` 或 `pipx install uv`
> 首次还需安装浏览器：`uv run playwright install chromium`

## 更多用法

```bash
uv run main.py web --port 5000     # 指定端口
uv run main.py cli -n 5            # 命令行注册 5 个
uv run main.py cli -n 10 -p 2      # 并行 2 个注册 10 个
uv run main.py cli -n 3 --headless  # 无头模式
```

## 配置

编辑 `config.py` 调整参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `HEADLESS` | 是否无头模式 | `False` |
| `SLOW_MO` | 操作间隔(ms) | `500` |
| `BATCH_SIZE` | 每批数量 | `5` |
| `BATCH_DELAY` | 批次间隔(秒) | `10` |
| `EMAIL_WAIT_TIMEOUT` | 等待验证邮件超时(秒) | `120` |
