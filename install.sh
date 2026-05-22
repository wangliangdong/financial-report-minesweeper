#!/bin/bash
# 财报排雷 Skill 安装脚本
# Usage: bash install.sh

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

CLAUDE_COMMANDS_DIR="$HOME/.claude/commands"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  财报排雷 Skill 安装程序${NC}"
echo -e "${BLUE}  Financial Report Minesweeper Installer${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo ""

# Step 1: Check prerequisites
echo -e "${YELLOW}[1/5] 检查环境...${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3.9+.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python: $PYTHON_VERSION"

# Check required packages
MISSING_PKGS=""
for pkg in tushare pandas requests; do
    if ! python3 -c "import $pkg" 2>/dev/null; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [ -n "$MISSING_PKGS" ]; then
    echo -e "${YELLOW}  缺少 Python 包:$MISSING_PKGS${NC}"
    read -p "  是否自动安装? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pip install $MISSING_PKGS
    else
        echo -e "${RED}请手动安装: pip install$MISSING_PKGS${NC}"
        exit 1
    fi
else
    echo "  Python 依赖: OK (tushare, pandas, requests)"
fi

# Step 2: Check TUSHARE_TOKEN
echo -e "${YELLOW}[2/5] 检查 Tushare Token...${NC}"

if [ -f "$SCRIPT_DIR/.env" ] && grep -q "TUSHARE_TOKEN" "$SCRIPT_DIR/.env"; then
    echo "  .env 文件已存在"
elif [ -n "$TUSHARE_TOKEN" ]; then
    echo "  环境变量 TUSHARE_TOKEN 已设置"
else
    echo -e "${YELLOW}  未找到 TUSHARE_TOKEN${NC}"
    read -p "  请输入你的 Tushare Pro Token (https://tushare.pro/register): " TOKEN
    if [ -n "$TOKEN" ]; then
        echo "TUSHARE_TOKEN=$TOKEN" > "$SCRIPT_DIR/.env"
        echo "  已保存到 .env"
    else
        echo -e "${YELLOW}  跳过. 请稍后手动设置:${NC}"
        echo "  export TUSHARE_TOKEN='your_token_here'"
        echo "  或创建 .env 文件"
    fi
fi

# Step 3: Install minesweeper skill
echo -e "${YELLOW}[3/5] 安装排雷 Skill...${NC}"

MINESWEEPER_DIR="$CLAUDE_COMMANDS_DIR/minesweeper"
mkdir -p "$MINESWEEPER_DIR/references"

cp "$SCRIPT_DIR/skill/SKILL.md" "$MINESWEEPER_DIR/SKILL.md"
cp "$SCRIPT_DIR/skill/references/checklist-rules.md" "$MINESWEEPER_DIR/references/checklist-rules.md"

echo "  已安装到 $MINESWEEPER_DIR"

# Step 4: Install download-report skill
echo -e "${YELLOW}[4/5] 安装年报下载 Skill...${NC}"

DOWNLOAD_REPORT="$CLAUDE_COMMANDS_DIR/download-report.md"
if [ -f "$DOWNLOAD_REPORT" ]; then
    echo "  download-report.md 已存在, 跳过"
else
    cp "$SCRIPT_DIR/skill/download-report.md" "$DOWNLOAD_REPORT"
    echo "  已安装到 $DOWNLOAD_REPORT"
fi

# Step 5: Verify
echo -e "${YELLOW}[5/5] 验证安装...${NC}"

ERRORS=0

if [ ! -f "$MINESWEEPER_DIR/SKILL.md" ]; then
    echo -e "${RED}  SKILL.md 未找到${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [ ! -f "$MINESWEEPER_DIR/references/checklist-rules.md" ]; then
    echo -e "${RED}  checklist-rules.md 未找到${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [ ! -f "$SCRIPT_DIR/scripts/minesweeper_data.py" ]; then
    echo -e "${RED}  minesweeper_data.py 未找到${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}  全部检查通过!${NC}"
else
    echo -e "${RED}  $ERRORS 项检查失败${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  安装完成!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
echo ""
echo "  使用方法 (在 Claude Code 中):"
echo ""
echo "    /minesweeper 600519"
echo "    /minesweeper 贵州茅台"
echo "    /minesweeper 000858 2023"
echo ""
echo "  项目目录: $SCRIPT_DIR"
echo "  Skill 目录: $MINESWEEPER_DIR"
echo ""
