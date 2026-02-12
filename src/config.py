"""配置文件"""

# Cerebras 注册页面
CEREBRAS_URL = "https://cloud.cerebras.ai/?utm_source=homepage"

# 临时邮箱 API (mail.tm)
TEMP_MAIL_API = "https://api.mail.tm"

# 注册结果输出文件
OUTPUT_FILE = "accounts.txt"

# 浏览器配置
HEADLESS = False  # 调试时设为 False 可以看到浏览器操作

# 速度模式: fast / standard / slow
SPEED_MODES = {
    "fast":     {"slow_mo": 100, "delay_mult": 0.35},
    "standard": {"slow_mo": 300, "delay_mult": 0.65},
    "slow":     {"slow_mo": 500, "delay_mult": 1.0},
}
SPEED_MODE = "standard"
SLOW_MO = SPEED_MODES[SPEED_MODE]["slow_mo"]

# 批量注册配置
BATCH_SIZE = 5  # 每批注册数量
BATCH_DELAY = 10  # 每批之间的间隔(秒)

# 超时配置(秒)
PAGE_TIMEOUT = 30
EMAIL_WAIT_TIMEOUT = 120  # 等待验证邮件的超时时间

# 随机用户信息生成
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Christopher", "Karen",
    "Daniel", "Lisa", "Matthew", "Nancy", "Anthony", "Betty", "Mark", "Helen",
    "Steven", "Sandra", "Andrew", "Donna", "Kenneth", "Carol", "Joshua", "Ruth",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
]
