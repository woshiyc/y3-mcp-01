import json, math, collections, os, sys

m = json.load(open('decoration_manifest.json', encoding='utf-8'))
types = collections.Counter(e['type'] for e in m['elements'])

print('=== 元素统计 ===')
for t, cnt in sorted(types.items()):
    print(f'  {t}: {cnt}')
print(f'  合计: {sum(types.values())}')

forest = [e for e in m['elements'] if 'forest' in e['type']]
total_land = 40341
total_area = sum(math.pi * e['radius']**2 for e in forest)

def avg_r(typ):
    sub = [e for e in forest if e['type']==typ]
    return (sum(e['radius'] for e in sub)/len(sub)) if sub else 0

print()
print('=== 森林覆盖估算 ===')
for ft in ['forest_sparse','forest_medium','forest_dense']:
    cnt = sum(1 for e in forest if e['type']==ft)
    if cnt:
        print(f'  {ft}: {cnt} 个区域, avg_radius={avg_r(ft):.1f} 格')
print(f'  估算总覆盖(pi*r^2累加): {total_area:.0f} 格 = {total_area/total_land*100:.1f}% 陆地')
print('  (区域有重叠，实际覆盖 < 估算值；重叠修正约 0.6~0.7x 较合理)')

for log in ['shape_warnings.log','height_warnings.log','unknown_pixels.log']:
    if os.path.exists(log):
        c = open(log).read().strip()
        if c:
            print(f'\n--- {log} ---\n{c[:400]}')
