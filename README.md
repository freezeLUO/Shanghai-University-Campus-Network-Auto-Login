# 校园网自动登录脚本

这是一个使用 Python 和 Selenium 编写的自动化脚本，用于自动登录校园网认证系统（如 Dr.COM、深澜等基于 Web 的认证）。它支持无头模式运行（后台静默），并针对 Chrome 的 SSL 证书拦截和页面交互做了优化处理。

## 环境要求

- 操作系统：Windows / macOS / Linux
- Python 3.x
- Google Chrome 浏览器

## 安装步骤

### 1. 安装 Python 依赖

在终端中运行以下命令安装必要的库：
```bash
pip install selenium
```

### 2. 配置 Chrome 浏览器与驱动

本项目使用 Selenium 控制 Chrome 浏览器。你需要确保 Chrome 浏览器本体和对应的 ChromeDriver 已正确安装。

#### 方式一：自动下载（推荐，需先联网）
如果你当前的设备暂时可以访问外网（例如使用手机热点），Selenium (4.x 版本) 内置的 Selenium Manager 可以**自动下载**匹配的 Chrome 和驱动。
1. 确保电脑已联网。
2. 运行一次脚本，Selenium 会自动检测并配置环境。
3. 之后在内网环境即可使用。

#### 方式二：手动下载（无网环境或指定版本）
如果你的环境完全无法连接外网，或者需要指定特定版本的 Chrome，请按以下步骤操作：

1.  访问 **Chrome for Testing** 官方下载页：
    [https://googlechromelabs.github.io/chrome-for-testing/#stable](https://googlechromelabs.github.io/chrome-for-testing/#stable)
2.  下载 **Stable** 渠道中对应你系统的：
    -   **chrome** (浏览器本体)
    -   **chromedriver** (驱动程序)
3.  解压下载的文件（例如解压到 `D:\XunLei\chrome-win64\`）。
4.  **修改脚本路径**：
    打开 `auto_login.py`，找到 `chrome_options.binary_location`，将其修改为你解压的 `chrome.exe` 的绝对路径。

    ```python
    # 示例
    chrome_options.binary_location = r"D:\XunLei\chrome-win64\chrome.exe"
    ```

## 配置账号信息

打开 `auto_login.py` 文件，找到以下部分并填入你的校园网账号和密码：

```python
# 约第 80-90 行
username_input.send_keys('你的学号/账号')
# ...
actions.click(password_input).send_keys('你的密码').perform()
```

## 运行脚本

在终端中运行：

```bash
python auto_login.py
```

## 功能特性

*   **无头模式 (Headless)**: 默认在后台运行，不弹出浏览器窗口，适合挂在服务器或后台任务中。
*   **安全拦截绕过**: 内置多种策略（强制信任、参数绕过等）自动处理 Chrome 针对校园网内网证书的 "此网站不安全" 拦截。
*   **稳健交互**: 使用 `ActionChains` 和智能等待机制，解决输入框被遮罩挡住、点击无效等问题。
