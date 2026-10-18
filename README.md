# GitHub 中文雷达 · StarScout

> 把 GitHub 上「最近新建 / 正在更新」的项目自动抓下来，用大模型生成中文介绍，做成一个可以像刷信息流一样快速扫的本地网页。

给自己用的项目发现工具：不用每天翻 Trending，打开就是一批带中文摘要的新项目，收藏 / 跳过会影响后续推荐。

![信息流](docs/screenshots/feed.png)

## 功能

- **列表信息流**：项目预览图、owner/repo、中文一句话、语言、时间、判断徽标、星数；点开看详情
- **详情页**：180~320 字中文摘要 + 2~4 条要点 + 项目预览大图 + **相似项目推荐**
- **日报**：过去 24 小时最值得看的项目，按口味排序，每个领域最多 2 个
- **榜单**：周飙升 / 月飙升 / 新收录 / 总星榜（按 star 快照差值计算）
- **收藏**：可写备注、一键导出 Markdown
- **历史**：看过的、跳过的、收藏的都在；跳过后悔可以放回信息流
- **兴趣反馈**：收藏 / 感兴趣 / 跳过会改变标签权重，越刷越合口味
- **标签组合筛选**：领域 + 形态 + 平台 + 特性多条件 AND
- **数据清洗**：自动隐藏 SEO 推广页、破解资源、批量刷星农场
- **全本地**：SQLite 存数据，不收集任何遥测

![详情页](docs/screenshots/detail.png)
![日报](docs/screenshots/daily.png)
![榜单](docs/screenshots/rank.png)
![设置页](docs/screenshots/settings.png)

## 快速开始

要求：Python 3.11+，一个 GitHub Token，一个 OpenAI 兼容的模型 API Key（默认 DeepSeek）。

```bash
git clone https://github.com/haxsd/github-radar.git
cd github-radar

# 建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

# 启动网页（第一次还没有数据，先去「设置」配置 key）
python -m radar.web
```

打开 <http://127.0.0.1:8765>，点右上角 **设置**，填入：

1. **GitHub Token**（不需要勾任何权限，public 仓库只读即可；留空则尝试用 `gh auth login` 的登录态）
2. **模型服务**：选择 DeepSeek / OpenAI / Ollama / 自定义，填好 Base URL、模型名、API Key
3. 点「测试连接」「测试模型」确认可用，再点「保存配置」

然后拉一次数据（首次会抓近 90 天的新项目，约 1~2 万条，需要一段时间）：

```bash
python -m radar.collect seed      # 首次种子数据
python -m radar.collect wave      # 日常增量（新项目 + 更新 + 中文补全）
```

再刷新网页就能刷了。

## 配置

两种方式等价：网页「设置」会写回 `.env`（推荐，立即生效），也可以手动改 `.env`。
环境变量优先级高于 `.env`。

| 键 | 说明 | 默认 |
|---|---|---|
| `GITHUB_TOKEN` | GitHub PAT，留空则用 `gh` CLI 登录态 | 空 |
| `LLM_PROVIDER` | `deepseek` / `openai` / `ollama` / `custom` | `deepseek` |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `LLM_API_KEY` | 模型 API Key（Ollama 可留空） | 空 |
| `LLM_JSON_MODE` | 是否要求 JSON 输出 | `1` |
| `LLM_DISABLE_THINKING` | 关闭思考模式（DeepSeek 建议开） | `1` |
| `WEB_HOST` / `WEB_PORT` | 网页监听地址 | `127.0.0.1` / `8765` |

> 不想用 DeepSeek？也可以用 OpenAI（贵）、本地 Ollama（免费），或者任何兼容 `/chat/completions` 的自建网关。

## 常用命令

```bash
python -m radar.collect seed          # 种子：近 90 天新建项目
python -m radar.collect wave          # 日常：增量收录 + 更新事件 + 中文补全
python -m radar.collect update        # 只刷新已有仓库的 star / 提交状态
python -m radar.collect translate     # 补翻译（可加 --limit 500）
python -m radar.collect tag           # 补标签
python -m radar.collect rewrite       # 重写老卡片
python -m radar.collect clean         # 预览可疑仓库（--apply 才真正隐藏，--unhide 恢复）
python -m radar.web                   # 启动网页
```

## 自动化（可选）

Windows 提供了现成的脚本（任务计划里指向它们即可，全天后台无窗口运行）：

| 脚本 | 用途 |
|---|---|
| `collect_bg.bat` | 无窗口采集，日志写 `data/logs/collect.log` |
| `start_web.bat` | 无窗口启动网页服务 |
| `run_hidden.vbs` | 隐藏窗口启动器（`wscript run_hidden.vbs collect_bg.bat`） |
| `translate_loop.bat` | 分批补翻译（每批 120 条 + 超时保护） |

macOS / Linux 用 cron：

```cron
0 0,8,16 * * * cd /path/to/github-radar && .venv/bin/python -m radar.collect wave >> data/logs/collect.log 2>&1
```

## 项目结构

```
radar/
  config.py     配置（GitHub token、模型服务、规则常量）
  db.py         SQLite 结构与读写
  github.py     GitHub REST / GraphQL
  llm.py        模型调用（中文卡生成 / 翻译 / 打标）
  collect.py    采集与维护命令
  feed.py       推荐排序、筛选、榜单、日报
  web.py        Flask 网页与 API
  templates/    页面模板
data/           本地数据库、缓存（不提交）
```

采集规则：**star > 50 且最近 3 个月有提交** 的仓库进入池子，采集窗口为近 90 天新建；更新事件展示 release / 涨星 / 提交等活动。

## 常见问题

- **提示 GitHub 403 / 限流**：没配 token 时只有 60 次/小时，配置后 5000 次/小时。
- **模型报错 401 / 404**：检查 Base URL 是否需要 `/v1`，模型名是否拼对；可以先点设置页「测试模型」。
- **网页能打开但没有内容**：还没跑采集，或数据还在翻译中；看 `data/logs/` 下的日志。
- **公司网络/代理环境**：程序默认绕过系统代理直连（避免本机代理排队卡死），如必须走代理可自行调整 `requests` 会话。

## 数据与隐私

所有数据（数据库、缓存、日志、配置）都在本地，仓库里不包含任何密钥。`.env` 与 `data/` 已在 `.gitignore` 中。

## License

MIT
