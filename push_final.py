#!/usr/bin/env python3
"""Push commit using GitHub token."""
import subprocess
import os

# Get token from 1Password
result = subprocess.run(
    ["op", "read", "op://Private/Github/Personal Access Token"],
    capture_output=True, text=True
)
token = result.stdout.strip()
print(f"Token len={len(token)}, prefix={token[:15]}...")

os.chdir("/tmp/hermes-pr/file-catalog-94")

# Method 1: Use token as username in URL
auth_url = f"https://x-access-token:{token}@github.com/davidasnider/file-catalog.git"

# Save original remote
orig = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
original_url = orig.stdout.strip()

# Set remote with token
subprocess.run(["git", "remote", "set-url", "origin", auth_url], check=True)

# Push
print("Pushing...")
push_result = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
print(f"stdout: {push_result.stdout}")
print(f"stderr: {push_result.stderr}")
print(f"exit: {push_result.returncode}")

# Restore original remote
subprocess.run(["git", "remote", "set-url", "origin", original_url], check=True)

if push_result.returncode == 0:
    print("SUCCESS: pushed!")
else:
    # Try alternative: git credential helper
    print("Direct URL failed, trying credential helper...")
    subprocess.run(["git", "config", "--global", "credential.helper", "cache"], check=True)
    
    # Use git credential fill
    import sys
    cred_input = f"protocol=https\nhost=github.com\nusername=x-access-token\npassword={token}\n\n"
    
    # Actually, let's try git -c approach
    push2 = subprocess.run(
        ["git", "-c", f"http.extraHeader=Authorization: Bearer {token}", "push", "origin", "HEAD"],
        capture_output=True, text=True
    )
    print(f"Method 2 stdout: {push2.stdout}")
    print(f"Method 2 stderr: {push2.stderr}")
    print(f"Method 2 exit: {push2.returncode}")
