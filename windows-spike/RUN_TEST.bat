@echo off
chcp 65001 >nul
setlocal
echo ============================================
echo  剪映 Windows 草稿兼容性验证
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [x] 没找到 python，请先装 Python 3.10+ 并勾选 Add to PATH
  pause & exit /b 1
)

python -c "import pyJianYingDraft" 2>nul
if errorlevel 1 (
  echo [·] 安装依赖 pyJianYingDraft ...
  python -m pip install -q pyJianYingDraft
)

echo.
echo 请把要测试的视频文件拖到这个窗口，然后回车：
set /p VIDEO=
set VIDEO=%VIDEO:"=%

echo.
echo [·] 正在生成测试草稿...
python "%~dp0spike.py" --video "%VIDEO%" --name "WIN测试_程序生成"

echo.
pause
