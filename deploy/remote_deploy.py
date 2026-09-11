"""远程部署脚本 - 通过 SSH/SFTP 将项目部署到 Linux 服务器

用法（PowerShell，密码与 IP 通过环境变量传入，不写入任何文件）：
    $env:DEPLOY_HOST='<服务器IP>'
    $env:DEPLOY_PW='<服务器密码>'
    python deploy/remote_deploy.py

可选环境变量：
    DEPLOY_HOST  服务器 IP（必填，不设默认值）
    DEPLOY_USER  SSH 用户（默认 root）
    DEPLOY_DIR   远程目标目录（默认 /root/ai）
    DEPLOY_PW    SSH 密码（必填）
"""
import os
import sys

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "")
USER = os.environ.get("DEPLOY_USER", "root")
PW = os.environ.get("DEPLOY_PW")
HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.normpath(os.path.join(HERE, "..", "deploy_bundle.tar.gz"))
REMOTE_DIR = os.environ.get("DEPLOY_DIR", "/root/ai")

if not HOST:
    sys.exit("缺少环境变量 DEPLOY_HOST（服务器 IP，出于安全不写入代码）")


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 300) -> tuple[int, str, str]:
    """执行远程命令并实时回显输出"""
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out)
    if err:
        print("[stderr]", err)
    print(f"[exit {code}]")
    return code, out, err


def main() -> None:
    if not PW:
        sys.exit("缺少环境变量 DEPLOY_PW（SSH 密码）")
    if not os.path.exists(BUNDLE):
        sys.exit(f"找不到部署包: {BUNDLE}，请先执行 tar 打包")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"连接 {USER}@{HOST} ...")
    ssh.connect(HOST, port=22, username=USER, password=PW, timeout=20)

    # 0. 环境确认：发行版 / 内存 / 磁盘
    run(ssh, "head -3 /etc/os-release; free -h; df -h / | tail -1")

    # 1. 创建目标目录
    run(ssh, f"mkdir -p {REMOTE_DIR}")

    # 2. 上传部署包
    size_mb = os.path.getsize(BUNDLE) / 1024 / 1024
    print(f"\n上传 {BUNDLE} ({size_mb:.1f} MB) -> {REMOTE_DIR}/bundle.tar.gz")
    sftp = ssh.open_sftp()
    sftp.put(BUNDLE, f"{REMOTE_DIR}/bundle.tar.gz")
    sftp.close()
    print("上传完成")

    # 3. 解压
    code, _, _ = run(ssh, f"cd {REMOTE_DIR} && tar xzf bundle.tar.gz && ls -la")
    if code != 0:
        sys.exit("解压失败")

    # 4. 执行一键安装（系统依赖 + 字体 + venv + pip + systemd，耗时较长）
    code, _, _ = run(ssh, f"cd {REMOTE_DIR} && bash deploy/install.sh 2>&1", timeout=2400)
    if code != 0:
        sys.exit("install.sh 执行失败，请检查上方日志")

    # 5. 部署验证
    run(ssh, "systemctl is-active learn-agent-api learn-agent-web")
    run(ssh, "sleep 2; curl -s -m 5 http://127.0.0.1:8000/api/health")
    run(ssh, "free -h")

    ssh.close()
    print("\n==== 部署流程结束 ====")


if __name__ == "__main__":
    main()
