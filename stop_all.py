import logging
import os
import signal
import time
from pathlib import Path

from mutual_watchdog import (
    AUTO_LOGIN_ROLE,
    MANUAL_STOP_ROLE,
    WATCHDOG_ROLE,
    CompanionSupervisor,
)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

SCRIPT_DIR = Path(__file__).resolve().parent
STOP_WAIT_TIMEOUT_SECONDS = 20
STOP_POLL_INTERVAL_SECONDS = 1


def request_stop_for_running_processes(supervisor):
    running_processes = supervisor.get_known_processes()
    if not running_processes:
        logging.info("当前没有检测到运行中的 auto_login.py 或 watchdog.py")
        supervisor.cleanup_runtime_files_if_all_stopped()
        return

    supervisor.request_shutdown("手动执行 stop_all.py", requester_role=MANUAL_STOP_ROLE)
    logging.info("已写入全局停机请求，准备停止现有进程")

    for role, pid in running_processes:
        try:
            os.kill(pid, signal.SIGTERM)
            logging.info("已向 %s 发送停止信号: PID=%s", role, pid)
        except ProcessLookupError:
            logging.info("%s 已退出: PID=%s", role, pid)
        except PermissionError as exc:
            logging.warning("无权停止 %s: PID=%s, 错误=%s", role, pid, exc)
        except OSError as exc:
            logging.warning("停止 %s 失败: PID=%s, 错误=%s", role, pid, exc)


def wait_for_stop(supervisor):
    deadline = time.monotonic() + STOP_WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        running_processes = supervisor.get_known_processes()
        if not running_processes:
            supervisor.cleanup_runtime_files_if_all_stopped()
            logging.info("auto_login.py 和 watchdog.py 已全部停止")
            return True
        time.sleep(STOP_POLL_INTERVAL_SECONDS)

    running_processes = supervisor.get_known_processes()
    if running_processes:
        process_text = ", ".join(f"{role}:{pid}" for role, pid in running_processes)
        logging.warning("等待超时，仍有进程未退出: %s", process_text)
        return False

    supervisor.cleanup_runtime_files_if_all_stopped()
    return True


def main():
    supervisor = CompanionSupervisor(
        role=AUTO_LOGIN_ROLE,
        peer_role=WATCHDOG_ROLE,
        own_script_path=SCRIPT_DIR / "auto_login.py",
        peer_script_path=SCRIPT_DIR / "watchdog.py",
    )
    request_stop_for_running_processes(supervisor)
    wait_for_stop(supervisor)


if __name__ == "__main__":
    main()