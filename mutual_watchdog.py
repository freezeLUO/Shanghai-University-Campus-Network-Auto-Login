import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

AUTO_LOGIN_ROLE = "auto_login"
WATCHDOG_ROLE = "watchdog"
MANUAL_STOP_ROLE = "manual_stop"
STATE_DIR_NAME = ".runtime"
SUPERVISION_INTERVAL_SECONDS = 5
PEER_LAUNCH_COOLDOWN_SECONDS = 15
ENABLE_WATCHDOG_ENV = "ENABLE_WATCHDOG"
SHUTDOWN_REQUEST_FILE_NAME = "shutdown_request.json"


def is_watchdog_enabled():
    value = os.environ.get(ENABLE_WATCHDOG_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def is_process_running(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False

    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        return _is_process_running_windows(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_process_running_windows(pid):
    import ctypes

    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    wait_timeout = 0x00000102

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        process_query_limited_information | synchronize,
        False,
        pid,
    )
    if not handle:
        return False

    try:
        result = kernel32.WaitForSingleObject(handle, 0)
        return result == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def _read_json_file(file_path):
    try:
        with file_path.open('r', encoding='utf-8') as file:
            return json.load(file)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _write_json_atomic(file_path, data):
    temp_file = file_path.with_suffix(file_path.suffix + ".tmp")
    with temp_file.open('w', encoding='utf-8') as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    temp_file.replace(file_path)


class CompanionSupervisor:
    def __init__(self, role, peer_role, own_script_path, peer_script_path, logger=None):
        self.role = role
        self.peer_role = peer_role
        self.own_script_path = Path(own_script_path).resolve()
        self.peer_script_path = Path(peer_script_path).resolve()
        self.script_dir = self.own_script_path.parent
        self.state_dir = self.script_dir / STATE_DIR_NAME
        self.state_file = self.state_dir / f"{self.role}.json"
        self.peer_state_file = self.state_dir / f"{self.peer_role}.json"
        self.shutdown_request_file = self.state_dir / SHUTDOWN_REQUEST_FILE_NAME
        self.logger = logger or logging.getLogger(self.role)
        self.instance_id = uuid.uuid4().hex
        self.started_at = time.time()
        self._last_launch_attempt = 0.0

    def acquire_single_instance(self):
        self.state_dir.mkdir(exist_ok=True)
        self.cleanup_runtime_files_if_all_stopped()
        if self.has_shutdown_request():
            self.logger.info("检测到全局停机请求，当前不启动 %s", self.role)
            return False

        current_state = _read_json_file(self.state_file)
        existing_pid = self._extract_pid(current_state)
        if existing_pid and existing_pid != os.getpid() and is_process_running(existing_pid):
            self.logger.warning("检测到 %s 已在运行，当前实例退出: PID=%s", self.role, existing_pid)
            return False

        self.heartbeat()
        return True

    def heartbeat(self):
        self.state_dir.mkdir(exist_ok=True)
        payload = {
            "role": self.role,
            "pid": os.getpid(),
            "instance_id": self.instance_id,
            "started_at": self.started_at,
            "updated_at": time.time(),
            "script": self.own_script_path.name,
        }
        _write_json_atomic(self.state_file, payload)

    def request_shutdown(self, reason, requester_role=None):
        self.state_dir.mkdir(exist_ok=True)
        payload = {
            "requester_role": requester_role or self.role,
            "requester_pid": os.getpid(),
            "requested_at": time.time(),
            "reason": reason,
        }
        _write_json_atomic(self.shutdown_request_file, payload)

    def has_shutdown_request(self):
        return isinstance(_read_json_file(self.shutdown_request_file), dict)

    def get_shutdown_request(self):
        shutdown_request = _read_json_file(self.shutdown_request_file)
        if isinstance(shutdown_request, dict):
            return shutdown_request
        return None

    def ensure_peer_running(self):
        if self.has_shutdown_request():
            return False

        peer_state = _read_json_file(self.peer_state_file)
        peer_pid = self._extract_pid(peer_state)
        if peer_pid and is_process_running(peer_pid):
            return False

        if not self.peer_script_path.exists():
            self.logger.error("未找到需要监督的脚本: %s", self.peer_script_path)
            return False

        now = time.monotonic()
        if now - self._last_launch_attempt < PEER_LAUNCH_COOLDOWN_SECONDS:
            return False

        self._last_launch_attempt = now
        if peer_pid:
            self.logger.warning("检测到 %s 已退出，准备重新拉起", self.peer_role)
        else:
            self.logger.warning("检测到 %s 未运行，准备拉起", self.peer_role)

        try:
            subprocess.Popen(
                [sys.executable, str(self.peer_script_path)],
                cwd=str(self.script_dir),
                env=os.environ.copy(),
            )
            return True
        except Exception as exc:
            self.logger.error("拉起 %s 失败: %s", self.peer_role, exc)
            return False

    def get_known_processes(self):
        processes = []
        for role, state_file in (
            (self.role, self.state_file),
            (self.peer_role, self.peer_state_file),
        ):
            state = _read_json_file(state_file)
            pid = self._extract_pid(state)
            if pid and is_process_running(pid):
                processes.append((role, pid))
        return processes

    def cleanup_runtime_files_if_all_stopped(self):
        if self.get_known_processes():
            return False

        for file_path in (self.state_file, self.peer_state_file, self.shutdown_request_file):
            try:
                file_path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                self.logger.debug("删除运行时文件失败 %s: %s", file_path, exc)
        return True

    def release_instance(self):
        current_state = _read_json_file(self.state_file)
        if not current_state:
            self.cleanup_runtime_files_if_all_stopped()
            return

        if current_state.get("instance_id") != self.instance_id:
            self.cleanup_runtime_files_if_all_stopped()
            return

        try:
            self.state_file.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            self.logger.debug("删除 %s 状态文件失败: %s", self.role, exc)
        finally:
            self.cleanup_runtime_files_if_all_stopped()

    @staticmethod
    def _extract_pid(state):
        if not isinstance(state, dict):
            return None

        pid = state.get("pid")
        try:
            return int(pid)
        except (TypeError, ValueError):
            return None
