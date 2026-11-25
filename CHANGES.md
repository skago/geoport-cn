# CHANGES — 相对上游 davesc63/GeoPort 的修改

本文件依据 GPL-3.0 第 5(a) 条的精神，声明本 fork 对上游代码的实质性修改。
基线：上游 main 分支（commit `6565163`，v5.0.3 发布后）。

## 新增文件

| 文件 | 说明 |
|---|---|
| `requirements.txt` | 依赖清单（上游未提供） |
| `.gitignore` | 忽略 `.venv/`、`__pycache__/` |
| `CHANGES.md` | 本文件 |
| `start`（重写） | 一键启动脚本：首次运行自动建 venv 装依赖（原为空壳脚本） |

## `src/main.py`

### 新功能
- **历史记录 / 收藏 API**：`/api/locations`、`/api/history`（GET 走 `/api/locations`）、`/api/favorites` 系列路由，JSON 持久化到 `~/GeoPort/saved_locations.json`；成功模拟位置后自动记录历史（50 米去重，上限 100 条）
- **`--host` 参数**：默认监听 `127.0.0.1`（原硬编码 `0.0.0.0` 对局域网开放）

### 安全修复
- 移除 `requests.get(..., verify=False)`（2 处）及对 `InsecureRequestWarning` 的全局屏蔽
- `app.run(debug=False)`：关闭 Werkzeug debugger（任意代码执行风险）
- `threaded=True`：修复单个半开连接即可卡死整个服务的问题

### 性能 / 体验
- 首页外网请求（油价 API / 版本检查 / 广播 / IP 归属地）改为后台守护线程预取 + 30 分钟缓存，页面渲染不再阻塞（弱网下从 30 秒+ 降至毫秒级）
- IP 归属地查询优先 HTTPS（ipapi.co），失败回退 ip-api.com，并缓存结果

### 依赖适配（pymobiledevice3 ≥ 11.6x）
- `DvtSecureSocketProxyService`（已在上游库移除）→ `DvtProvider` 异步上下文 API，定位设置/清除共 3 处调用点
- `cli_install_wetest_drivers` 改为可选导入（新版本已移除，仅影响 Windows + iOS 17.0–17.3.1 老组合）
- `pyuac` 改为仅 Windows 导入（原在 macOS/Linux 上直接崩溃）

### 其他
- 版本号/更新检查指向本 fork 仓库（`GITHUB_REPO = 'skago/geoport-cn'`）
- 移除上游遗留的 `src/templates/map2.html`（从未被任何路由渲染的死代码，内含上游的第三方 VPN 推广位）
- `APP_VERSION_NUMBER` 对齐 `CURRENT_VERSION`（原 2.3.3 与 5.0.3 不一致导致误报更新）

## `src/templates/map.html`

### 新功能
- **地图源选择器**：高德街道/卫星（默认）、百度地图、Google 街道/卫星 + 原有 15 个国际源
- **坐标纠偏**：WGS-84 ↔ GCJ-02 ↔ BD-09 全套转换（eviltransform 算法）；选点/搜索/拖拽 marker/路线绘制/GPX 回放/GeoJSON 导入导出全部走业务坐标（WGS-84）与显示坐标（按源纠偏）双向转换
- **百度地图支持**：因百度瓦片网格非标准（中心原点、自有投影），采用 `proj4 + proj4leaflet` 构造 `L.CRS.Baidu` 独立地图实例，切换时视图/标注互转
- **历史/收藏面板**：查看、一键使用、收藏当前坐标（内联输入）、改名（行内编辑）、删除、清空历史
- 地图源选择持久化（localStorage）

### 修复
- `setMapSource` 在切换前先快照当前视图（原实现先改坐标系状态再取视图，导致往返切换视图不同步）
- 修复 `<script>` 标签误加载 bootstrap CSS 的问题
- GPX 回放/路线数据统一从 WGS 快照读取，避免纠偏坐标污染业务数据

### 清理
- 移除上游 SurveyMonkey 反馈链接与 App Store 不相关的推广横幅引用；页脚改为标注 fork 来源与 GPL 许可

## 未修改

- `LICENSE`（GPL-3.0）原样保留
- `docs/`、`images/`、`FAQ.md`、`MAP_LAYERS.json` 原样保留

## 第三方代码

- 百度瓦片 CRS 定义参考 [muyao1987/leaflet-tileLayer-baidugaode](https://github.com/muyao1987/leaflet-tileLayer-baidugaode)（Apache-2.0）
- GCJ-02/BD-09 转换算法为社区通行的 eviltransform 实现
