#!/usr/bin/env python3
"""
Y3 Terrain Evolution - Preview Server

轻量 HTTP 服务（端口 9876），供 visual_eval.py 截图并供前端 Three.js 预览读取数据。

端点：
  GET  /world_state     -> output/world_state.json
  GET  /ecology         -> output/ecology_layer.json
  GET  /civilization    -> output/civilization_layer.json
  GET  /last_screenshot -> {"image_b64": "<base64 png>"} 或 {"image_b64": null}
  POST /screenshot      -> body: {"image_b64": "<base64 png>"}，存入内存

用法：
  python preview_server.py --output-dir output/
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


# ---------------------------------------------------------------------------
# 请求处理器
# ---------------------------------------------------------------------------

class TerrainHandler(BaseHTTPRequestHandler):
    _last_screenshot_b64: str | None = None
    _last_screenshot_lock = threading.Lock()

    # output_dir 由主程序在启动前注入
    output_dir: str = "output"

    def log_message(self, fmt, *args):  # 静默日志，避免刷屏
        pass

    # ---- GET ----------------------------------------------------------------

    def do_GET(self):
        if self.path == "/world_state":
            self._serve_json("world_state.json")
        elif self.path == "/ecology":
            self._serve_json("ecology_layer.json")
        elif self.path == "/civilization":
            self._serve_json("civilization_layer.json")
        elif self.path == "/last_screenshot":
            with TerrainHandler._last_screenshot_lock:
                b64 = TerrainHandler._last_screenshot_b64
            self._send_json({"image_b64": b64})
        else:
            self._send_error(404, "Not Found")

    def _serve_json(self, filename):
        p = Path(TerrainHandler.output_dir) / filename
        if not p.exists():
            self._send_error(404, f"{filename} not found")
            return
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    # ---- POST ---------------------------------------------------------------

    def do_POST(self):
        if self.path == "/screenshot":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                b64 = payload.get("image_b64", "")
                with TerrainHandler._last_screenshot_lock:
                    TerrainHandler._last_screenshot_b64 = b64
                self._send_json({"status": "ok"})
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                self._send_error(400, f"Bad JSON: {e}")
        else:
            self._send_error(404, "Not Found")

    # ---- helpers ------------------------------------------------------------

    def _send_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, code, msg):
        data = json.dumps({"error": msg}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

def run(output_dir: str = "output", port: int = 9876, bind: str = "127.0.0.1"):
    TerrainHandler.output_dir = output_dir
    server = HTTPServer((bind, port), TerrainHandler)
    print(f"[preview_server] 监听 http://{bind}:{port}  output_dir={output_dir}")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--port",       type=int, default=9876)
    parser.add_argument("--bind",       default="127.0.0.1")
    args = parser.parse_args()
    run(args.output_dir, args.port, args.bind)


if __name__ == "__main__":
    main()
