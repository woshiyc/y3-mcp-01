#!/usr/bin/env python3
"""检查并自动安装依赖（仅 numpy，其余均为标准库）。"""
import sys
import json
import subprocess

REQUIRED = {"numpy": "numpy"}

missing = []
for pkg, import_name in REQUIRED.items():
    try:
        __import__(import_name)
    except ImportError:
        missing.append(pkg)

install_failed = []
for pkg in missing:
    print(f"[check_deps] 安装 {pkg}...", flush=True)
    ret = subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"],
                         capture_output=True)
    if ret.returncode != 0:
        install_failed.append(pkg)

if install_failed:
    print(json.dumps({"status": "missing", "install_failed": install_failed}))
    sys.exit(1)
else:
    print(json.dumps({"status": "ok", "installed": missing}))
