# 远行商人消息推送

这个项目会定时抓取远行商人页面，解析当前时间段商品，并在商品变化时通过 `ntfy` 推送到安卓通知栏。

当前数据源：

- `https://www.onebiji.com/hykb_tools/comm/lkwgmerchant/preview.php?id=1&immgj=0`

## 项目作用

这套脚本主要解决两件事：

1. 在远行商人刷新后自动抓取当前商品
2. 如果商品和上次结果不同，就自动推送到手机

项目默认使用 GitHub Actions 托管运行，所以不需要你自己的电脑一直开着。

## 当前触发机制

现在的触发机制分成两层：

### 1. GitHub Actions 定时触发

工作流只会在下面这些时间点自动运行：

- `08:00` 到 `08:30`
- `12:00` 到 `12:30`
- `16:00` 到 `16:30`
- `20:00` 到 `20:30`

在每个时间窗口内，GitHub Actions 会大约每 5 分钟触发一次。

### 2. 脚本内部时间判断

脚本里还会再判断一次当前时间是否处于刷新窗口内。

默认配置：

- `REFRESH_TIMES=08:00,12:00,16:00,20:00`
- `REFRESH_WINDOW_MINUTES=30`

也就是说，即使 GitHub Actions 成功触发，脚本也只会在这些刷新点后的半小时内真正执行抓取逻辑。

### 手动触发

如果你在 GitHub 页面手动点击 `Run workflow`，默认会启用 `force_run=true`，跳过时间窗口判断，方便你随时联调测试。

## GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 里添加：

- `NTFY_TOPIC`：你的 `ntfy` 主题名，必填
- `NTFY_SERVER`：可选，不填时脚本默认使用 `https://ntfy.sh`
- `NTFY_TOKEN`：可选，如果你的 `ntfy` 服务需要鉴权

## 可选环境变量

可以在工作流 `env` 中调整：

- `MERCHANT_URL`：默认就是当前页面源
- `TIMEZONE`：默认 `Asia/Shanghai`
- `REFRESH_TIMES`：默认 `08:00,12:00,16:00,20:00`
- `REFRESH_WINDOW_MINUTES`：默认 `30`
- `WATCH_ITEMS`：逗号分隔的关注商品名
- `NOTIFY_ON_FIRST_RUN`：默认 `true`
- `FORCE_RUN`：手动调试时可设为 `true`

## 本地运行

先安装依赖：

```bash
pip install -r requirements.txt
```

PowerShell 示例：

```powershell
$env:NTFY_TOPIC="your-topic"
$env:FORCE_RUN="true"
python .\main.py
```

## 状态文件

脚本会在 `data` 目录下维护两个文件：

- `data/latest.json`：保存最近一次的商品结果，用于下次比对
- `data/history.jsonl`：保存每次抓取到的历史记录

GitHub Actions 会把这两个文件的变化自动提交回仓库，这样后续运行时可以继续做商品变化判断。

## 常见说明

- GitHub Actions 的 `schedule` 不是绝对准点的，高峰时段可能会延迟几分钟
- 所以当前方案是“时间窗口内多次触发 + 脚本内部再判断一次”
- 如果你没有收到通知，先看 Actions 日志里 `Run merchant notifier` 这一步的输出
