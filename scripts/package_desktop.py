"""Collect dependency licenses and zip the built, clean Windows distribution."""
import hashlib
import importlib.metadata as metadata
from pathlib import Path
import shutil
import zipfile

root=Path(__file__).resolve().parents[1]
bundle=root/'release'/'FandianDazi'
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
# Never distribute runtime data, settings or credentials.
for p in bundle.rglob('*'):
    if p.is_file() and (p.name.startswith('.env') or p.suffix in ('.db','.log') or p.name=='settings.json'):
        raise RuntimeError('Unexpected private runtime file in distribution: '+str(p.relative_to(bundle)))
archive=root/'release'/'FandianDazi-0.2.0-windows-x64.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(bundle.rglob('*')):
        if p.is_file(): z.write(p,p.relative_to(bundle.parent))
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
(root/'release'/'SHA256SUMS.txt').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
print(archive.name,round(archive.stat().st_size/1024/1024,1),'MiB',checksum)
