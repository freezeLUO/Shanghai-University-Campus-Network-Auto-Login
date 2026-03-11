# 校园网自动登录脚本

这是一个使用 Python 和 Selenium 编写的自动化脚本，用于自动登录校园网认证系统（如 Dr.COM、深澜等基于 Web 的认证）。脚本会常驻运行，并以“是否能够直接访问百度官网”为准判断当前是否已经联网。

## 环境要求

- 操作系统：Windows / Linux
- Python 3.x
- Selenium 4.x
- Google Chrome / Chromium

## 安装依赖

在终端中运行：

```bash
pip install selenium
```

## Chrome 与 ChromeDriver

脚本支持两种方式启动浏览器：

1. 手动指定 Chrome 和 ChromeDriver 的路径。
2. 留空 ChromeDriver 路径，让 Selenium Manager 尝试自动处理。

如果你完全离线，建议提前手动准备好匹配版本的 ChromeDriver。

## 首次运行配置

首次运行会在脚本同目录生成 config.json，并提示输入以下内容：

- chrome_binary：Chrome 浏览器路径，留空则使用系统默认 Chrome。
- chromedriver_path：ChromeDriver 路径，留空则尝试 Selenium Manager。
- username：校园网账号。
- password：校园网密码。
- check_interval：检查间隔，默认 60 秒，最小 5 秒。

示例配置：

```json
{
    "chrome_binary": "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "chromedriver_path": "C:/Tools/chromedriver.exe",
    "username": "你的账号",
    "password": "你的密码",
    "check_interval": 60
}
```

## 联网判断规则

脚本不再使用 ping，而是直接访问下面这个地址：

```text
https://www.baidu.com/
```

满足以下条件才判定为“已经联网”：

- 请求在超时时间内成功返回。
- 最终地址仍然是 baidu.com 域名。
- HTTP 状态码为 2xx 或 3xx。

如果被重定向到认证页、请求超时、DNS 解析失败，或者返回的不是百度域名，都会视为未联网并触发登录流程。

## 运行方式

直接运行：

```bash
python auto_login.py
```

默认会自动拉起 watchdog.py，主程序和 watchdog 会互相监督、互相拉起。

如果你只想单独启动监督程序，也可以运行：

```bash
python watchdog.py
```

如果你想一键停止主程序和 watchdog，也可以运行：

```bash
python stop_all.py
```

默认使用无头模式。如果你需要排查页面交互问题，可以临时关闭无头模式。

Linux / macOS:

```bash
HEADLESS=0 python auto_login.py
```

Windows PowerShell:

```powershell
$env:HEADLESS="0"
python auto_login.py
```

如果你想临时关闭互监功能：

Linux / macOS:

```bash
ENABLE_WATCHDOG=0 python auto_login.py
```

Windows PowerShell:

```powershell
$env:ENABLE_WATCHDOG="0"
python auto_login.py
```

## 互监模式

- auto_login.py 会周期性检查 watchdog.py 是否仍然存在，不在就重新拉起。
- watchdog.py 会周期性检查 auto_login.py 是否仍然存在，不在就重新拉起。
- 两个进程都限制为单实例运行，避免重复拉起多个同名进程。
- 运行时状态文件会写入脚本目录下的 .runtime 目录。

## 测试互监

可以按下面的方式手工验证互监是否生效：

1. 运行 python auto_login.py。
2. 确认脚本目录下出现 .runtime/auto_login.json 和 .runtime/watchdog.json。
3. 手动结束 auto_login.py 进程，等待 5 到 15 秒，观察 watchdog.py 是否将它重新拉起。
4. 手动结束 watchdog.py 进程，等待 5 到 15 秒，观察 auto_login.py 是否将它重新拉起。

如果你只想调试主程序逻辑，不想让它被自动拉起，可以临时关闭互监：

- Linux / macOS：ENABLE_WATCHDOG=0 python auto_login.py
- Windows PowerShell：$env:ENABLE_WATCHDOG="0" 后再运行 python auto_login.py

## 停止说明

- 现在推荐使用 python stop_all.py 完整停止 auto_login.py 和 watchdog.py。
- 如果在控制台中对其中任意一个进程按 Ctrl+C，它会先写入全局停机请求，再通知另一方一起退出。
- 如果你是直接在任务管理器里强制结束其中一个进程，另一方仍然会按互监逻辑把它重新拉起。
- 如果只是想临时调试或单步排查，建议先使用 ENABLE_WATCHDOG=0 启动主程序。

## 当前限制

- 当前互监是进程级监督，只能处理“进程退出”这一类故障。
- 如果进程还活着但内部逻辑卡死，另一方不会主动重启它。
- 状态文件只作为本机互监依据，不适合跨机器或跨目录共享使用。
- 在 Windows 上，stop_all.py 结束 Python 进程后，可能会短暂留下陈旧状态文件；下次启动会自动清理。

## 长时间运行说明

- 脚本退出时会主动关闭 Chrome 和 ChromeDriver。
- 登录失败时会重新创建浏览器会话，避免长时间运行后复用异常会话。
- 启动 WebDriver 时会临时关闭代理环境变量，退出后会恢复原值。
- 支持响应 Ctrl+C 和 SIGTERM，适合放到计划任务或服务中运行。
- 启用互监后，只要主程序或 watchdog 中任意一个异常退出，另一方会尝试重新拉起它。
