# GitHub 中文雷达 · StarScout

[中文](README.md) · [English](README-EN.md)

> 自动抓取 GitHub 近 90 天的新项目，用大模型生成中文摘要，做成可以像刷信息流一样快速扫的本地项目发现工具。

![信息流界面](docs/screenshots/feed.png)

## 核心能力

- **信息流**：预览图、owner/repo、中文一句话、语言、时间、星数一览，点开看详情
- **详情与推荐**：180~320 字中文摘要 + 2~4 条要点 + 项目预览大图 + 相似项目推荐
- **日报与榜单**：过去 24 小时精选，周飙升 / 月飙升 / 新收录 / 总星榜
- **收藏与历史**：收藏可写备注、导出 Markdown；跳过后悔可以放回信息流
- **口味反馈**：收藏 / 感兴趣 / 跳过会调整标签权重，越刷越合口味
- **检查更新**：设置页检查 GitHub 最新 Release，有新版本时直达下载页
- **纯本地**：SQLite 存储、无遥测；模型可配 DeepSeek / OpenAI / 本地 Ollama 等任意 OpenAI 兼容接口

## 下载安装（Windows）

从 [Releases](https://github.com/haxsd/github-radar/releases/latest) 下载唯一安装包：

- `GitHubRadar-Setup-0.7.1.exe`：双击安装，不需要管理员权限；带开始菜单 / 桌面快捷方式、系统托盘，可在「设置 → 应用」卸载。
- 数据默认保存在 `%LOCALAPPDATA%\GitHubRadar\`（数据库、预览图缓存、日志、`.env`）。
- 从旧版绿色目录迁移：运行 `StarScout.exe --import-data "旧目录路径"`，或把旧目录的 `data\` 与 `.env` 复制到上面的数据目录。

## 快速开始（源码运行）

要求 Python 3.11+、一个 GitHub Token（public 只读即可）和一个 OpenAI 兼容模型的 API Key。

```bash
git clone https://github.com/haxsd/github-radar.git
cd github-radar
python -m venv .venv
.venv\Scripts\activate          # Windows；macOS / Linux 用 source .venv/bin/activate
pip install -r requirements.txt
python -m radar.web             # 打开 http://127.0.0.1:8765，先在「设置」填 Token 与模型 Key
python -m radar.collect seed    # 首次：抓取近 90 天新建项目
python -m radar.collect wave    # 日常：增量采集
```

没有 Key 也能先看效果：运行 `python -m radar.demo` 载入内置示例数据。

Docker 部署（先填好 `.env`）：

```bash
cp .env.example .env && docker compose up -d --build
```

## 常用命令

```bash
python -m radar.collect seed|wave|update|translate|tag|thumbs
python -m radar.collect clean           # 预览可疑仓库，加 --apply 才真正隐藏
```

Windows 下 `collect_bg.bat`（无窗口采集）与 `start_web.bat` 可直接交给任务计划程序。

## 文档

- [docs/design.md](docs/design.md)：网页 UI 设计规范与组件约定
- [CHANGELOG.md](CHANGELOG.md)：版本更新记录
- [CONTRIBUTING.md](CONTRIBUTING.md)：贡献约定
- [packaging/使用说明.txt](packaging/使用说明.txt)：桌面版安装与使用说明
- [Releases](https://github.com/haxsd/github-radar/releases)：版本与下载

## 数据与隐私

数据库、缓存、日志、配置全部保存在本地；`.env` 与 `data/` 已加入 `.gitignore`，项目不收集遥测。

## 许可证

MIT
