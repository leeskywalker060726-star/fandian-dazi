# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
root=Path(SPECPATH).parent
hidden=collect_submodules('mcp',filter=lambda name:not name.startswith('mcp.cli'))+['apps.api.main','apps.food_mcp','sqlalchemy.dialects.sqlite','sqlalchemy.dialects.mysql.pymysql','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on']
datas=[(str(root/'dist'),'dist'),(str(root/'LICENSE'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.')]+collect_data_files('webview')+collect_data_files('pythonnet')+collect_data_files('clr_loader')
datas.append((str(root/'data'/'catalog_meituan.json'),'data'))
a=Analysis([str(root/'desktop'/'main.py')],pathex=[str(root)],binaries=[],datas=datas,hiddenimports=hidden,hookspath=[],runtime_hooks=[],excludes=['pytest','tkinter','PyQt5','PyQt6','PySide2','PySide6'],noarchive=False)
pyz=PYZ(a.pure)
app=EXE(pyz,a.scripts,[],exclude_binaries=True,name='FandianDazi',icon=str(root/'desktop'/'app.ico'),debug=False,strip=False,upx=False,console=False)
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='FandianWorker',debug=False,strip=False,upx=False,console=True)
coll=COLLECT(app,worker,a.binaries,a.datas,strip=False,upx=False,name='FandianDazi')
