"""Convert a local capture archive; never execute or copy its application code."""
import argparse
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from apps.api.catalog_import import activate,build,use_demo,validate


def main():
    parser=argparse.ArgumentParser(description='导入美团菜单采集快照，保留账号与记忆')
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--raw-dir',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'data/local/catalog_meituan.json')
    parser.add_argument('--activate',action='store_true')
    parser.add_argument('--use-demo',action='store_true')
    args=parser.parse_args()
    if args.use_demo:
        from apps.api.seed import initialize
        initialize();use_demo();print('已切回演示目录，个人数据未变更。');return
    if bool(args.archive)==bool(args.raw_dir): parser.error('请提供 --archive 或 --raw-dir 中的一项')
    def read(name):
        if args.raw_dir: return json.loads((args.raw_dir/name).read_text(encoding='utf-8-sig'))
        with zipfile.ZipFile(args.archive) as archive:
            matches=[i for i in archive.infolist() if ('/'+i.filename.replace('\\','/')).endswith('/data/raw/'+name)]
            if len(matches)!=1 or matches[0].file_size>30_000_000: raise ValueError('压缩包中的数据文件缺失、重复或过大：'+name)
            return json.loads(archive.read(matches[0]).decode('utf-8-sig'))
    document=build(read('menus.json'),read('shops.json'))
    validate(document)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    result=document['metadata']
    if args.activate:
        from apps.api.seed import initialize
        initialize();result=activate(document)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
