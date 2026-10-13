"""项目内离线安装 pip 与 pytest，避免修改 Ubuntu 的系统目录。"""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
pip_wheel = next((root / 'wheels').glob('pip-*.whl'))
sys.path.insert(0, str(pip_wheel))
from pip._internal.cli.main import main

if main(['install', '--no-index', '--find-links', str(root / 'wheels'),
         'pip', 'pytest==8.4.2']):
    raise SystemExit(1)
subprocess.run([sys.executable, '-m', 'pytest', '--version'], check=True)
