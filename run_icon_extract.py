import subprocess, sys

r = subprocess.run(
    sys.executable + ' "E:/pycode/y3-map/y3-maker-config/skills/y3-gen-terrain-from-image/scripts/cv_icon_extract.py"'
    ' --deco-dir "E:/pycode/y3-map/y3-maker-config/skills/y3-gen-terrain-from-image/output/09/source_blocks_2x2"'
    ' --source-dir "E:/pycode/y3-map/y3-maker-config/skills/y3-gen-terrain-from-image/output/09/source_blocks_2x2"'
    ' --output-dir "E:/pycode/y3-map/y3-maker-config/skills/y3-gen-terrain-from-image/output/09"'
    ' --grid-cols 2 --grid-rows 2 --map-w 256 --map-h 256',
    shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace'
)
print(r.stdout)
if r.stderr: print('ERR:', r.stderr[:1000])
print('EXIT:', r.returncode)
