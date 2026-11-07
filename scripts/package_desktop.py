"""Collect dependency licenses and zip the built, clean Windows distribution."""
import hashlib
import importlib.metadata as metadata
from pathlib import Path
import shutil
import zipfile
import argparse

root=Path(__file__).resolve().parents[1]
version=__import__('json').loads((root/'package.json').read_text(encoding='utf-8'))['version']
parser=argparse.ArgumentParser()
parser.add_argument('--bundle',type=Path,default=root/'release'/'FandianDazi')
parser.add_argument('--archive',type=Path,default=root/'release'/f'FandianDazi-{version}-windows-x64.zip')
parser.add_argument('--include-local-catalog',action='store_true',help='仅供本机演示，显式允许包含离线菜单')
args=parser.parse_args()
bundle=args.bundle
licenses=bundle/'THIRD_PARTY_LICENSES'
licenses.mkdir(exist_ok=True)
for dist in metadata.distributions():
    name=dist.metadata['Name'] or 'unknown'
    for entry in dist.files or []:
        if any(word in Path(str(entry)).name.lower() for word in ['license','copying','notice']) and '.dist-info' in str(entry):
            source=Path(dist.locate_file(entry))
            if source.is_file():
                target=licenses/name/Path(str(entry)).name
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(source,target)
python_license=Path(__import__('sys').base_prefix)/'LICENSE.txt'
if python_license.exists(): shutil.copy2(python_license,licenses/'Python-LICENSE.txt')
for package in ['react','react-dom','lucide-react','scheduler']:
    for source in (root/'node_modules'/package).glob('*LICENSE*'):
        target=licenses/package
        target.mkdir(exist_ok=True)
        shutil.copy2(source,target/source.name)
shutil.copy2(root/'LICENSE',bundle/'LICENSE')
shutil.copy2(root/'THIRD_PARTY_NOTICES.md',bundle/'THIRD_PARTY_NOTICES.md')
shutil.copy2(root/'docs'/'桌面版.md',bundle/'使用说明.md')
shutil.copy2(root/'docs'/'本地菜单接入.md',bundle/'本地菜单接入.md')
# Never distribute runtime data, settings or credentials.
for p in bundle.rglob('*'):
    if p.is_file() and (p.name.startswith('.env') or p.suffix in ('.db','.log') or p.name=='settings.json'):
        raise RuntimeError('Unexpected private runtime file in distribution: '+str(p.relative_to(bundle)))
    if p.is_file() and p.name=='catalog.json' and not args.include_local_catalog:
        raise RuntimeError('Local catalog must not enter the public distribution')
archive=args.archive
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(bundle.rglob('*')):
        if p.is_file(): z.write(p,p.relative_to(bundle.parent))
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.sha256').write_text(checksum+'  '+archive.name+'\n',encoding='utf-8')
if archive.name==f'FandianDazi-{version}-windows-x64.zip':
    (root/'release'/'SHA256SUMS.txt').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
print(archive.name,round(archive.stat().st_size/1024/1024,1),'MiB',checksum)
