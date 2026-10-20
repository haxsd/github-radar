# 设计规范（UI Design System）

> 本文件记录 github-radar 网页端的视觉 token、组件与响应式约定。改 UI 前先看这里，避免硬编码颜色/间距。

## 1. 设计 token

全部定义在 `radar/static/css/base.css` 的 `:root` 中：

| 类别 | token | 说明 |
|---|---|---|
| 背景 / 表面 | `--bg` `--bg2` `--surface` `--surface-2` `--surface-3` | 深色底 + 三级表面 |
| 边框 | `--stroke` `--stroke-strong` | 分隔线与强调描边 |
| 文字 | `--text` `--text-dim` `--muted` `--faint` | 主/次/弱/极弱 |
| 品牌色 | `--accent` `--accent-2` `--accent-3` | 蓝 / 紫 / 青，仅用于品牌、CTA、选中态 |
| 语义色 | `--success` `--warn` `--danger` | 成功 / 警告 / 错误 |
| 圆角 | `--r-sm` `--r-md` `--r-lg` `--r-xl` `--r-pill` | 10 / 14 / 18 / 22 / 999 |
| 间距 | `--sp-1` ~ `--sp-10` | 4/8 网格（4,8,12,16,20,24,32,40） |
| 字号 | `--fs-xs` ~ `--fs-2xl` | 12,13,15,16,18,22,28 |
| 布局 | `--page-w` `--gutter` | 内容最大宽 1140px，左右 gutter 自适应 |
| 其他 | `--shadow` `--shadow-sm` `--ease` `--mono` | 阴影 / 缓动 / 等宽字体 |

## 2. 响应式断点

| 断点 | 行为 |
|---|---|
| `> 1120px` | 完整顶栏：品牌 + 导航 + 状态统计 |
| `≤ 1120px` | 隐藏顶栏更新时间 |
| `≤ 940px` | 顶栏导航可横向滚动（带右缘渐隐）；隐藏右侧统计 |
| `≤ 820px` | 信息流行从三列改为两列（缩略图 + 内容，操作行下移） |
| `≤ 640px` | 日报/收藏单列；榜单行信息下移；设置页单列 |
| `≤ 600px` | 收紧 gutter / 顶栏高度；信息流隐藏键盘快捷键按钮 |

## 3. 共享组件（base.css）

- 布局：`.wrap`（1140 内容宽）、`.glass`（玻璃卡片）
- 文本：`.muted` `.mono` `.kbd`
- 按钮：`.btn` + `.primary` / `.good` / `.ghost` / `.sm`；`:focus-visible` 全局外发光
- 徽标：`.pill`（`.ok` `.warn`）
- 状态：`.status-dot`（`.busy`）
- 反馈：`.toast`（`aria-live="polite"`，JS 位于 `static/js/base.js` 的 `window.toast`）
- 空态：`.empty` + `.empty-icon`
- 骨架屏：`.sk`（shimmer 动画）
- 图标：`static` 内的 SVG 使用 `.i` / `.i-lg`；服务端模板通过 `_macros.html` 的 `icon()` 宏输出
- 动效：统一 `--ease`，并遵守 `prefers-reduced-motion`

## 4. 模板与宏

- 页面模板只保留结构与数据；CSS/JS 通过 `url_for('static', ...)` 引入。
- 共享宏在 `radar/templates/_macros.html`：
  - `icon(name, cls='')`：线性 SVG 图标（radar/bookmark/clock/chart/download/edit/trash/eye/check/external/filter/star）
  - `empty(title, text, icon_name='radar', cls='')`：空状态
- 信息流卡片由 `static/js/feed.js` 渲染，图标常量在 JS 内维护，新增图标时两边保持同步。

## 5. 新页面接入

1. 在 `radar/templates/` 建模板并 `{% extends "base.html" %}`；
2. `{% block style %}` 里用 `url_for('static', filename='css/<page>.css')` 引样式；
3. 需要交互时 `{% block scripts %}` 引 `js/<page>.js`，脚本在 body 末尾、`base.js` 之后加载；
4. 使用 token 而不是硬编码颜色/间距；优先复用 base.css 组件；
5. 更新 `tests/test_static_assets.py` 的页面清单（如新增页面）。

## 6. 验证

- `python -m unittest discover -s tests -v`（含静态资源/模板引用检查）
- `node --check radar/static/js/*.js`（CI 已执行）
- 本地页面：`python -m radar.web` 后检查 1440px 与 390px 两种宽度
