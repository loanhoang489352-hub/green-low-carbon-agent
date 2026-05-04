@echo off
chcp 65001 >nul
echo ========================================
echo 绿色低碳智能体 - 诊断工具
echo ========================================
echo.

cd /d "%~dp0src"

echo [1/5] 检查 Python 版本...
python --version

echo.
echo [2/5] 检查 .env 配置...
if exist "%~dp0.env" (
    echo .env 文件存在
    findstr /C:"API_PROVIDER" "%~dp0.env"
    findstr /C:"DEEPSEEK_API_KEY" "%~dp0.env"
) else (
    echo [错误] .env 文件不存在!
)

echo.
echo [3/5] 检查依赖包...
python -c "import openai; print('openai:', openai.__version__)"
python -c "import langchain; print('langchain:', langchain.__version__)"
python -c "import langgraph; print('langgraph:', langgraph.__version__)"

echo.
echo [4/5] 测试 LLM 连接...
python test_llm_quick.py

echo.
echo [5/5] 启动测试对话...
python test_simple.py

pause
