"""Cerebras 注册工具 - 统一入口  |  By Isla7940

用法:
    python main.py                # 启动 Web 管理界面 (默认)
    python main.py web --port 5000 # 指定端口
    python main.py cli -n 5       # 命令行注册 5 个
    python main.py cli -n 10 -p 3 # 并行 3 个流水线注册 10 个
    python main.py cli -n 5 -p 5 --headless  # 无头 + 全并行

并行说明:
    -p / 并行数: 1~5，每个 worker 独立浏览器实例
    5 个并行约占 2~3GB 内存，按需调整
"""

import os
import sys
import time
import argparse
import threading
from datetime import datetime
from loguru import logger

_file_lock = threading.Lock()
_BANNER = "By Isla7940"


def setup_logging():
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{message}</cyan>"
        ),
        level="DEBUG",
    )
    logger.add(
        "logs/register_{time:YYYY-MM-DD}.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
    )


def _save_result_cli(result: dict, output_file: str):
    """保存注册结果到文件（线程安全，没拿到 Key 则标记失败且不写入）"""
    api_key = (result.get('api_key') or '').strip()
    if not api_key:
        result['status'] = 'failed'
        logger.warning("未获取到 API Key，标记为失败，跳过写入")
        return
    with _file_lock, open(output_file, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"[{timestamp}] "
            f"Email: {result['email']} | "
            f"API Key: {api_key} | "
            f"Name: {result['user_info']['full_name']} | "
            f"Status: {result['status']}\n"
        )
        f.write(line)
    logger.info(f"结果已保存到 {output_file}")


def _register_worker_cli(worker_id: int, output_file: str) -> dict:
    """单个注册任务（独立浏览器实例）"""
    from register import CerebrasRegistrar
    logger.info(f"[Worker-{worker_id}] 开始注册")
    with CerebrasRegistrar() as registrar:
        result = registrar.register_one()
        _save_result_cli(result, output_file)
        if result["status"] == "success":
            logger.success(
                f"[Worker-{worker_id}] 注册成功: {result['email']}"
            )
        else:
            logger.error(
                f"[Worker-{worker_id}] 注册失败: {result['status']}"
            )
    return result


def _run_batch_cli(count: int, output_file: str, parallel: int = 1):
    """批量注册（支持并行）

    Args:
        count: 注册数量
        output_file: 输出文件路径
        parallel: 并行数
    """
    from register import CerebrasRegistrar
    from config import BATCH_DELAY

    success_count = 0
    fail_count = 0

    logger.info(f"开始批量注册，目标数量: {count}，并行数: {parallel}")
    logger.info(f"结果将保存到: {output_file}")

    if parallel <= 1:
        # 串行模式
        with CerebrasRegistrar() as registrar:
            for i in range(count):
                logger.info(f"===== 第 {i + 1}/{count} 个账号 =====")
                result = registrar.register_one()
                _save_result_cli(result, output_file)
                if result["status"] == "success":
                    success_count += 1
                else:
                    fail_count += 1
                if i + 1 < count:
                    delay = BATCH_DELAY // 2
                    logger.info(f"等待 {delay} 秒后继续...")
                    time.sleep(delay)
    else:
        # 流水线模式：错开启动，最多 parallel 个同时运行
        stagger = BATCH_DELAY  # 每个 worker 间隔秒数
        threads = []       # (thread, start_time, worker_id)
        next_id = 1
        launched = 0

        while launched < count or threads:
            # 清理已完成的线程
            alive = []
            for t, st, wid, fut in threads:
                if t.is_alive():
                    alive.append((t, st, wid, fut))
                else:
                    # 收集结果
                    try:
                        result = fut["result"]
                        if result["status"] == "success":
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception:
                        fail_count += 1
            threads = alive

            # 有空位且还有任务
            if len(threads) < parallel and launched < count:
                # 检查距上次启动是否够 stagger 秒
                now = time.time()
                if threads:
                    last_start = max(st for _, st, _, _ in threads)
                    wait = stagger - (now - last_start)
                    if wait > 0:
                        logger.info(
                            f"距上个 worker 不足 {stagger}s，"
                            f"等待 {wait:.1f}s..."
                        )
                        time.sleep(wait)

                wid = next_id
                next_id += 1
                launched += 1
                fut = {"result": None}

                def _run(w=wid, o=output_file, f=fut):
                    f["result"] = _register_worker_cli(w, o)

                t = threading.Thread(target=_run, daemon=True)
                t.start()
                threads.append((t, time.time(), wid, fut))
                logger.info(
                    f"已启动 Worker-{wid} "
                    f"({launched}/{count}), "
                    f"当前并行: {len(threads)}"
                )
            else:
                time.sleep(1)

    logger.info("=" * 50)
    logger.info(f"注册完成! 成功: {success_count}, 失败: {fail_count}")
    logger.info(f"结果已保存到: {output_file}")


def _cmd_web(args):
    """启动 Web 管理界面"""
    os.makedirs("screenshots", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    print(f"\n  {_BANNER}\n")
    from app import app
    app.run(debug=False, host="0.0.0.0", port=args.port)


def _cmd_cli(args):
    """命令行批量注册"""
    from config import OUTPUT_FILE
    os.makedirs("screenshots", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    setup_logging()

    if args.headless:
        import config
        config.HEADLESS = True

    output = args.output or OUTPUT_FILE
    print(f"\n  {_BANNER}\n")
    logger.info("Cerebras 批量注册工具启动")
    logger.info(f"计划注册 {args.count} 个账号，并行: {args.parallel}")

    _run_batch_cli(args.count, output, args.parallel)
    print(f"\n  {_BANNER}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Cerebras 注册工具 - By Isla7940",
    )
    sub = parser.add_subparsers(dest="command")

    # 默认 / web 子命令
    web_parser = sub.add_parser("web", help="启动 Web 管理界面 (默认)")
    web_parser.add_argument(
        "--port", type=int, default=5000, help="端口 (默认: 5000)",
    )

    # cli 子命令
    cli_parser = sub.add_parser("cli", help="命令行批量注册")
    cli_parser.add_argument(
        "-n", "--count", type=int, default=1, help="注册数量 (默认: 1)",
    )
    cli_parser.add_argument(
        "-o", "--output", type=str, default=None, help="输出文件路径",
    )
    cli_parser.add_argument(
        "-p", "--parallel", type=int, default=1, help="并行数 (默认: 1)",
    )
    cli_parser.add_argument(
        "--headless", action="store_true", help="无头模式运行浏览器",
    )

    args = parser.parse_args()

    if args.command == "cli":
        _cmd_cli(args)
    else:
        # 默认启动 Web UI
        if not hasattr(args, 'port'):
            args.port = 5000
        _cmd_web(args)


if __name__ == "__main__":
    main()
