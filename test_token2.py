#!/usr/bin/env python3
"""Test alternate GitHub token."""
import subprocess
import urllib.request
import json

# Get token from "Github" item's "Personal Access Token" field
result = subprocess.run(
    ["op", "read", "op://Private/Github/Personal Access Token"],
    capture_output=True, text=True
)
token = result.stdout.strip()
print(f"Token: len={len(token)}, prefix={token[:15]}...")

# Test API access
req = urllib.request.Request("https://api.github.com/user", headers={
    "Authorization": f"Bearer {token}",
    "User-Agent": "hermes",
    "Accept": "application/vnd.github+json"
})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        print(f"API OK - user: {data.get('login', '?')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"API FAIL: HTTP {e.code} - {body[:200]}")
except Exception as e:
    print(f"API ERROR: {e}")

# Test GraphQL (resolve thread)
mutation = """
mutation {
  resolveReviewThread(input: {threadId: "PRRT_kwDORZk0is6HmOf6"}) {
    thread { isResolved }
  }
}
"""
req2 = urllib.request.Request(
    "https://api.github.com/graphql",
    data=json.dumps({"query": mutation}).encode(),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "hermes"
    }
)
try:
    with urllib.request.urlopen(req2, timeout=15) as resp:
        data = json.loads(resp.read())
        if "errors" in data:
            print(f"GraphQL FAIL: {data['errors']}")
        else:
            print(f"GraphQL OK: {data}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"GraphQL HTTP: {e.code} - {body[:200]}")
