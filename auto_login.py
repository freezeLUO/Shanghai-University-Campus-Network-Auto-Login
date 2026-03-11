import json
import logging
import os
import shutil
import signal
import time
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Event

from mutual_watchdog import (
    AUTO_LOGIN_ROLE,
    SUPERVISION_INTERVAL_SECONDS,
    WATCHDOG_ROLE,
    CompanionSupervisor,
    is_watchdog_enabled,
)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
BAIDU_TEST_URL = "https://www.baidu.com/"
DEFAULT_CHECK_INTERVAL = 60
MIN_CHECK_INTERVAL = 5
NETWORK_TIMEOUT = 5
MAX_LOGIN_ATTEMPTS = 3
DRIVER_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "no_proxy",
    "NO_PROXY",
)


def normalize_executable_path(raw_path):
    raw_path = raw_path.strip().strip('"')
    if not raw_path:
        return ""

    expanded_path = os.path.expandvars(os.path.expanduser(raw_path))
    resolved_path = shutil.which(expanded_path)
    if resolved_path:
        return resolved_path
    if os.path.exists(expanded_path):
        return str(Path(expanded_path).resolve())
    return expanded_path


def normalize_check_interval(raw_value):
    try:
        interval = int(raw_value)
    except (TypeError, ValueError):
        logging.warning("check_interval 无效，已回退到默认值 %s 秒", DEFAULT_CHECK_INTERVAL)
        return DEFAULT_CHECK_INTERVAL

    if interval < MIN_CHECK_INTERVAL:
        logging.warning("check_interval 过小，已调整为 %s 秒", MIN_CHECK_INTERVAL)
        return MIN_CHECK_INTERVAL

    return interval


def save_config(config):
    with CONFIG_FILE.open('w', encoding='utf-8') as file:
        json.dump(config, file, indent=4, ensure_ascii=False)


def normalize_config(raw_config):
    config = dict(raw_config)
    config["chrome_binary"] = normalize_executable_path(config.get("chrome_binary", ""))
    config["chromedriver_path"] = normalize_executable_path(config.get("chromedriver_path", ""))
    config["username"] = str(config.get("username", "")).strip()
    config["password"] = str(config.get("password", "")).strip()
    config["check_interval"] = normalize_check_interval(config.get("check_interval", DEFAULT_CHECK_INTERVAL))
    return config


def get_config():
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open('r', encoding='utf-8') as file:
                config = normalize_config(json.load(file))
        except (OSError, json.JSONDecodeError) as exc:
            logging.error("读取配置文件失败: %s", exc)
            raise SystemExit(1) from exc

        missing_fields = [field for field in ("username", "password") if not config.get(field)]
        if missing_fields:
            logging.error("配置文件缺少必要字段: %s", ", ".join(missing_fields))
            raise SystemExit(1)

        save_config(config)
        return config

    print("=== 首次运行配置 ===")
    print("提示：Windows 可以输入完整路径，Linux 也支持 ~、环境变量和 PATH 中的可执行文件名。")

    chrome_binary = normalize_executable_path(
        input("请输入 Chrome 浏览器完整路径，留空则使用系统默认 Chrome: ")
    )
    chromedriver_path = normalize_executable_path(
        input("请输入 ChromeDriver 完整路径，留空则尝试 Selenium Manager: ")
    )
    username = input("请输入校园网账号: ").strip()
    password = input("请输入校园网密码: ").strip()

    config = normalize_config(
        {
            "chrome_binary": chrome_binary,
            "chromedriver_path": chromedriver_path,
            "username": username,
            "password": password,
            "check_interval": DEFAULT_CHECK_INTERVAL,
        }
    )

    save_config(config)
    print(f"配置已保存至 {CONFIG_FILE}")
    return config


def install_signal_handlers(stop_event, supervisor):
    def handle_stop_signal(signum, _frame):
        logging.info("收到退出信号 %s，准备停止脚本", signum)
        supervisor.request_shutdown(f"主程序收到退出信号 {signum}")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_stop_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_stop_signal)


class CampusNetworkLogin:
    def __init__(self, config) -> None:
        self.config = config
        self.chrome_options = self._setup_options()
        self.chromedriver_path = self.config.get("chromedriver_path", "")
        self.driver = None
        self._proxy_env_backup = None
        self._baidu_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _setup_options(self):
        chrome_options = webdriver.ChromeOptions()
        chrome_binary = self.config.get("chrome_binary")
        if chrome_binary:
            chrome_options.binary_location = chrome_binary

        headless_env = os.environ.get("HEADLESS", "").strip()
        if headless_env != "0":
            chrome_options.add_argument("--headless=new")

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--ignore-ssl-errors")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.set_capability("acceptInsecureCerts", True)
        chrome_options.add_argument("--unsafely-treat-insecure-origin-as-secure=http://10.10.9.9")
        return chrome_options

    def _disable_proxy_for_webdriver(self):
        if self._proxy_env_backup is not None:
            return

        self._proxy_env_backup = {key: os.environ.get(key) for key in DRIVER_PROXY_ENV_KEYS}
        for key in DRIVER_PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["no_proxy"] = "*"
        os.environ["NO_PROXY"] = "*"

    def _restore_proxy_env(self):
        if self._proxy_env_backup is None:
            return

        for key, value in self._proxy_env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._proxy_env_backup = None

    def _start_driver(self):
        chrome_binary = self.config.get("chrome_binary")
        if chrome_binary and not os.path.exists(chrome_binary):
            logging.error("未找到 Chrome 浏览器: %s", chrome_binary)
            return False

        self._disable_proxy_for_webdriver()

        try:
            if self.chromedriver_path:
                if not os.path.exists(self.chromedriver_path):
                    logging.error("未找到 chromedriver: %s", self.chromedriver_path)
                    self._restore_proxy_env()
                    return False
                service = Service(self.chromedriver_path)
                self.driver = webdriver.Chrome(service=service, options=self.chrome_options)
            else:
                self.driver = webdriver.Chrome(options=self.chrome_options)

            self.driver.set_page_load_timeout(20)
            self.driver.set_script_timeout(20)
            logging.info("Chrome 驱动已启动")
            return True
        except Exception as exc:
            logging.error("启动 Chrome 失败: %s", exc)
            self._safe_quit_driver()
            return False

    def _safe_quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
                logging.info("Chrome 驱动已关闭，释放资源")
            except Exception as exc:
                logging.warning("关闭 Chrome 驱动时出错: %s", exc)
        self.driver = None
        self._restore_proxy_env()

    def _perform_login_attempt(self, attempt):
        driver = self.driver
        logging.info("正在访问登录页面... 第 %s 次尝试", attempt)
        driver.get('http://10.10.9.9/')
        time.sleep(3)

        if "成功" in driver.title or "已经登录" in driver.page_source:
            logging.info("检测到已经登录成功。")
            return True

        actions = ActionChains(driver)

        try:
            username_tip = driver.find_element(By.ID, 'username_tip')
            if username_tip.is_displayed():
                username_tip.click()
                time.sleep(0.5)
        except Exception:
            pass

        username_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'username'))
        )
        username_input.clear()
        username_input.send_keys(self.config["username"])
        time.sleep(1)

        try:
            pwd_tip = driver.find_element(By.ID, 'pwd_tip')
            if pwd_tip.is_displayed():
                actions.click(pwd_tip).perform()
                time.sleep(0.5)
        except Exception:
            pass

        password_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'pwd'))
        )
        password_input.clear()
        password_input.send_keys(self.config["password"])

        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'loginLink'))
        )
        actions.click(login_button).perform()

        time.sleep(5)
        return self.check_network_connection()

    def login_campus_network(self):
        success = False

        try:
            for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
                self._safe_quit_driver()
                if not self._start_driver():
                    break

                try:
                    if self._perform_login_attempt(attempt):
                        logging.info("校园网登录成功！")
                        success = True
                        break
                    logging.warning("登录后仍无法访问百度官网，第 %s 次尝试失败", attempt)
                except Exception as exc:
                    logging.error("登录过程中出错，第 %s 次尝试失败: %s", attempt, exc)

                if attempt < MAX_LOGIN_ATTEMPTS:
                    time.sleep(min(10, attempt * 2))
        finally:
            self._safe_quit_driver()

        return success

    def check_network_connection(self):
        request = urllib.request.Request(
            BAIDU_TEST_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0 Safari/537.36"
                )
            },
        )

        try:
            with self._baidu_opener.open(request, timeout=NETWORK_TIMEOUT) as response:
                response.read(1)
                status_code = getattr(response, "status", response.getcode())
                hostname = urllib.parse.urlparse(response.geturl()).hostname or ""
                if 200 <= status_code < 400 and (
                    hostname == "baidu.com" or hostname.endswith(".baidu.com")
                ):
                    return True

                logging.debug(
                    "访问百度返回非预期结果: status=%s host=%s",
                    status_code,
                    hostname,
                )
                return False
        except Exception as exc:
            logging.debug("访问百度失败: %s", exc)
            return False

    def check_and_login(self):
        if self.check_network_connection():
            return

        logging.warning("当前无法访问百度官网，触发自动登录流程...")
        self.login_campus_network()

    def shutdown(self):
        self._safe_quit_driver()


def main():
    supervisor = CompanionSupervisor(
        role=AUTO_LOGIN_ROLE,
        peer_role=WATCHDOG_ROLE,
        own_script_path=Path(__file__),
        peer_script_path=SCRIPT_DIR / "watchdog.py",
    )
    stop_event = Event()
    install_signal_handlers(stop_event, supervisor)
    if not supervisor.acquire_single_instance():
        return

    campus_network = None
    try:
        current_config = get_config()
        campus_network = CampusNetworkLogin(current_config)
        interval = current_config["check_interval"]
        next_check_time = 0.0
        watchdog_enabled = is_watchdog_enabled()

        logging.info("进入常驻模式，每 %s 秒检查一次网络", interval)
        if watchdog_enabled:
            supervisor.ensure_peer_running()
            logging.info("互监模式已启用，主程序与 watchdog 会互相拉起")
        else:
            logging.info("互监模式已禁用，设置 ENABLE_WATCHDOG=1 可重新启用")

        while not stop_event.is_set():
            supervisor.heartbeat()
            if supervisor.has_shutdown_request():
                shutdown_request = supervisor.get_shutdown_request() or {}
                logging.info(
                    "检测到全局停机请求，主程序准备退出: %s",
                    shutdown_request.get("reason", "未提供原因"),
                )
                stop_event.set()
                continue
            if watchdog_enabled:
                supervisor.ensure_peer_running()

            now = time.monotonic()
            if now >= next_check_time:
                try:
                    campus_network.check_and_login()
                except Exception:
                    logging.exception("循环执行时发生未捕获异常")
                next_check_time = time.monotonic() + interval

            wait_seconds = min(
                SUPERVISION_INTERVAL_SECONDS,
                max(0.5, next_check_time - time.monotonic()),
            )
            stop_event.wait(wait_seconds)
    finally:
        if campus_network is not None:
            campus_network.shutdown()
        supervisor.release_instance()

if __name__ == "__main__":
    main()
