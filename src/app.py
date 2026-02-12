"""Cerebras 注册工具 - Web UI"""

import os
import re
import json
import threading
import time
from datetime import datetime
from flask import Flask, render_template, jsonify, request
import httpx
from loguru import logger

app = Flask(__name__)

ACCOUNTS_FILE = "accounts.txt"
CEREBRAS_API_BASE = "https://api.cerebras.ai/v1/chat/completions"

# 注册任务状态
register_state = {
    "running": False,
    "total": 0,
    "done": 0,
    "current": 0,
    "phase": "",
    "results": [],
    "log": [],
}
_state_lock = threading.Lock()

# IP 切换提醒状态
ip_reminder = {
    "enabled": True,
    "interval": 5,
    "total_done": 0,
    "waiting": False,
}
_ip_confirm_event = threading.Event()
_ip_confirm_event.set()

# 日志级别对应的前端标签
_LEVEL_TAG = {
    "DEBUG": "DBG",
    "INFO": "INF",
    "SUCCESS": "OK",
    "WARNING": "WRN",
    "ERROR": "ERR",
}

# 从 loguru 消息中推断阶段
_PHASE_KEYWORDS = [
    ("临时邮箱", "创建邮箱"),
    ("浏览器上下文", "启动浏览器"),
    ("正在访问", "打开注册页"),
    ("已填写邮箱", "填写邮箱"),
    ("reCAPTCHA", "人机验证"),
    ("Continue", "提交注册"),
    ("Check your email", "等待验证邮件"),
    ("sign-in link", "处理验证链接"),
    ("onboarding", "填写资料"),
    ("API Key", "获取 API Key"),
    ("注册成功", "注册成功"),
    ("注册失败", "注册失败"),
]


def _log_sink(message):
    """loguru sink：捕获注册过程日志推送到前端"""
    record = message.record
    level = record["level"].name
    text = record["message"]

    # 过滤掉 DEBUG 级别的冗余信息
    if level == "DEBUG":
        return

    tag = _LEVEL_TAG.get(level, level)
    short = f"[{tag}] {text}"

    with _state_lock:
        register_state["log"].append(short)
        # 只保留最近 200 条
        if len(register_state["log"]) > 200:
            register_state["log"] = register_state["log"][-200:]
        # 自动推断当前阶段
        for keyword, phase in _PHASE_KEYWORDS:
            if keyword in text:
                register_state["phase"] = phase
                break


def parse_accounts() -> list:
    """解析 accounts.txt 获取所有账号信息"""
    accounts = []
    if not os.path.exists(ACCOUNTS_FILE):
        return accounts
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            match = re.match(
                r'\[(.+?)\]\s*Email:\s*(\S+)\s*\|\s*API Key:\s*(\S+)\s*\|\s*Name:\s*(.+?)\s*\|\s*Status:\s*(\S+)',
                line,
            )
            if match:
                accounts.append({
                    "time": match.group(1),
                    "email": match.group(2),
                    "api_key": match.group(3),
                    "name": match.group(4).strip(),
                    "status": match.group(5),
                    "key_valid": None,
                })
    return accounts


def test_single_key(api_key: str, model: str) -> dict:
    """测试单个 API Key"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello in one sentence."}],
        "max_tokens": 50,
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(CEREBRAS_API_BASE, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return {"valid": True, "reply": content[:80], "error": None}
            elif resp.status_code == 429:
                return {"valid": True, "reply": None, "error": "限流中(429)，Key有效但服务繁忙"}
            else:
                msg = resp.text[:120]
                return {"valid": False, "reply": None, "error": f"HTTP {resp.status_code}: {msg}"}
    except Exception as e:
        return {"valid": False, "reply": None, "error": str(e)}


# ── 路由 ──────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/accounts")
def api_accounts():
    """获取所有账号"""
    return jsonify(parse_accounts())


@app.route("/api/test_key", methods=["POST"])
def api_test_key():
    """测试单个 Key"""
    data = request.json
    api_key = data.get("api_key", "")
    model = data.get("model", "qwen-3-32b")
    result = test_single_key(api_key, model)
    return jsonify(result)


@app.route("/api/test_all", methods=["POST"])
def api_test_all():
    """测试所有 Key"""
    model = request.json.get("model", "qwen-3-32b")
    accounts = parse_accounts()
    results = []
    for acc in accounts:
        r = test_single_key(acc["api_key"], model)
        results.append({
            "name": acc["name"],
            "email": acc["email"],
            "api_key": acc["api_key"],
            **r,
        })
    return jsonify(results)


@app.route("/api/delete_account", methods=["POST"])
def api_delete_account():
    """删除指定账号"""
    api_key = request.json.get("api_key", "")
    if not api_key or not os.path.exists(ACCOUNTS_FILE):
        return jsonify({"ok": False, "msg": "无效请求"})
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new_lines = [l for l in lines if api_key not in l]
    if len(new_lines) == len(lines):
        return jsonify({"ok": False, "msg": "未找到该账号"})
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    return jsonify({"ok": True, "msg": "已删除"})


def _save_result(result: dict, output_file: str):
    """保存单个注册结果到文件（没拿到 Key 则标记失败且不写入）"""
    api_key = (result.get('api_key') or '').strip()
    if not api_key:
        result['status'] = 'failed'
        return
    with open(output_file, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"[{timestamp}] "
            f"Email: {result['email']} | "
            f"API Key: {api_key} | "
            f"Name: {result['user_info']['full_name']} | "
            f"Status: {result['status']}\n"
        )
        f.write(line)


def _on_register_done(result: dict, label: str):
    """注册完成后更新共享状态"""
    with _state_lock:
        register_state["done"] += 1
        status_icon = "OK" if result["status"] == "success" else "FAIL"
        register_state["results"].append({
            "email": result["email"],
            "api_key": result.get("api_key", "")[:12] + "...",
            "status": result["status"],
            "name": result["user_info"]["full_name"],
        })
        register_state["log"].append(
            f"[{status_icon}] {label}: "
            f"{result['user_info']['full_name']} "
            f"({result['email']})"
        )
        if result["status"] == "success":
            ip_reminder["total_done"] += 1


def _do_ip_remind():
    """执行 IP 切换提醒：阻塞直到用户确认"""
    with _state_lock:
        ip_reminder["waiting"] = True
        register_state["phase"] = "等待切换 IP"
        register_state["log"].append(
            f"[WRN] 已完成 {ip_reminder['total_done']} 个账号，"
            "建议切换 IP 后继续"
        )
    _ip_confirm_event.clear()
    _ip_confirm_event.wait()
    with _state_lock:
        ip_reminder["waiting"] = False
        register_state["phase"] = "继续注册"
        register_state["log"].append("[INF] 用户已确认，继续注册...")


def _register_worker(worker_id: int, output_file: str):
    """单个并行 worker：独立浏览器实例完成一次注册"""
    from register import CerebrasRegistrar

    try:
        with CerebrasRegistrar() as reg:
            result = reg.register_one()
            _save_result(result, output_file)
            _on_register_done(result, f"Worker-{worker_id}")
    except Exception as e:
        with _state_lock:
            register_state["done"] += 1
            register_state["log"].append(f"[ERR] Worker-{worker_id} 出错: {e}")


def _run_register(count: int, parallel: int = 1):
    """在后台线程中执行注册（支持并行）"""
    with _state_lock:
        register_state["running"] = True
        register_state["total"] = count
        register_state["done"] = 0
        register_state["current"] = 0
        register_state["phase"] = "初始化"
        register_state["results"] = []
        register_state["log"] = ["By Isla7940"]

    # 挂载 loguru sink 捕获注册日志
    sink_id = logger.add(_log_sink, level="INFO", format="{message}")

    try:
        from config import OUTPUT_FILE, BATCH_DELAY

        if parallel <= 1:
            # ── 串行模式 ──
            from register import CerebrasRegistrar

            with CerebrasRegistrar() as reg:
                for i in range(count):
                    with _state_lock:
                        register_state["current"] = i + 1
                        register_state["phase"] = "准备注册"
                        register_state["log"].append(
                            f"━━━ 开始注册第 {i+1}/{count} 个账号 ━━━"
                        )
                    result = reg.register_one()
                    _save_result(result, OUTPUT_FILE)
                    _on_register_done(result, f"第 {i+1} 个完成")

                    # IP 切换提醒
                    with _state_lock:
                        need = (
                            ip_reminder["enabled"]
                            and ip_reminder["total_done"] > 0
                            and ip_reminder["total_done"] % ip_reminder["interval"] == 0
                            and i < count - 1
                        )
                    if need:
                        _do_ip_remind()
        else:
            # ── 流水线并行模式 ──
            stagger = BATCH_DELAY
            launched = 0
            next_wid = 1
            active = []  # [(thread, worker_id)]
            last_launch = 0.0
            last_reminded_total = 0

            with _state_lock:
                register_state["log"].append(
                    f"━━━ 流水线模式: {count} 个账号, {parallel} 并行 ━━━"
                )

            while launched < count or active:
                # 清理已完成的线程
                active = [(t, w) for t, w in active if t.is_alive()]

                with _state_lock:
                    register_state["current"] = launched
                    if active:
                        wids = ", ".join(str(w) for _, w in active)
                        register_state["phase"] = f"Worker {wids} 运行中"

                # IP 提醒检查：所有活跃 worker 完成后才提醒
                check_remind = False
                with _state_lock:
                    cur_total = ip_reminder["total_done"]
                    if (
                        ip_reminder["enabled"]
                        and cur_total > 0
                        and cur_total >= last_reminded_total + ip_reminder["interval"]
                        and launched < count
                    ):
                        check_remind = True

                if check_remind:
                    if active:
                        with _state_lock:
                            register_state["phase"] = "等待所有 Worker 完成"
                            register_state["log"].append(
                                "[INF] 等待运行中的 Worker 完成后提醒切换 IP..."
                            )
                        for t, _ in active:
                            t.join()
                        active = []
                    with _state_lock:
                        last_reminded_total = ip_reminder["total_done"]
                    _do_ip_remind()
                    continue

                # 启动新 worker
                if len(active) < parallel and launched < count:
                    now = time.time()
                    if active and (now - last_launch) < stagger:
                        wait = stagger - (now - last_launch)
                        with _state_lock:
                            register_state["log"].append(
                                f"[INF] 间隔等待 {wait:.0f}s 后启动下一个..."
                            )
                        time.sleep(wait)

                    wid = next_wid
                    next_wid += 1
                    launched += 1
                    with _state_lock:
                        register_state["log"].append(
                            f"━━━ 启动 Worker-{wid} ({launched}/{count}) ━━━"
                        )

                    t = threading.Thread(
                        target=_register_worker,
                        args=(wid, OUTPUT_FILE),
                        daemon=True,
                    )
                    t.start()
                    last_launch = time.time()
                    active.append((t, wid))
                else:
                    time.sleep(1)

    except Exception as e:
        with _state_lock:
            register_state["phase"] = "出错"
            register_state["log"].append(f"[ERR] 注册出错: {e}")
    finally:
        logger.remove(sink_id)
        with _state_lock:
            register_state["running"] = False
            register_state["phase"] = "已完成"
            register_state["log"].append("━━━ 注册任务已结束 ━━━")
            register_state["log"].append("By Isla7940")


@app.route("/api/register/start", methods=["POST"])
def api_register_start():
    """启动注册任务"""
    with _state_lock:
        if register_state["running"]:
            return jsonify({"ok": False, "msg": "已有注册任务在运行"})
    count = request.json.get("count", 1)
    parallel = request.json.get("parallel", 1)
    t = threading.Thread(target=_run_register, args=(count, parallel), daemon=True)
    t.start()
    mode = "流水线" if parallel > 1 else "串行"
    return jsonify({"ok": True, "msg": f"已启动注册 {count} 个账号（{mode}，并行 {parallel}）"})


@app.route("/api/register/status")
def api_register_status():
    """获取注册任务状态"""
    with _state_lock:
        data = dict(register_state)
        data["ip_reminder"] = dict(ip_reminder)
        return jsonify(data)


@app.route("/api/ip_reminder/respond", methods=["POST"])
def api_ip_reminder_respond():
    """用户响应 IP 切换提醒"""
    action = request.json.get("action", "")
    with _state_lock:
        if action == "disable":
            ip_reminder["enabled"] = False
        elif action == "custom":
            new_interval = request.json.get("interval", 5)
            ip_reminder["interval"] = max(1, int(new_interval))
        # action == "continue" 保持当前间隔不变
    _ip_confirm_event.set()
    return jsonify({"ok": True})


@app.route("/api/ip_reminder/setting", methods=["GET"])
def api_ip_reminder_get():
    """获取 IP 提醒设置"""
    with _state_lock:
        return jsonify({
            "enabled": ip_reminder["enabled"],
            "interval": ip_reminder["interval"],
        })


@app.route("/api/ip_reminder/setting", methods=["POST"])
def api_ip_reminder_set():
    """设置 IP 提醒间隔"""
    interval = request.json.get("interval", 5)
    with _state_lock:
        if interval <= 0:
            ip_reminder["enabled"] = False
        else:
            ip_reminder["enabled"] = True
            ip_reminder["interval"] = int(interval)
    return jsonify({"ok": True})


@app.route("/api/export_keys")
def api_export_keys():
    """导出所有成功的 API Key（纯文本，每行一个）"""
    accounts = parse_accounts()
    keys = [a["api_key"] for a in accounts if a["status"] == "success" and a["api_key"]]
    return "\n".join(keys), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/speed_mode", methods=["GET"])
def api_speed_mode_get():
    """获取当前速度模式"""
    import config as cfg
    return jsonify({"mode": cfg.SPEED_MODE})


@app.route("/api/speed_mode", methods=["POST"])
def api_speed_mode_set():
    """切换速度模式"""
    import config as cfg
    mode = request.json.get("mode", "standard")
    if mode not in cfg.SPEED_MODES:
        return jsonify({"ok": False, "msg": f"无效模式: {mode}"})
    cfg.SPEED_MODE = mode
    cfg.SLOW_MO = cfg.SPEED_MODES[mode]["slow_mo"]
    return jsonify({"ok": True, "mode": mode})


if __name__ == "__main__":
    print("\n  By Isla7940\n")
    os.makedirs("screenshots", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    app.run(debug=False, port=5000)
