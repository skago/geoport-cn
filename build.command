#!/bin/bash
# GeoPort CN 一键构建：打包自包含 macOS 应用（无需 Python 环境的发布版）
# 产物：dist/GeoPort CN.app + dist/GeoPort-CN-mac-<版本>.zip
set -e
cd "$(dirname "$0")"

echo "=========================================="
echo "  GeoPort CN 自包含版构建"
echo "=========================================="

# 1) 依赖检查（构建机需要源码环境；产物不需要）
if [ ! -x ".venv/bin/python" ]; then
    echo "→ 构建机首次准备：创建 venv 并安装依赖..."
    python3 -m venv .venv
    ./.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
fi
if ! ./.venv/bin/pip show pyinstaller >/dev/null 2>&1; then
    ./.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple pyinstaller
fi

# 2) PyInstaller 打包服务二进制
echo "→ PyInstaller 打包（约 1-2 分钟）..."
rm -rf build dist geoport-cn.spec
./.venv/bin/pyinstaller --onefile --name geoport-cn \
    --collect-all pymobiledevice3 \
    --collect-all apple_compress --collect-all pyimg4 --collect-all ipsw_parser \
    --collect-all pytun_pmd3 --collect-all pmd_pytcp --collect-all pmd_net_addr \
    --add-data "src/templates:templates" \
    src/main.py 2>&1 | tail -1

# 3) 组装 app：AppleScript 启动器壳 + 二进制 + 图标
echo "→ 组装 GeoPort CN.app ..."
rm -rf "dist/GeoPort CN.app"
osacompile -o "dist/GeoPort CN.app" scripts/launcher-release.applescript
cp dist/geoport-cn "dist/GeoPort CN.app/Contents/MacOS/geoport-cn"
cp scripts/assets/app-icon.icns "dist/GeoPort CN.app/Contents/Resources/applet.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet.icns" "dist/GeoPort CN.app/Contents/Info.plist" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string applet.icns" "dist/GeoPort CN.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "dist/GeoPort CN.app/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleName GeoPort CN" "dist/GeoPort CN.app/Contents/Info.plist" 2>/dev/null || true
touch "dist/GeoPort CN.app"

# 4) 打 zip 发布包
VERSION=$(grep -o 'APP_VERSION_NUMBER = "[^"]*"' src/main.py | cut -d'"' -f2 | sed 's/^v//')
cd dist
rm -f GeoPort-CN-mac-*.zip
zip -qr "GeoPort-CN-mac-v${VERSION}.zip" "GeoPort CN.app"
cd ..

echo ""
echo "=========================================="
echo "  ✅ 构建完成"
du -sh "dist/GeoPort CN.app" "dist"/GeoPort-CN-mac-*.zip
echo "  app 可直接分发；zip 用于 GitHub Release"
echo "=========================================="
