#!/bin/bash
# GeoPort CN 一键安装：双击本文件即可（无需终端操作）
# 做四件事：检查 Python → 建虚拟环境装依赖 → 编译启动器 → 放入 /Applications
set -e
cd "$(dirname "$0")"
APP_NAME="GeoPort CN.app"

echo "=========================================="
echo "  GeoPort CN 一键安装"
echo "=========================================="

# 1. Python 检查
if ! command -v python3 >/dev/null; then
    echo "❌ 未找到 python3。请先安装 Python 3.10+：https://www.python.org/downloads/"
    echo "安装完成后重新双击本文件。"
    read -r -p "按回车键关闭..." _
    exit 1
fi
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
echo "✓ Python $PYVER"

# 2. 虚拟环境 + 依赖（已存在则跳过安装，幂等）
if [ ! -x ".venv/bin/python" ]; then
    echo "→ 创建虚拟环境并安装依赖（国内镜像，约 1-2 分钟）..."
    python3 -m venv .venv
    ./.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
else
    echo "✓ 依赖已就绪（.venv 存在，跳过）"
fi

# 3. 编译启动器到 /Applications（并套上应用图标）
install_app() {
    local target="$1"
    osacompile -o "$target" scripts/launcher.applescript
    if [ -f scripts/assets/app-icon.icns ]; then
        cp scripts/assets/app-icon.icns "$target/Contents/Resources/applet.icns"
        # 新版 osacompile 产物使用 Assets.car 结构，需显式声明图标文件
        /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet.icns" "$target/Contents/Info.plist" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string applet.icns" "$target/Contents/Info.plist"
        # CFBundleIconName 优先级更高（指向 Assets.car 默认图标），必须删除
        /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$target/Contents/Info.plist" 2>/dev/null
        touch "$target"
    fi
}
echo "→ 安装启动器到 /Applications ..."
if install_app "/Applications/$APP_NAME" 2>/dev/null; then
    echo "✓ 已安装到 /Applications/$APP_NAME"
else
    mkdir -p ~/Applications
    install_app "$HOME/Applications/$APP_NAME"
    echo "✓ /Applications 无权限，已安装到 ~/Applications/$APP_NAME（个人应用目录）"
fi

echo ""
echo "=========================================="
echo "  ✅ 安装完成！"
echo "  以后使用：双击「GeoPort CN」即可"
echo "  （启动台 / Spotlight 搜索 GeoPort）"
echo "  手机用 USB 线连上 Mac 并信任即可"
echo "=========================================="
open -R "/Applications/$APP_NAME" 2>/dev/null || true
read -r -p "按回车键关闭..." _
