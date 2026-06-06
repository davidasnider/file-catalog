#!/usr/bin/env python3
"""Push branch and resolve review thread using GitHub API."""
import subprocess
import os
import sys

# Get token from 1Password
result = subprocess.run(
    ["op", "read", "op://Private/GitHub Personal Access Token/token"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"ERROR: op read failed: {result.stderr}")
    sys.exit(1)
token = result.stdout.strip()
print(f"Got token (len={len(token)}, prefix={token[:8]}...)")

# Switch to repo
os.chdir("/tmp/hermes-pr/file-catalog-94")

# Push using git with token auth
remote_url = "https://github.com/davidasnider/file-catalog.git"
auth_url = f"https://{token}:x-oauth-basic@github.com/davidasnider/file-catalog.git"

# Update remote with token
subprocess.run(["git", "remote", "set-url", "origin", auth_url], check=True)

# Push
print("Pushing...")
push_result = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
print(f"Push stdout: {push_result.stdout}")
print(f"Push stderr: {push_result.stderr}")
print(f"Push exit: {push_result.returncode}")

# Reset remote to clean URL
subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)

if push_result.returncode != 0:
    print("Push failed!")
    sys.exit(1)

# Resolve the review thread
import urllib.request
import json

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
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "hermes-kanban-worker"
    }
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        print(f"Resolve result: {json.dumps(data, indent=2)}")
except urllib.error.HTTPError as e:
    print(f"HTTP Error resolving thread: {e.code}")
    print(e.read().decode())
    sys.exit(1)

print("DONE - pushed and resolved")
