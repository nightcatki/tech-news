# 科技晨报

移动优先的科技新闻 PWA，用于每天展示一手科技新闻。可在手机浏览器中添加到主屏幕使用。

关注板块：AI 大模型、3DGS、具身智能、产品与公司。
另包含开发者工具、算力与云、安全漏洞等高价值技术来源。

## 项目结构

```text
index.html          # 移动端 PWA 单页应用
manifest.json       # 添加到手机主屏幕所需配置
icon.svg            # PWA 图标
scripts/            # 每日新闻 JSON 生成脚本
data/               # 前端读取的新闻 JSON
.github/workflows/  # GitHub Actions 自动生成与部署
```

## 每日自动更新

`.github/workflows/daily-news.yml` 已配置：

- 每天北京时间 07:00 自动运行
- 抓取 RSS/Atom 新闻源
- 优先展示官方公告、官方博客、开发者变更日志、安全公告等一手来源
- 为高分新闻生成“重点解读”字段
- 生成 `data/YYYY-MM-DD.json`
- 覆盖 `data/latest.json`
- 更新 `data/index.json`
- 自动提交到 `main`
- 自动重新部署 GitHub Pages

手动运行：仓库 → Actions → Generate daily news → Run workflow。

## 手机端翻译

当前网页使用“手动逐条翻译”：

1. 打开网页底部“我的”
2. 选择 DeepSeek 官方 API 或智谱 GLM 官方 API
3. 填入 API Key 并保存
4. 回到“今日”，点击每张新闻卡片底部的“翻译”

Key 只保存在当前浏览器本地。翻译成功后会缓存到本地，重复打开不会再次调用。

## 本地调试

```bash
python scripts/generate_news.py
python -m http.server 8080
```

手机和电脑在同一局域网时，可访问 `http://<电脑IP>:8080` 预览。

## 路线图

- [x] 移动端 PWA + GitHub Pages 发布
- [x] 四板块抓取 + 定时数据生成
- [x] 一手来源优先排序 + 重要新闻重点解读
- [x] 手机端 DeepSeek / 智谱官方 API 手动逐条翻译
- [ ] 每周政策流水线
- [ ] 浏览器 Web Push 晨报提醒
- [ ] 收藏行为训练推荐排序
