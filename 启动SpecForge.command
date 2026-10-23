#!/bin/bash
# 双击启动 SpecForge：启动后台服务并自动打开浏览器。关闭这个终端窗口即停止服务。
cd "$(dirname "$0")"
[ -f frontend/dist/index.html ] || (cd frontend && npm install && npm run build)
[ -f examples/sdtm/spec_final.xlsx ] || python3 examples/make_examples.py
(sleep 3 && open "http://127.0.0.1:8000") &
python3 -m uvicorn specforge.api.app:app --app-dir backend --port 8000
