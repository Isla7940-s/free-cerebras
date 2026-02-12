"""临时邮箱模块 - 使用 mail.tm API"""

import re
import time
import html
import httpx
from loguru import logger
from config import TEMP_MAIL_API, EMAIL_WAIT_TIMEOUT


class TempEmail:
    """mail.tm 临时邮箱客户端"""

    def __init__(self):
        self.client = httpx.Client(timeout=30)
        self.email = None
        self.password = None
        self.token = None
        self.account_id = None

    def _get_available_domain(self) -> str:
        """获取可用的邮箱域名"""
        resp = self.client.get(f"{TEMP_MAIL_API}/domains")
        resp.raise_for_status()
        data = resp.json()
        domains = data.get("hydra:member", data) if isinstance(data, dict) else data
        if not domains:
            raise RuntimeError("没有可用的临时邮箱域名")
        domain = domains[0]["domain"]
        logger.info(f"使用邮箱域名: {domain}")
        return domain

    def create_account(self, username: str = None, max_retries: int = 3) -> str:
        """创建临时邮箱账户，返回邮箱地址（带重试）"""
        import random
        domain = self._get_available_domain()

        for attempt in range(max_retries):
            if username is None or attempt > 0:
                username = f"user{int(time.time() * 1000)}"
            self.email = f"{username}@{domain}"
            self.password = f"Pass{int(time.time())}!Xx"

            try:
                resp = self.client.post(
                    f"{TEMP_MAIL_API}/accounts",
                    json={"address": self.email, "password": self.password},
                )
                if resp.status_code == 201:
                    data = resp.json()
                    self.account_id = data["id"]
                    logger.success(f"临时邮箱创建成功: {self.email}")
                    self._login()
                    return self.email
                else:
                    logger.warning(
                        f"创建邮箱失败 (第{attempt+1}次): "
                        f"{resp.status_code}"
                    )
            except Exception as e:
                logger.warning(f"创建邮箱异常 (第{attempt+1}次): {e}")

            if attempt < max_retries - 1:
                delay = random.uniform(2, 5)
                logger.info(f"等待 {delay:.1f}s 后重试...")
                time.sleep(delay)

        raise RuntimeError("创建临时邮箱失败，已重试3次")

    def _login(self):
        """登录获取 token"""
        resp = self.client.post(
            f"{TEMP_MAIL_API}/token",
            json={"address": self.email, "password": self.password},
        )
        resp.raise_for_status()
        self.token = resp.json()["token"]
        logger.debug("邮箱登录成功，获取到 token")

    def wait_for_verification_email(
        self, sender_keyword: str = "cerebras", timeout: int = None
    ) -> str:
        """等待并获取验证邮件中的验证链接或验证码

        Args:
            sender_keyword: 发件人关键词过滤
            timeout: 超时时间(秒)

        Returns:
            验证链接或验证码字符串
        """
        if timeout is None:
            timeout = EMAIL_WAIT_TIMEOUT

        headers = {"Authorization": f"Bearer {self.token}"}
        start_time = time.time()
        logger.info(f"等待验证邮件... (超时: {timeout}s)")

        while time.time() - start_time < timeout:
            try:
                resp = self.client.get(
                    f"{TEMP_MAIL_API}/messages", headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                messages = (
                    data.get("hydra:member", data)
                    if isinstance(data, dict)
                    else data
                )

                for msg in messages:
                    msg_from = str(msg.get("from", {}).get("address", "")).lower()
                    msg_subject = str(msg.get("subject", "")).lower()
                    if (
                        sender_keyword.lower() in msg_from
                        or sender_keyword.lower() in msg_subject
                    ):
                        logger.info(f"收到验证邮件: {msg.get('subject', '')}")
                        return self._extract_verification_info(msg["id"], headers)
            except Exception as e:
                logger.warning(f"检查邮件时出错: {e}")

            time.sleep(5)

        raise TimeoutError(f"等待验证邮件超时 ({timeout}s)")

    def _extract_verification_info(self, message_id: str, headers: dict) -> str:
        """从邮件内容中提取验证链接或验证码"""
        resp = self.client.get(
            f"{TEMP_MAIL_API}/messages/{message_id}", headers=headers
        )
        resp.raise_for_status()
        msg_data = resp.json()

        # 优先从 HTML 内容中提取（字段可能是 str 或 list）
        raw_html = msg_data.get("html", "") or ""
        raw_text = msg_data.get("text", "") or ""
        if isinstance(raw_html, list):
            raw_html = "\n".join(str(x) for x in raw_html)
        if isinstance(raw_text, list):
            raw_text = "\n".join(str(x) for x in raw_text)
        content = raw_html or raw_text

        # 尝试提取验证/登录链接
        url_keywords = (
            r'verify|confirm|activate|callback|token|'
            r'sign-in|signin|login|auth|magic|link'
        )
        url_patterns = [
            rf'href="(https?://[^"]*(?:{url_keywords})[^"]*)"',
            rf'(https?://[^\s<>"]+(?:{url_keywords})[^\s<>"]*)',
            # 兜底: 匹配任何 cerebras 域名的链接
            r'href="(https?://[^"]*cerebras[^"]*)"',
            r'(https?://[^\s<>"]*cerebras[^\s<>"]*)',
        ]
        for pattern in url_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                link = html.unescape(match.group(1))
                logger.success(f"提取到验证链接: {link[:80]}...")
                return link

        # 尝试提取验证码 (4-8位数字或字母数字混合)
        code_patterns = [
            r'(?:code|验证码|verification)[:\s]*([A-Za-z0-9]{4,8})',
            r'<strong>(\d{4,8})</strong>',
            r'(?:^|\s)(\d{6})(?:\s|$)',
        ]
        for pattern in code_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                code = match.group(1)
                logger.success(f"提取到验证码: {code}")
                return code

        # 返回纯文本内容供手动处理
        logger.warning("未能自动提取验证信息，返回邮件原文")
        return raw_text or content

    def close(self):
        """关闭 HTTP 客户端"""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
