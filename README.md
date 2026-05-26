# 远行商人消息推送

这个项目会定时抓取远行商人页面，解析当前时间段商品，并在商品变化时通过 `ntfy` 推送到安卓通知栏。

当前数据源：

- `https://www.onebiji.com/hykb_tools/comm/lkwgmerchant/preview.php?id=1&immgj=0`

## 运行方式

本项目优先面向 GitHub Actions 运行，不需要你自己的电脑一直开着。

## GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 里添加：

- `NTFY_TOPIC`：你的 `ntfy` 主题名，必填
- `NTFY_SERVER`：可选，不填时脚本默认使用 `https://ntfy.sh`
- `NTFY_TOKEN`：可选，如果你的 `ntfy` 服务需要鉴权

## 可选 Variables

也可以在 `Actions variables` 或工作流 `env` 里调整：

- `MERCHANT_URL`：默认就是当前页面源
- `TIMEZONE`：默认 `Asia/Shanghai`
- `REFRESH_TIMES`：默认 `08:00,12:00,16:00,20:00`
- `REFRESH_WINDOW_MINUTES`：默认 `20`
- `WATCH_ITEMS`：逗号分隔的关注商品名
- `NOTIFY_ON_FIRST_RUN`：默认 `true`

## 本地运行

```bash
pip install -r requirements.txt
```

PowerShell 示例：

```powershell
$env:NTFY_TOPIC="your-topic"
$env:FORCE_RUN="true"
python .\main.py
```

## GitHub Actions 持久化

工作流会把 `data/latest.json` 和 `data/history.jsonl` 的变化自动提交回仓库，这样下次运行时可以继续做商品比对。
