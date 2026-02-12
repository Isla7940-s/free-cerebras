"""测试 Cerebras API Key 是否可用"""

import httpx
import sys

API_BASE = "https://api.cerebras.ai/v1/chat/completions"
MODEL = "qwen-3-32b"

KEYS = [
    ("csk-c26cprn5wdh6x4ycnfvdr6w2hpp848ftm9ftjfnr9fk3tmh9", "Betty Williams"),
    ("csk-tj54tccv5yrmcmdkxr3jrvm9vcxhhv6rwewhxfr4p32ct33k", "Elizabeth Young"),
    ("csk-nh32djwv9c5fvrw64yv2wex4epn22r8xpmee6ry3ehtx6wh2", "Joseph Sanchez"),
    ("csk-83yc6yf632n8nefxryn6r6vdf6566rnxfh2kv4txcpt2wxkj", "Linda Wilson"),
]

def test_key(api_key: str, name: str):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Hi, say hello in one sentence."}],
        "max_tokens": 50,
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(API_BASE, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                print(f"[OK]  {name} | key=...{api_key[-8:]} | reply: {content[:60]}")
                return True
            else:
                print(f"[FAIL] {name} | key=...{api_key[-8:]} | HTTP {resp.status_code}: {resp.text[:120]}")
                return False
    except Exception as e:
        print(f"[ERR] {name} | key=...{api_key[-8:]} | {e}")
        return False

if __name__ == "__main__":
    print(f"Testing {len(KEYS)} keys with model: {MODEL}\n")
    results = []
    for key, name in KEYS:
        ok = test_key(key, name)
        results.append((name, ok))
    
    print(f"\n{'='*50}")
    valid = sum(1 for _, ok in results if ok)
    print(f"Result: {valid}/{len(KEYS)} keys are valid")
    for name, ok in results:
        print(f"  {'OK' if ok else 'FAIL':>4}  {name}")
