"""Scan publishable files without ever printing secret values or matching lines."""
import argparse
from pathlib import Path
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[re.compile(rb'sk-[A-Za-z0-9_-]{24,}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
          re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
failures=set()
known=[]


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.DEVNULL)


def check(name,data,patterns=True):
    if any(value in data for value in known): failures.add(name+' (local credential match)')
    if patterns and any(pattern.search(data) for pattern in PATTERNS): failures.add(name+' (credential pattern)')


def private_path(name):
    parts=Path(name.replace('\\','/')).parts
    return any(p in ('.env','.runtime','desktop-data') for p in parts) or any(p.startswith('.env.') and p!='.env.example' for p in parts) or Path(name).name in ('settings.json','settings.tmp') or Path(name).suffix in ('.db','.log','.key') or '/data/local/' in '/'+name or '/data/raw/' in '/'+name


def scan_bundle(bundle):
    from PyInstaller.archive.readers import CArchiveReader
    for path in bundle.rglob('*'):
        if not path.is_file(): continue
        name='bundle/'+path.relative_to(bundle).as_posix()
        if private_path(name): failures.add(name+' (private runtime file)')
        # Third-party binaries may contain token-format examples; compare actual local secrets throughout.
        check(name,path.read_bytes(),patterns=path.suffix in {'.json','.md','.txt','.js','.html','.css','.pem'})
        if path.name not in ('FandianDazi.exe','FandianWorker.exe'): continue
        archive=CArchiveReader(str(path))
        for entry,info in archive.toc.items():
            if info[-1]=='z':
                embedded=archive.open_embedded_archive(entry)
                for module in embedded.toc:
                    data=embedded.extract(module,raw=True)
                    if data: check(name+'!'+module,data,patterns=module.startswith(('apps.','desktop.')))
            else:
                data=archive.extract(entry)
                if data: check(name+'!'+entry,data,patterns=entry=='main')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--staged',action='store_true')
    parser.add_argument('--history',action='store_true')
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    # Local values are compared in memory only; they never enter source or output.
    if (ROOT/'.env').is_file():
        from dotenv import dotenv_values
        for key,value in dotenv_values(ROOT/'.env').items():
            if value and len(value)>=8 and re.search(r'KEY|TOKEN|SECRET|PASSWORD',key,re.I):
                known.append(value.encode())
    names=git('ls-files','-z',*([] if args.staged else ['--cached','--others','--exclude-standard'])).decode('utf-8').split('\0')
    for name in set(names)-{''}:
        if private_path(name): failures.add(name+' (private file)')
        path=ROOT/name
        data=git('show',':'+name) if args.staged else path.read_bytes() if path.is_file() else b''
        check(name,data)
    if args.history:
        for line in git('rev-list','--objects','--all').decode('utf-8').splitlines():
            oid,_,name=line.partition(' ')
            if git('cat-file','-t',oid).strip()!=b'blob': continue
            if name and private_path(name): failures.add('history/'+name+' (private file)')
            check('history/'+oid,git('cat-file','-p',oid))
    if args.bundle: scan_bundle(args.bundle)
    if args.archive:
        with zipfile.ZipFile(args.archive) as archive:
            if archive.testzip(): failures.add('archive (corrupt entry)')
            for entry in archive.infolist():
                if entry.is_dir(): continue
                if private_path(entry.filename): failures.add('archive/'+entry.filename+' (private file)')
                check('archive/'+entry.filename,archive.read(entry),patterns=Path(entry.filename).suffix in {'.json','.md','.txt','.js','.html','.css','.pem'})
    if failures:
        print('Publish check FAILED (values redacted):\n'+'\n'.join(sorted(failures)))
        raise SystemExit(1)
    print('Publish check passed: no detected credential values/patterns or private runtime files.')


if __name__=='__main__': main()
