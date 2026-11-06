"""Create only the configured application database, without printing credentials."""
import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
if os.getenv('USE_MYSQL', 'false').lower() == 'true':
    import pymysql
    name = os.getenv('MYSQL_DATABASE','fandian')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', name):
        raise SystemExit('MYSQL_DATABASE must contain only letters, digits or underscores.')
    try:
        connection = pymysql.connect(host=os.getenv('MYSQL_HOST','127.0.0.1'), port=int(os.getenv('MYSQL_PORT','3306')),
            user=os.getenv('MYSQL_USER','root'), password=os.getenv('MYSQL_PASSWORD',''), connect_timeout=5)
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            cursor.execute('SELECT VERSION()')
            print('MySQL connected:', cursor.fetchone()[0])
        connection.close()
    except Exception as error:
        print('MySQL initialization failed:', type(error).__name__, 'code:', error.args[0] if error.args else 'unknown')
        raise SystemExit(1)
else:
    print('SQLite local demo selected.')

from apps.api.seed import initialize
initialize()
print('Application tables and demo catalog initialized.')
