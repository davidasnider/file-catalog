#!/usr/bin/env python3
"""Test GitHub token and push."""
import subprocess
import urllib.request
import json

# Get token from 1Password
result = subprocess.run(
    ["op", "read", "op://Private/GitHub Personal Access Token/token"],
    capture_output=True, text=True
)
token = result.stdout.strip()
print(f"Token: len={len(token)}, prefix={token[:15]}...")

# Test API access
for url, label in [
    ("https://api.github.com/user", "user"),
    ("https://api.github.com/repos/davidasnider/file-catalog", "repo"),
]:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "hermes",
        "Accept": "application/vnd.github+json"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"{label}: OK (login={data.get('login', data.get('full_name', '?'))})")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"{label}: HTTP {e.code} - {body[:200]}")
    except Exception as e:
        print(f"{label}: ERROR - {e}")

# Try resolving the thread via API
mutation = """
mutation {
  resolveReviewThread(input: {threadId: "PRRT_kwDORZk0is6HmOf6"}) {
    thread { isResolved }
  }
}
"""
req = urllib.request.Request(
    "https://api.github.com/graphql",
    data=json.dumps({"query": mutation}).encode(),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "hermes"
    }
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        if "errors" in data:
            print(f"Resolve thread: ERROR - {data['errors']}")
        else:
            print(f"Resolve thread: OK - {data}")
except urllib.error.HTTPError as e:
    print(f"Resolve thread: HTTP {e.code} - {e.read().decode()[:200]}")
