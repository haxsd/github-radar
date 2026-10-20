# 更新日志

## 0.7.1

- 设置页新增“版本与更新”：检查 GitHub 最新 Release，有新版本时显示版本号和下载入口。
- 检查结果缓存 6 小时；支持手动强制刷新，网络失败不会弹错误条。

## 0.7.0

这一版主要做稳定性、性能和设置体验优化，没有破坏性的数据格式变更，旧版数据可直接升级。

### 修复

- 规则兜底打标按子串误判：`html` 被当成 AI、`email` 被当成 AI、`client` 被当成 CLI、`guide` 被当成 GUI 等。
- 信息流删除一行后，收藏/跳过按钮可能操作到下一张卡片。
- 未翻译项目在信息流、榜单、收藏页缺少原始英文描述。
- `translate_loop.py` 与批处理同时打开 `collect.log` 导致 Windows 文件锁崩溃；翻译完成后还会空跑大量批次。
- GitHub API 连接超时/网络错误不重试，网络抖动会让整波采集失败。
- 空数据库执行 `radar.collect update` 报表不存在。
- `seed` 未加采集锁，可能与 `wave` 同时写库。
- 旧版 release 事件使用 UTC 时间，和本地事件混排会差几个小时；旧版布局迁移遗漏 WAL/SHM 文件。
- 示例数据清理后残留 `seen` / `saves` 孤儿行。
- 空 Base URL / 空模型名没有友好错误提示，401/403 会无意义重试。

### 优化

- SQLite schema 改为 `PRAGMA user_version` 一次性初始化；增加常用索引和连接缓存参数。
- 首页不再预查信息流分类/标签/画像；标记已读改为单线程队列。
- Flask JSON 不再转义中文；API 增加 `no-store`，所有响应增加基础安全头。
- Web 入口优先使用 waitress，Docker 增加健康检查。
- 缩略图宽度收敛到 240/480/960，修复预下载并发竞态。
- 设置页“测试连接/测试模型”直接使用当前表单值，无需先保存。
- 增加 `pyproject.toml`、ruff 硬错误检查和 CI lint。

### 依赖

- 新增 `waitress>=3.0`（未安装时自动回退 Flask 自带服务器）。

## 更早版本

见 [Releases](https://github.com/haxsd/github-radar/releases)。
