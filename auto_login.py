import logging
import shutil
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time
import subprocess
import traceback

class CampusNetworkLogin:
    def __init__(self) -> None:
        logging.info("启动 Selenium")

        # 禁用系统代理，防止干扰本地驱动连接
        os.environ['no_proxy'] = '*'
        if 'http_proxy' in os.environ: del os.environ['http_proxy']
        if 'https_proxy' in os.environ: del os.environ['https_proxy']

        # 设置 Chrome 选项
        chrome_options = webdriver.ChromeOptions()
        # 指定下载的 chrome.exe 路径
        chrome_options.binary_location = r"D:\XunLei\chrome-win64\chrome.exe"
        # chrome_options.add_argument("--headless") # 重新开启无头模式
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # 忽略证书错误和安全警告
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--ignore-ssl-errors")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--test-type")
        # 允许不安全证书 (Seleinum 4 标准写法)
        chrome_options.set_capability("acceptInsecureCerts", True)
        # 强制将该站点视为安全站点，防止弹出"不安全连接"拦截
        chrome_options.add_argument("--unsafely-treat-insecure-origin-as-secure=http://10.10.9.9,http://123.123.123.123")
        
        # 设置窗口大小，防止 headless 模式下元素重叠或不显示
        chrome_options.add_argument("--window-size=1920,1080")

        try:
            print("正在启动 Chrome...")
            self.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            logging.error(f"启动 Chrome 失败: {e}")
            print("提示：请确保网络正常或驱动已正确下载。")
            exit(1)

    # 登录校园网
    def login_campus_network(self):
        driver = self.driver
        max_attempts = 3
        attempts = 0

        while attempts < max_attempts:
            try:
                print(f"正在访问登录页面... 第 {attempts + 1} 次尝试")
                driver.get('http://10.10.9.9/')
                time.sleep(3) # 等待页面跳转

                # 检查是否已经登录 (根据 HTML, 可能没有 toLogOut，这里可以根据标题判断)
                if "成功" in driver.title or "已经登录" in driver.page_source:
                    print("检测到已经登录成功。")
                    return

                # 登录流程
                try:
                    # 使用 ActionChains 防止普通交互失败
                    actions = ActionChains(driver)

                    print("正在输入用户名...")
                    # 尝试处理用户名提示框遮挡问题
                    try:
                        username_tip = driver.find_element(By.ID, 'username_tip')
                        if username_tip.is_displayed():
                            print("检测到用户名提示遮罩，正在点击...")
                            # 尝试点击遮罩
                            try:
                                username_tip.click()
                            except:
                                actions.click(username_tip).perform()
                            time.sleep(0.5)
                    except:
                        pass

                    username_input = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, 'username'))
                    )
                    username_input.clear()
                    # 回退到普通输入方式，防止 ActionChains 在某些情况下失效
                    try:
                         username_input.click()
                         username_input.send_keys('23721830')
                    except:
                         print("普通输入失败，尝试 ActionChains...")
                         actions.click(username_input).send_keys('xxxxxxx').perform()
                    
                    time.sleep(1) # 增加短暂等待

                    print("正在输入密码...")
                    try:
                        pwd_tip = driver.find_element(By.ID, 'pwd_tip')
                        if pwd_tip.is_displayed():
                            print("检测到密码提示遮罩，正在点击...")
                            actions.click(pwd_tip).perform()
                            time.sleep(0.5)
                    except Exception as e:
                        print(f"尝试点击提示遮罩时忽略错误: {e}")

                    password_input = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, 'pwd'))
                    )
                    password_input.clear()
                    actions.click(password_input).send_keys('xxxxxxxx').perform()

                    print("正在点击登录按钮...")
                    # 直接点击 a 标签
                    login_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, 'loginLink'))
                    )
                    # login_button.click()
                    actions.click(login_button).perform()

                    # 等待登录结果
                    time.sleep(5)
                    if self.check_network_connection():
                        print("校园网登录成功！")
                        return
                    else:
                        print("登录后网络仍未通，可能账户密码错误或欠费。")
                        driver.save_screenshot('error_result.png')
                
                except Exception as e:
                    print(f"操作页面元素时出错: {e}")
                    traceback.print_exc()
                    driver.save_screenshot(f'error_step_{attempts}.png')
                    attempts += 1

            except Exception as e:
                print(f"页面加载出错: {e}")
                attempts += 1
            
            time.sleep(2)

        print("达到最大尝试次数，登录失败。")

    # 检查网络是否可以 ping 通百度
    def check_network_connection(self):
        try:
            # Windows 下 ping 参数是 -n
            result = subprocess.run(['ping', '-n', '1', 'www.baidu.com'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return result.returncode == 0
        except Exception as e:
            print(f"检查网络连接时出错: {e}")
            return False

    # 检查网络连接状态
    def check_and_login(self):
        if self.check_network_connection():
            print("网络连接正常，无需登录。")
        else:
            print("网络无法连接，尝试登录校园网...")
            self.login_campus_network()

# 创建 CampusNetworkLogin 实例并调用 check_and_login 函数
campus_network = CampusNetworkLogin()
campus_network.check_and_login()