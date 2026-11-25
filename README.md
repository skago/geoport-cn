# GeoPort Enhanced

> 基于 [davesc63/GeoPort](https://github.com/davesc63/GeoPort) 的增强版：无需越狱的 iOS 定位模拟工具。
> Your Location, Anywhere!

在原版基础上，增强版主要面向**中文用户 / 国内网络环境**，新增了国内地图源（含坐标纠偏）、历史记录与收藏等功能，并做了一系列安全与稳定性修复。

## ✨ 相对上游的新特性

- 🗺️ **地图源可选**：新增高德地图（街道/卫星，默认）、百度地图、Google（街道/卫星），保留原版 15 个国际底图源
- 📐 **坐标系自动纠偏**：内置 WGS-84 ↔ GCJ-02 ↔ BD-09 转换，高德/百度底图上选点、搜索、路线回放均精确对位（发送给手机的坐标始终是 WGS-84）
- 🕐 **历史记录**：每次成功模拟位置自动记录（50 米内自动去重，上限 100 条），点击即可一键复用
- ⭐ **收藏夹**：常用地点收藏、改名、去重，不用每次重新填坐标
- ⚡ **首页秒开**：外网请求（油价/版本检查/广播/IP 归属地）全部改为后台预取 + 缓存，弱网/代理环境下页面从卡 30 秒+ 降到毫秒级
- 🔒 **安全修复**：移除 `verify=False`、关闭 Werkzeug debugger、默认只监听 `127.0.0.1`（`--host` 可开放局域网）、Flask 多线程模式
- 🐍 **现代依赖适配**：适配 pymobiledevice3 v11.6x 新 API（上游源码已落后于打包版）

详细改动列表见 [CHANGES.md](CHANGES.md)。

## 🚀 安装与运行

依赖：Python 3.10+，真机操作需要 USB 连接 iPhone/iPad（首次需配对）。

```bash
git clone https://github.com/skago/geoport-enhanced.git
cd geoport-enhanced

# 一键启动（首次运行自动创建虚拟环境并安装依赖）
./start

# 真机定位模拟在 macOS/Linux 下需要 root：
sudo ./start
```

然后浏览器打开 `http://localhost:54321`。

<details>
<summary>手动安装 / 常用参数</summary>

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt   # 国内可加 -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv/bin/python src/main.py --no-browser --port 54329
```

| 参数 | 说明 |
|---|---|
| `--port` | Web UI 端口（默认 54321，被占用时自动换随机端口） |
| `--host` | 监听地址（默认 127.0.0.1；`0.0.0.0` 开放局域网，注意安全） |
| `--no-browser` | 不自动打开浏览器 |
| `--udid` | 指定目标设备 |
| `--wifihost` | 通过 Wi-Fi 连接指定设备 IP |

</details>

数据文件（历史/收藏）保存在 `~/GeoPort/saved_locations.json`。

## ⚠️ 使用须知与免责声明

- 本工具仅供**应用开发测试、定位功能调试、个人学习**等合法用途
- 使用本工具伪造位置可能违反某些 App 或平台的服务条款，由此产生的后果由使用者自行承担
- 请遵守你所在地区的法律法规
- 地图瓦片版权归各地图厂商所有，请遵循其服务条款

## 📄 许可证

本项目基于 GPL-3.0 许可证发布（继承自上游项目）。

- 上游项目：[GeoPort](https://github.com/davesc63/GeoPort) by davesc63
- 核心依赖：[pymobiledevice3](https://github.com/doronz88/pymobiledevice3) by doronz88（同为 GPL）
- 修改内容详见 [CHANGES.md](CHANGES.md)

## ☕ 支持这个项目

如果增强版对你有帮助，欢迎请作者喝杯咖啡：

<!-- TODO: 替换成你的 Buy Me a Coffee / 爱发电链接 -->
[![Buy Me a Coffee](https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=☕&slug=YOUR_BMC_USERNAME&button_colour=FFDD00&font_colour=000000&outline_colour=000000&coffee_colour=ffffff)](https://www.buymeacoffee.com/YOUR_BMC_USERNAME)

也欢迎支持上游原作者 [davesc63](https://www.buymeacoffee.com/davesc63) —— 没有他的 GeoPort，就没有这个项目。
