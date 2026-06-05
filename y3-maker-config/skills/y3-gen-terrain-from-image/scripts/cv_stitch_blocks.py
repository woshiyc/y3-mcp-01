# scripts/cv_stitch_blocks.py
"""
将 16 张分块装饰图（decoration_block_{row}_{col}.png）拼合为完整的 decoration_design.png。

命名规则：decoration_block_{row}_{col}.png，row/col 各为 0~grid_size-1。
拼合后使用最近邻插值缩放到目标尺寸，保护精确 RGB 颜色（防止插值偏移导致 CV 识别失败）。
"""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow 未安装，请运行 pip install Pillow", file=sys.stderr)
    sys.exit(1)


def split_gray_context(input_path: str, output_dir: str, grid_size: int) -> None:
    """将灰度上下文图切分为 grid_size×grid_size 块，供用户作为装饰图生成参考底图。"""
    img = Image.open(input_path)
    w, h = img.size
    bw, bh = w // grid_size, h // grid_size

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for row in range(grid_size):
        for col in range(grid_size):
            x0, y0 = col * bw, row * bh
            block = img.crop((x0, y0, x0 + bw, y0 + bh))
            block.save(str(out / f"gray_block_{row}_{col}.png"))

    print(f"灰度底图已切分为 {grid_size}×{grid_size}={grid_size**2} 块 → {output_dir}")
    print(f"  每块尺寸：{bw}×{bh} px")


def validate_blocks(input_dir: str, grid_size: int, block_size: int) -> list:
    """验证所有块图片存在且尺寸正确，返回缺失/错误列表。"""
    errors = []
    for row in range(grid_size):
        for col in range(grid_size):
            path = Path(input_dir) / f"decoration_block_{row}_{col}.png"
            if not path.exists():
                errors.append(f"缺失：decoration_block_{row}_{col}.png")
                continue
            try:
                img = Image.open(str(path))
                w, h = img.size
                if w != block_size or h != block_size:
                    errors.append(
                        f"尺寸错误：decoration_block_{row}_{col}.png 期望 {block_size}×{block_size}，实际 {w}×{h}"
                    )
            except Exception as e:
                errors.append(f"无法读取：decoration_block_{row}_{col}.png — {e}")
    return errors


def stitch_blocks(input_dir: str, output_path: str,
                  grid_size: int, block_size: int, output_size: int) -> None:
    """拼合 grid_size×grid_size 块图片，缩放到 output_size×output_size 后保存。"""
    # 验证
    errors = validate_blocks(input_dir, grid_size, block_size)
    if errors:
        print("ERROR: 块验证失败，请补充以下文件后重跑：", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(1)

    canvas_size = grid_size * block_size
    canvas = Image.new("RGB", (canvas_size, canvas_size))

    for row in range(grid_size):
        for col in range(grid_size):
            path = Path(input_dir) / f"decoration_block_{row}_{col}.png"
            block = Image.open(str(path)).convert("RGB")
            canvas.paste(block, (col * block_size, row * block_size))

    if canvas_size != output_size:
        canvas = canvas.resize((output_size, output_size), Image.NEAREST)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)

    print(f"✅ 拼合完成：{grid_size}×{grid_size} 块 × {block_size}px → {output_size}×{output_size}px")
    print(f"   输出：{output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="装饰图分块拼合工具 / 灰度底图切分工具"
    )
    subparsers = parser.add_subparsers(dest="cmd")

    # 子命令：拼合（默认用途）
    stitch_p = subparsers.add_parser("stitch", help="拼合16块装饰图为完整图（默认）")
    stitch_p.add_argument("--input-dir",   required=True, help="16张块图片所在目录")
    stitch_p.add_argument("--output",      required=True, help="输出路径（decoration_design.png）")
    stitch_p.add_argument("--grid-size",   type=int, default=4,    help="格数（默认4，即4×4=16块）")
    stitch_p.add_argument("--block-size",  type=int, default=1024, help="每块像素尺寸（默认1024）")
    stitch_p.add_argument("--output-size", type=int, default=2048, help="最终输出尺寸（默认2048）")

    # 子命令：切分灰度底图
    split_p = subparsers.add_parser("split", help="切分灰度上下文图为参考底图")
    split_p.add_argument("--input",      required=True, help="gray_context.png 路径")
    split_p.add_argument("--output-dir", required=True, help="输出目录（存放 gray_block_*_*.png）")
    split_p.add_argument("--grid-size",  type=int, default=4, help="格数（默认4）")

    # 兼容旧式无子命令调用（直接传 --input-dir 等参数）
    parser.add_argument("--input-dir",   help="[stitch] 16张块图片所在目录")
    parser.add_argument("--output",      help="[stitch] 输出路径")
    parser.add_argument("--grid-size",   type=int, default=4)
    parser.add_argument("--block-size",  type=int, default=1024)
    parser.add_argument("--output-size", type=int, default=2048)

    args = parser.parse_args()

    if args.cmd == "split":
        split_gray_context(args.input, args.output_dir, args.grid_size)
    elif args.cmd == "stitch" or (args.cmd is None and args.input_dir):
        stitch_blocks(
            args.input_dir, args.output,
            args.grid_size, args.block_size, args.output_size
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
