# ⚡ 科技晨报 · 每日科技一手新闻工作台

移动优先的科技新闻 PWA，用于展示每日科技一手新闻、中文摘要与政策速递。

关注板块：**AI 大模型 · 3DGS / 三维重建 · 具身智能 · 产品与公司**

## 当前项目结构

```
├── index.html          # 移动端 PWA 单页应用
├── manifest.json       # 添加到手机主屏幕所需配置
├── icon.svg            # PWA 图标
├── data/               # 前端读取的新闻 JSON
└── .github/workflows/  # GitHub Pages 自动发布
```

## 部署步骤（约 10 分钟）

1. **推送本仓库到 GitHub**（私有仓库即可）
2. **开启 Pages**：仓库 Settings → Pages → Source 选 GitHub Actions
3. **等待部署**：Actions → Deploy static site 运行成功
4. **手机访问** `https://<用户名>.github.io/<仓库名>/` → 浏览器菜单「添加到主屏幕」→ 当 App 用

后续接入抓取流水线后，只要持续写入 `data/` 目录，前端会自动展示最新数据。

## 本地调试

本地预览：

```bash
python -m http.server 8080
# 手机与电脑同一局域网时，访问 http://<电脑IP>:8080
```

## 路线图

- [x] V1：移动 PWA + GitHub Pages 发布
- [ ] 四板块抓取 + AI 摘要 + 定时数据生成
- [ ] 每周政策流水线（国家级 + 浙江/上海）
- [ ] 机器之心、36氪等失效 RSS 改用 HTML 抓取
- [ ] 浏览器 Web Push 晨报推送
- [ ] 收藏行为训练推荐排序
- [ ] 微信小程序包装（需企业主体）
