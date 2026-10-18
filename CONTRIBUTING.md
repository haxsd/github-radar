# 参与贡献

先谢谢你看这个项目。它是个自用的项目发现工具，欢迎提 issue 和 PR，但请尽量保持「小而专注」：一个 PR 只做一件事。

## 本地开发

```bash
git clone https://github.com/haxsd/github-radar.git
cd github-radar
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m radar.web     # 启动后访问 http://127.0.0.1:8765
```

不想配 GitHub Token / 模型 Key 也能先看界面：启动后首页点「载入示例数据」，或执行 `python -m radar.demo`。

## 代码约定

- Python 3.11+，标准库 + Flask + requests + python-dotenv + Pillow，**不要引入重量级依赖**
- 函数、变量用英文命名，注释和用户可见文案用中文
- 提交前跑一次 `python -m compileall radar` 确认语法没问题
- 采集、LLM、排序等核心逻辑改动，请在 PR 描述里写清楚「为什么这样改」和潜在影响

## 不要提交的东西

- `.env`、任何 token / API Key / 账号信息
- `data/`（数据库、缓存、日志）
- 个人路径（`C:\Users\...`、`/Users/...`）

仓库里已有 `.gitignore` 兜底，但请不要用 `git add -f` 强推这类文件。

## 提交 PR

1. Fork + 新建分支（`feat/xxx`、`fix/xxx`）
2. 只改相关文件，避免顺手格式化整个文件
3. 描述里包含：改了啥、为什么、怎么验证（截图更好）
4. 如果 UI 有变化，附一张改动后的截图

## Issue

- Bug：写清楚复现步骤、系统环境、相关日志（`data/logs/`）
- 功能建议：说明使用场景，而不只是"想要 XX"
- 安全问题：不要开公开 issue，直接私下联系仓库维护者

## 许可

提交的代码默认以 MIT 协议贡献。
