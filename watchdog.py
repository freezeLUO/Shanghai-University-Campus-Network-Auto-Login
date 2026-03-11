import logging
import signal
from pathlib import Path
from threading import Event

from mutual_watchdog import (
    AUTO_LOGIN_ROLE,
    SUPERVISION_INTERVAL_SECONDS,
    WATCHDOG_ROLE,
    CompanionSupervisor,
    is_watchdog_enabled,
)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

SCRIPT_DIR = Path(__file__).resolve().parent


def install_signal_handlers(stop_event, supervisor):
    def handle_stop_signal(signum, _frame):
        logging.info("watchdog 收到退出信号 %s，准备停止", signum)
        supervisor.request_shutdown(f"watchdog 收到退出信号 {signum}")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_stop_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_stop_signal)


def main():
    if not is_watchdog_enabled():
        logging.info("ENABLE_WATCHDOG=0，watchdog 不启动")
        return

    supervisor = CompanionSupervisor(
        role=WATCHDOG_ROLE,
        peer_role=AUTO_LOGIN_ROLE,
        own_script_path=Path(__file__),
        peer_script_path=SCRIPT_DIR / "auto_login.py",
    )
    stop_event = Event()
    install_signal_handlers(stop_event, supervisor)
    if not supervisor.acquire_single_instance():
        return

    logging.info("watchdog 已启动，每 %s 秒检查一次主程序", SUPERVISION_INTERVAL_SECONDS)
    try:
        supervisor.ensure_peer_running()
        while not stop_event.is_set():
            supervisor.heartbeat()
            if supervisor.has_shutdown_request():
                shutdown_request = supervisor.get_shutdown_request() or {}
                logging.info(
                    "检测到全局停机请求，watchdog 准备退出: %s",
                    shutdown_request.get("reason", "未提供原因"),
                )
                stop_event.set()
                continue
            supervisor.ensure_peer_running()
            stop_event.wait(SUPERVISION_INTERVAL_SECONDS)
    finally:
        supervisor.release_instance()


if __name__ == "__main__":
    main()