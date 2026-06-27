@echo off
chcp 65001 >nul
cd /d "C:\Users\32472\.openclaw\workspace\narrascape"
set PATH=D:\ffmpeg-8.0.1-essentials_build\bin;%PATH%
set PYTHONIOENCODING=utf-8
.venv_test\Scripts\python -m streamlit run src\narrascape\dashboard.py ^
  --server.port 8501 ^
  --server.address 127.0.0.1 ^
  --theme.base dark ^
  --server.headless true ^
  --server.runOnSave false ^
  --server.fileWatcherType none
pause
