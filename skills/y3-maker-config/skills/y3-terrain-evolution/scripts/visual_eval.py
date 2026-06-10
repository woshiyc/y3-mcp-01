#!/usr/bin/env python3
"""
Y3 Terrain Evolution - Visual Evaluator (生态纪专用)

调用 preview_server GET /last_screenshot 获取截图（base64 PNG），
然后通过 Anthropic API（claude-sonnet-4-6）对截图进行视觉评分，
生成 visual_eval_ecology.json。

仅在生态纪（ecology era）视觉迭代阶段调用，最多 max_visual_iterations 次。

用法：
  python visual_eval.py \\
    --preview-url http://127.0.0.1:9876 \\
    --output output/visual_eval_ecology.json \\
    --iteration 1 \\
    --max-iterations 3
"""

import argparse
import base64
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path


# ---------------------------------------------------------------------------
# Claude API 调用（anthropic SDK）
# ---------------------------------------------------------------------------

def _call_claude_vision(image_b64: str, prompt: str, model: str, api_key: str) -> str:
    """调用 Anthropic Messages API，传入 base64 PNG 截图，返回模型文本输出。"""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": "image/png",
                        "data":       image_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# 截图获取
# ---------------------------------------------------------------------------

def fetch_screenshot(preview_url: str) -> str | None:
    """GET /last_screenshot，返回 base64 字符串或 None。"""
    url = preview_url.rstrip("/") + "/last_screenshot"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("image_b64")
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 评估结果解析
# ---------------------------------------------------------------------------

def _parse_score(text: str) -> dict:
    """
    从 LLM 文本中提取 JSON 评分块。
    LLM 应返回类似：
      {"score": 72, "issues": ["..."], "suggestions": ["..."]}
    若无法解析则返回原始文本。
    """
    import re
    m = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"raw": text, "score": 0}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

VISUAL_PROMPT = """\
你是一名 Y3 游戏地图美术评审。请对这张地图截图进行视觉质量评估，关注生态层表现：
1. 植被分布是否自然（森林、灌木、草地密度合理）
2. 水体边缘是否有自然过渡（湿地、浅水、芦苇）
3. 地形与生态是否协调（山地→针叶林，平原→草甸）
4. 整体视觉丰富度

请以 JSON 格式返回评分（0-100）和主要问题：
{"score": <int>, "issues": ["<issue1>", ...], "suggestions": ["<suggestion1>", ...]}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview-url",    default="http://127.0.0.1:9876")
    parser.add_argument("--output",         required=True)
    parser.add_argument("--iteration",      type=int, default=1)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--model",          default="claude-sonnet-4-6")
    parser.add_argument("--api-key",        default=None,
                        help="Anthropic API key（优先使用环境变量 ANTHROPIC_API_KEY）")
    args = parser.parse_args()

    import os
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[visual_eval] 错误: 未设置 ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    if args.iteration > args.max_iterations:
        print(f"[visual_eval] 已达最大视觉迭代次数 {args.max_iterations}，跳过")
        result = {"status": "skipped", "reason": "max_iterations_reached",
                  "iteration": args.iteration, "max_iterations": args.max_iterations}
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        return

    print(f"[visual_eval] 获取截图（{args.preview_url}）...")
    image_b64 = fetch_screenshot(args.preview_url)
    if not image_b64:
        print("[visual_eval] 错误: 未获取到截图，请先通过 POST /screenshot 上传", file=sys.stderr)
        sys.exit(1)

    print(f"[visual_eval] 调用 {args.model} 进行视觉评分...")
    raw_text = _call_claude_vision(image_b64, VISUAL_PROMPT, args.model, api_key)
    eval_data = _parse_score(raw_text)

    result = {
        "status":         "ok",
        "iteration":      args.iteration,
        "max_iterations": args.max_iterations,
        "score":          eval_data.get("score", 0),
        "issues":         eval_data.get("issues", []),
        "suggestions":    eval_data.get("suggestions", []),
        "raw":            raw_text,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"[visual_eval] 评分: {result['score']} → {args.output}")


if __name__ == "__main__":
    main()
