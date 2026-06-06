#!/usr/bin/env python3
"""Verify PR #94 state after push and thread resolution."""
import subprocess
import json
import urllib.request

result = subprocess.run(
    ["op", "read", "op://Private/Github/Personal Access Token"],
    capture_output=True, text=True
)
token = result.stdout.strip()

query = """
query {
  repository(owner: "davidasnider", name: "file-catalog") {
    pullRequest(number: 94) {
      state
      headRefName
      commits(last: 1) {
        nodes {
          commit {
            oid
            messageHeadline
          }
        }
      }
      reviewThreads(first: 10) {
        nodes {
          id
          isResolved
        }
      }
    }
  }
}
"""
headers = {
    "Authorization": "Bearer " + token,
    "Content-Type": "application/json",
    "User-Agent": "hermes"
}
req = urllib.request.Request(
    "https://api.github.com/graphql",
    data=json.dumps({"query": query}).encode(),
    headers=headers
)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    pr = data["data"]["repository"]["pullRequest"]
    print(f"PR state: {pr['state']}")
    print(f"Branch: {pr['headRefName']}")
    last = pr["commits"]["nodes"][0]["commit"]
    print(f"Last commit: {last['oid'][:7]} - {last['messageHeadline']}")
    threads = pr["reviewThreads"]["nodes"]
    print(f"Review threads: {len(threads)}")
    for t in threads:
        print(f"  {t['id']}: resolved={t['isResolved']}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:300]}")
