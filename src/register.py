"""Cerebras 自动注册核心模块"""

import random
import time
import re
import os
import shutil
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from playwright_stealth import Stealth
from loguru import logger
from temp_email import TempEmail
from config import (
    CEREBRAS_URL,
    HEADLESS,
    PAGE_TIMEOUT,
    FIRST_NAMES,
    LAST_NAMES,
    SPEED_MODES,
)
import config as _cfg


def generate_random_user() -> dict:
    """生成随机用户信息"""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    return {
        "first_name": first,
        "last_name": last,
        "full_name": f"{first} {last}",
    }


class CerebrasRegistrar:
    """Cerebras 账号自动注册器"""

    def __init__(self):
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.temp_email: TempEmail = None
        self._user_data_dir: str = None

    def start_browser(self):
        """初始化 Playwright"""
        self.playwright = sync_playwright().start()
        logger.info("浏览器引擎已初始化")

    def _create_context(self):
        """创建全新的浏览器上下文（独立临时目录 + 随机指纹）"""
        # 关闭旧的上下文
        self._close_context()

        # 创建全新的临时目录
        self._user_data_dir = f"./browser_data_{int(time.time())}_{random.randint(1000,9999)}"
        os.makedirs(self._user_data_dir, exist_ok=True)

        # 随机化 viewport
        width = random.randint(1200, 1400)
        height = random.randint(750, 900)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
        ]
        try:
            slow_mo = SPEED_MODES.get(_cfg.SPEED_MODE, {}).get("slow_mo", 300)
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                channel="chrome",
                headless=HEADLESS,
                slow_mo=slow_mo,
                args=launch_args,
                viewport={"width": width, "height": height},
                locale="en-US",
                timezone_id="America/New_York",
            )
        except Exception:
            slow_mo = SPEED_MODES.get(_cfg.SPEED_MODE, {}).get("slow_mo", 300)
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                headless=HEADLESS,
                slow_mo=slow_mo,
                args=launch_args,
                viewport={"width": width, "height": height},
                locale="en-US",
                timezone_id="America/New_York",
            )

        # 授权剪贴板权限
        self.context.grant_permissions(
            ["clipboard-read", "clipboard-write"],
            origin="https://cloud.cerebras.ai",
        )

        # 复用默认页面
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()
        stealth = Stealth()
        stealth.apply_stealth_sync(self.page)
        self.page.set_default_timeout(PAGE_TIMEOUT * 1000)
        logger.info(f"全新浏览器上下文已创建 (viewport={width}x{height})")

        # 创建后默认最小化窗口
        self._minimize_window()

    def _get_cdp_session(self):
        """获取 CDP session（用于窗口管理）"""
        try:
            return self.context.new_cdp_session(self.page)
        except Exception:
            return None

    def _minimize_window(self):
        """通过 CDP 最小化浏览器窗口"""
        try:
            cdp = self._get_cdp_session()
            if not cdp:
                return
            result = cdp.send("Browser.getWindowForTarget")
            window_id = result.get("windowId")
            if window_id:
                cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "minimized"},
                })
                logger.info("浏览器窗口已最小化")
            cdp.detach()
        except Exception as e:
            logger.debug(f"最小化窗口失败: {e}")

    def _restore_window(self):
        """通过 CDP 还原并置顶浏览器窗口"""
        try:
            cdp = self._get_cdp_session()
            if not cdp:
                return
            result = cdp.send("Browser.getWindowForTarget")
            window_id = result.get("windowId")
            if window_id:
                cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "normal"},
                })
                logger.info("浏览器窗口已还原")
            cdp.detach()
            self.page.bring_to_front()
        except Exception as e:
            logger.debug(f"还原窗口失败: {e}")

    def _close_context(self):
        """关闭当前上下文并清理临时目录"""
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
            self.page = None
        if self._user_data_dir and os.path.exists(self._user_data_dir):
            try:
                shutil.rmtree(self._user_data_dir)
            except Exception:
                pass
            self._user_data_dir = None

    def _random_delay(self, min_sec: float = 0.5, max_sec: float = 2.0):
        """模拟人类操作的随机延迟（受速度模式影响）"""
        mult = SPEED_MODES.get(_cfg.SPEED_MODE, {}).get("delay_mult", 1.0)
        time.sleep(random.uniform(min_sec * mult, max_sec * mult))

    def _human_type(self, selector: str, text: str):
        """模拟人类打字速度"""
        element = self.page.locator(selector)
        element.click()
        self._random_delay(0.3, 0.6)
        for char in text:
            element.press_sequentially(char, delay=random.randint(50, 150))
        self._random_delay(0.2, 0.5)

    def _navigate_to_signup(self):
        """导航到注册页面（Cerebras首页即为登录/注册页）"""
        logger.info(f"正在访问 {CEREBRAS_URL}")
        self.page.goto(CEREBRAS_URL, wait_until="domcontentloaded")
        # 等待页面渲染完成（不受速度模式影响）
        try:
            self.page.wait_for_selector(
                'input[name="email"], input[type="email"]',
                state="visible", timeout=15000,
            )
        except Exception:
            logger.warning("等待邮箱输入框超时，尝试继续...")
        self._random_delay(1, 2)
        self.page.screenshot(path="screenshots/01_landing.png")
        logger.info("已到达 Sign Up or Log In 页面")

    def _fill_email(self, email: str):
        """填写邮箱（Cerebras页面只有一个Email输入框）"""
        self._random_delay(1, 2)
        email_selectors = [
            'input[name="email"]',
            'input[type="email"]',
            'input[placeholder*="email" i]',
        ]
        self._fill_field(email_selectors, email, "邮箱")
        self._random_delay(0.5, 1)
        self.page.screenshot(path="screenshots/02_email_filled.png")
        logger.info(f"已填写邮箱: {email}")

    def _ensure_email_filled(self, email: str):
        """确认邮箱字段有值，如果被清空则重新填写"""
        email_selectors = [
            'input[name="email"]',
            'input[type="email"]',
            'input[placeholder*="email" i]',
        ]
        for selector in email_selectors:
            try:
                loc = self.page.locator(selector).first
                if loc.is_visible(timeout=2000):
                    current_val = loc.input_value()
                    if current_val.strip() == "" or current_val != email:
                        logger.warning(f"邮箱被清空了! 重新填写: {email}")
                        loc.fill("")
                        loc.press_sequentially(
                            email, delay=random.randint(30, 100)
                        )
                    else:
                        logger.info("邮箱字段正常，无需重新填写")
                    return
            except Exception:
                continue

    def _fill_field(
        self, selectors: list, value: str, field_name: str, required: bool = True
    ) -> bool:
        """尝试用多个选择器填写字段"""
        for selector in selectors:
            try:
                loc = self.page.locator(selector).first
                if loc.is_visible(timeout=8000):
                    loc.click()
                    loc.fill("")
                    self._random_delay(0.2, 0.4)
                    loc.press_sequentially(value, delay=random.randint(30, 100))
                    logger.info(f"已填写{field_name}: {value}")
                    return True
            except Exception:
                continue

        if required:
            logger.error(f"未找到{field_name}输入框")
            raise RuntimeError(f"找不到{field_name}字段")
        else:
            logger.debug(f"{field_name}字段不存在，跳过")
            return False

    def _wait_for_captcha(self):
        """等待用户手动完成 reCAPTCHA 验证

        检测页面上的 reCAPTCHA，提示用户手动点击完成验证，
        然后轮询等待验证完成。
        """
        # 用多种方式检测 reCAPTCHA 是否存在
        captcha_detected = False
        captcha_selectors = [
            'iframe[src*="recaptcha"]',
            'iframe[src*="google.com/recaptcha"]',
            'iframe[title*="reCAPTCHA"]',
            '.g-recaptcha',
            'div[data-sitekey]',
        ]
        for sel in captcha_selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=3000):
                    captcha_detected = True
                    logger.info(f"通过选择器检测到 reCAPTCHA: {sel}")
                    break
            except Exception:
                continue

        if not captcha_detected:
            logger.info("未检测到 reCAPTCHA，跳过")
            return

        # 弹出浏览器窗口让用户操作
        self._restore_window()

        logger.warning("=" * 50)
        logger.warning("检测到 reCAPTCHA 人机验证!")
        logger.warning("请在浏览器中手动完成验证（点击复选框 + 选图片）")
        logger.warning("完成后脚本将自动继续...")
        logger.warning("=" * 50)

        # 轮询等待 reCAPTCHA 完成
        max_wait = 300  # 最多等待 5 分钟
        start = time.time()
        while time.time() - start < max_wait:
            try:
                # 方法1: 检查 iframe 内的复选框状态
                for frame_sel in [
                    'iframe[src*="recaptcha"]',
                    'iframe[title*="reCAPTCHA"]',
                ]:
                    try:
                        frame = self.page.frame_locator(frame_sel)
                        checked = frame.locator(
                            '.recaptcha-checkbox[aria-checked="true"],'
                            '#recaptcha-anchor[aria-checked="true"]'
                        )
                        if checked.is_visible(timeout=1000):
                            logger.success("reCAPTCHA 验证已通过!")
                            self.page.screenshot(
                                path="screenshots/03_captcha_done.png"
                            )
                            self._minimize_window()
                            self._random_delay(1, 2)
                            return
                    except Exception:
                        continue

                # 方法2: 检查 textarea#g-recaptcha-response 是否有值
                try:
                    resp = self.page.locator(
                        'textarea#g-recaptcha-response'
                    ).first
                    val = resp.evaluate('el => el.value')
                    if val and len(val) > 10:
                        logger.success("reCAPTCHA 验证已通过 (response detected)!")
                        self.page.screenshot(
                            path="screenshots/03_captcha_done.png"
                        )
                        self._minimize_window()
                        self._random_delay(1, 2)
                        return
                except Exception:
                    pass

            except Exception:
                pass
            time.sleep(2)

        raise TimeoutError("等待 reCAPTCHA 验证超时 (5分钟)")

    def _click_continue(self):
        """点击 Continue with email 按钮"""
        submit_selectors = [
            'button:has-text("Continue with email")',
            'button:has-text("Continue")',
            'button[type="submit"]',
        ]
        for selector in submit_selectors:
            try:
                loc = self.page.locator(selector).first
                if loc.is_visible(timeout=3000):
                    loc.click()
                    logger.info(f"已点击: {selector}")
                    self._random_delay(3, 5)
                    self.page.screenshot(path="screenshots/04_after_continue.png")
                    return True
            except Exception:
                continue

        logger.error("未找到 Continue 按钮")
        raise RuntimeError("找不到 Continue with email 按钮")

    def _handle_verification(self, temp_email: TempEmail):
        """处理邮箱验证（sign-in link）"""
        # 确认已到达 "Check your email" 页面
        try:
            check_text = self.page.locator('text="Check your email"')
            if check_text.is_visible(timeout=5000):
                logger.info("已到达 Check your email 页面")
        except Exception:
            logger.info("正在等待验证邮件...")

        self.page.screenshot(path="screenshots/05_check_email.png")

        # 从临时邮箱获取 sign-in link
        logger.info("等待 Cerebras sign-in link 邮件...")
        verification_info = temp_email.wait_for_verification_email()

        if verification_info.startswith("http"):
            logger.info(f"获取到 sign-in link，正在打开...")
            self.page.goto(verification_info, wait_until="domcontentloaded")
            self._random_delay(3, 5)
            self.page.screenshot(path="screenshots/06_after_signin.png")
            logger.info(f"验证后 URL: {self.page.url}")

            # 检查是否有 "Complete Sign-in" 页面，需要点 Continue
            try:
                complete_text = self.page.locator(
                    'text="Complete Sign-in"'
                )
                if complete_text.is_visible(timeout=5000):
                    logger.info("检测到 Complete Sign-in 页面")
                    continue_btn = self.page.locator(
                        'button:has-text("Continue")'
                    ).first
                    if continue_btn.is_visible(timeout=3000):
                        continue_btn.click()
                        logger.info("已点击 Continue 完成登录")
                        self._random_delay(5, 8)
                        self.page.screenshot(
                            path="screenshots/07_signed_in.png"
                        )
                        logger.info(f"登录后 URL: {self.page.url}")
            except Exception as e:
                logger.debug(f"未检测到 Complete Sign-in: {e}")

            # 检查是否有 profile 设置页面（首次注册可能需要填写）
            self._handle_profile_setup()
        else:
            logger.warning(f"未获取到链接，收到: {verification_info[:100]}")

    def _handle_profile_setup(self):
        """处理 onboarding 页面（填名字 + 选 Hobbyist + Continue）"""
        self._random_delay(2, 3)

        # 检查是否在 onboarding 页面（排除 onboarding=false）
        is_onboarding = (
            "/onboarding" in self.page.url
            and "onboarding=false" not in self.page.url
        )
        if not is_onboarding:
            try:
                title = self.page.locator('text="Enter Details"')
                is_onboarding = title.is_visible(timeout=5000)
            except Exception:
                pass

        if not is_onboarding:
            logger.info("无需填写 onboarding，直接进入面板")
            return

        logger.info(f"检测到 onboarding 页面: {self.page.url}")

        # 填写 Full Name
        user_info = generate_random_user()
        for sel in [
            'input[placeholder*="John" i]',
            'input[placeholder*="name" i]',
            'input[type="text"]',
        ]:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=2000):
                    loc.click()
                    loc.fill("")
                    self._random_delay(0.3, 0.5)
                    loc.type(user_info["full_name"], delay=80)
                    logger.info(f"已填写 Full Name: {user_info['full_name']}")
                    break
            except Exception:
                continue

        self._random_delay(0.5, 1)

        # 选择 Hobbyist
        for el in self.page.locator('div, label, span').all():
            try:
                text = el.text_content() or ""
                if text.strip() == "Hobbyist":
                    el.click(force=True)
                    logger.info("已选择 Use Case: Hobbyist")
                    break
            except Exception:
                continue

        self._random_delay(1, 2)
        url_before = self.page.url

        # 点击 Continue → 直接进入 Plan 选择页面
        try:
            btn = self.page.locator('button:has-text("Continue")').first
            if btn.is_visible(timeout=3000):
                btn.click()
                logger.info("已点击 Continue")
                self._random_delay(3, 5)
                logger.info(f"进入 Plan 页面: {self.page.url}")
        except Exception as e:
            logger.warning(f"点击 Continue 失败: {e}")

        # Plan 页面：先试 Skip，再试 Free Get Started
        if not self._click_skip():
            self._click_free_plan()
        # 等待页面跳转
        self._random_delay(1, 2)

    def _click_skip(self):
        """点击页面上的 Skip 按钮"""
        url_before = self.page.url
        skip_selectors = [
            'button:has-text("Skip")',
            'a:has-text("Skip")',
            'text="Skip"',
        ]
        for sel in skip_selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=3000):
                    loc.click()
                    logger.info(f"已点击 Skip 跳过")
                    # 等待页面跳转
                    for _ in range(10):
                        self._random_delay(1, 2)
                        if self.page.url != url_before:
                            break
                    logger.info(f"Skip 后 URL: {self.page.url}")
                    return True
            except Exception:
                continue
        logger.debug("未找到 Skip 按钮")
        return False

    def _click_free_plan(self):
        """点击 Free plan 的 Get Started 按钮"""
        try:
            btns = self.page.locator(
                'button:has-text("Get Started")'
            ).all()
            if btns:
                url_before = self.page.url
                btns[0].click()
                logger.info("已点击 Free Plan 的 Get Started")
                for _ in range(15):
                    self._random_delay(1, 2)
                    if self.page.url != url_before:
                        break
                logger.info(f"Plan 后 URL: {self.page.url}")
        except Exception as e:
            logger.debug(f"点击 Free Plan 失败: {e}")

    def _extract_api_key(self) -> str:
        """从 platform 主页获取 API Key"""
        self._random_delay(1, 2)

        # 导航到 platform 主页（会自动重定向到 Get Started 页面）
        logger.info("正在导航到 platform 主页获取 API Key...")
        self.page.goto(
            "https://cloud.cerebras.ai/platform/",
            wait_until="domcontentloaded",
        )
        self._random_delay(1, 2)
        logger.info(f"platform 主页 URL: {self.page.url}")

        # 仅当URL含 /onboarding 且非 onboarding=false 时才触发
        if "/onboarding" in self.page.url and "onboarding=false" not in self.page.url:
            logger.info("被重定向到 onboarding，重新处理...")
            self._handle_profile_setup()
            # 重新导航到 platform
            self.page.goto(
                "https://cloud.cerebras.ai/platform/",
                wait_until="domcontentloaded",
            )
            self._random_delay(5, 8)
            logger.info(f"重新导航后 URL: {self.page.url}")

        self.page.screenshot(path="screenshots/10_platform_home.png")

        # 方法1: 直接从页面 HTML 中提取 csk- 开头的完整 Key
        page_content = self.page.content()
        key_match = re.search(r'(csk-[a-zA-Z0-9]{32,})', page_content)
        if key_match:
            api_key = key_match.group(1)
            logger.success(f"从页面直接获取到 API Key: {api_key[:20]}...")
            return api_key

        # 方法2: 点击 COPY API KEY 按钮，直接读剪贴板
        copy_selectors = [
            'button:has-text("COPY API KEY")',
            'button:has-text("Copy API Key")',
            'button:has-text("Copy")',
        ]
        for sel in copy_selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=5000):
                    loc.click()
                    logger.info(f"已点击: {sel}")
                    self._random_delay(1, 2)

                    # 方式A: clipboard API 读取
                    try:
                        clip = self.page.evaluate(
                            "() => navigator.clipboard.readText()"
                        )
                        if clip and clip.startswith("csk-") and len(clip) > 30:
                            logger.success(
                                f"从剪贴板获取完整 API Key: "
                                f"{clip[:20]}..."
                            )
                            return clip
                        logger.debug(f"clipboard API 返回: {clip}")
                    except Exception as e:
                        logger.debug(f"clipboard API 失败: {e}")

                    # 方式B: 创建隐藏输入框 + Ctrl+V 粘贴
                    try:
                        self.page.evaluate("""() => {
                            const ta = document.createElement('textarea');
                            ta.id = '__paste_area__';
                            ta.style.position = 'fixed';
                            ta.style.left = '-9999px';
                            document.body.appendChild(ta);
                            ta.focus();
                        }""")
                        self.page.keyboard.press("Control+v")
                        self._random_delay(0.5, 1)
                        pasted = self.page.evaluate(
                            "document.getElementById("
                            "'__paste_area__').value"
                        )
                        if pasted and pasted.startswith("csk-") and len(pasted) > 30:
                            logger.success(
                                f"从粘贴获取完整 API Key: "
                                f"{pasted[:20]}..."
                            )
                            return pasted
                        logger.debug(f"粘贴内容: {pasted}")
                    except Exception as e:
                        logger.debug(f"粘贴方式失败: {e}")
                    break
            except Exception:
                continue

        # 方法3: 尝试从页面 JS 状态中提取
        try:
            key_from_js = self.page.evaluate("""() => {
                // 查找所有包含 csk- 的文本节点
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                );
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent;
                    const match = text.match(/csk-[a-zA-Z0-9]{32,}/);
                    if (match) return match[0];
                }
                // 查找 __NEXT_DATA__ 中的 key
                const nd = document.getElementById('__NEXT_DATA__');
                if (nd) {
                    const match = nd.textContent.match(
                        /csk-[a-zA-Z0-9]{32,}/
                    );
                    if (match) return match[0];
                }
                return null;
            }""")
            if key_from_js:
                logger.success(
                    f"从页面 JS 获取 API Key: {key_from_js[:20]}..."
                )
                return key_from_js
        except Exception:
            pass

        logger.warning("未能自动提取完整 API Key，请查看截图手动获取")
        return ""

    def register_one(self) -> dict:
        """执行一次完整的注册流程

        流程: 访问页面 → 填邮箱 → 人工过验证码 → Continue → 邮箱验证 → 获取API Key

        Returns:
            包含注册结果的字典 {email, api_key, status}
        """
        user_info = generate_random_user()
        result = {
            "email": "",
            "api_key": "",
            "user_info": user_info,
            "status": "failed",
        }

        try:
            # 1. 创建临时邮箱
            self.temp_email = TempEmail()
            email = self.temp_email.create_account()
            result["email"] = email

            # 2. 创建新的浏览器上下文
            self._create_context()

            # 3. 导航到注册页面
            self._navigate_to_signup()

            # 4. 循环处理注册页（可能多次重定向回来）
            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                logger.info(f"--- 注册尝试 第{attempt}次 ---")
                logger.info(f"当前 URL: {self.page.url}")

                # 填邮箱
                self._fill_email(email)

                # 检测并等待 reCAPTCHA
                self._wait_for_captcha()

                # reCAPTCHA 通过后，确认邮箱还在（解验证码期间可能被清空）
                self._ensure_email_filled(email)

                # 点击 Continue with email
                self._click_continue()

                # 等待页面响应（不用 networkidle，会卡住）
                self._random_delay(5, 8)
                try:
                    self.page.wait_for_load_state(
                        "domcontentloaded", timeout=10000
                    )
                except Exception:
                    pass

                current_url = self.page.url
                logger.info(f"点击后 URL: {current_url}")

                # 直接检测是否到达 "Check your email" 页面
                try:
                    check_email = self.page.locator(
                        'text="Check your email"'
                    )
                    if check_email.is_visible(timeout=3000):
                        logger.success(
                            "已到达 Check your email 页面!"
                        )
                        break
                except Exception:
                    pass

                # 否则检查是否还在注册页
                still_on_signup = False
                try:
                    email_input = self.page.locator(
                        'input[name="email"], input[type="email"]'
                    ).first
                    if email_input.is_visible(timeout=3000):
                        still_on_signup = True
                except Exception:
                    pass

                if not still_on_signup:
                    logger.success("已离开注册页，进入下一步!")
                    break
                else:
                    logger.warning("仍在注册页，将重新填写...")
            else:
                raise RuntimeError(f"注册页循环 {max_attempts} 次仍未通过")

            # 5. 处理邮箱验证
            logger.info("开始检查临时邮箱中的 sign-in link...")
            self._handle_verification(self.temp_email)

            # 10. 尝试获取 API Key
            api_key = self._extract_api_key()
            result["api_key"] = api_key

            result["status"] = "success"
            logger.success(f"注册成功: {email}")

        except Exception as e:
            logger.error(f"注册失败: {e}")
            result["status"] = f"failed: {e}"
            try:
                self.page.screenshot(path="screenshots/error.png")
            except Exception:
                pass
        finally:
            if self.temp_email:
                self.temp_email.close()
            # 关闭上下文并清理临时目录
            self._close_context()

        return result

    def close(self):
        """关闭浏览器"""
        self._close_context()
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        logger.info("浏览器已关闭")

    def __enter__(self):
        self.start_browser()
        return self

    def __exit__(self, *args):
        self.close()
