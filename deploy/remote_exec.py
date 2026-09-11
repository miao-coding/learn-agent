"""远程命令执行小工具 - 部署后的运维辅助

用法（PowerShell）：
    $env:DEPLOY_HOST='<服务器IP>'
    $env:DEPLOY_PW='<服务器密码>'
    python deploy/remote_exec.py "systemctl is-active learn-agent-api" "free -h"

可选环境变量：DEPLOY_HOST / DEPLOY_USER / DEPLOY_PW（必填）
"""
import os
import sys

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "")
USER = os.environ.get("DEPLOY_USER", "root")
PW = os.environ.get("DEPLOY_PW")

if not HOST:
    sys.exit("缺少环境变量 DEPLOY_HOST（服务器 IP，出于安全不写入代码）")

if not PW:
    sys.exit("缺少环境变量 DEPLOY_PW（SSH 密码）")
if len(sys.argv) < 2:
    sys.exit("用法: python deploy/remote_exec.py <命令1> [命令2] ...")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, port=22, username=USER, password=PW, timeout=20)

for cmd in sys.argv[1:]:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    print(f"$ {cmd}")
    if out:
        print(out)
    if err:
        print("[stderr]", err)

ssh.close()
