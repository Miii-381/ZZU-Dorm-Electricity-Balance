# ZZU Electricity Monitor

[![Python Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fendoflife.date%2Fapi%2Fpython.json&query=%24%5B0%5D.latest&label=Python&style=flat&logo=python&logoColor=white&color=3776AB)](https://www.python.org/)
[![ZZU.Py](https://img.shields.io/pypi/v/zzupy?label=ZZU.Py&style=flat)](https://pypi.org/project/zzupy/)
[![License](https://img.shields.io/github/license/Elykia093/ZZU-Electricity-Monitor.svg?style=flat)](https://github.com/Elykia093/ZZU-Electricity-Monitor/blob/main/LICENSE)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-online-2ea44f?style=flat&logo=githubpages&logoColor=white)](https://elykia093.github.io/ZZU-Electricity-Monitor/)

## 功能特性

- 定时自动获取照明/空调电量
- 低电量多渠道通知 (20+ 渠道)
- 现代化前端，支持深色模式
- 内置房间查询器，快速查找房间编号
- 统一认证 MFA Token/可信设备方案，适配 GitHub Actions 非交互运行
- AES-256-GCM 加密存储
- 支持 GitHub Actions 自动运行

## 部署方式

本项目按自部署和 GitHub Actions 两条线维护，两种方式共用 `ACCOUNT`、`PASSWORD`、`LIGHT_ROOM`、`AC_ROOM`、`ZZU_DEVICE_ID`、通知渠道等环境变量。

<details>
<summary><strong>方式一：自部署</strong></summary>

适合已有服务器、NAS、计划任务或自己维护 Python 环境的场景。程序默认执行一次电量更新，前端页面仍读取 `page/data` 里的静态数据。

```bash
python -m pip install -r requirements.txt
python main.py
```

定时运行时，把工作目录固定在仓库根目录，并持久化 `page/data`。首次 MFA 可以按下方 GitHub Actions 初始化流程完成，也可以本地运行 `python auth.py` 后再执行 `python auth.py encrypt` 生成 `page/data/tokens.enc`。

#### 数据存储

项目只保留 JSON 文件存储。电量记录按月写入 `page/data/YYYY-MM.json`，同时维护 `time.json`、`last_30_records.json` 和通知去重状态 `notify_state.json`。

自部署和 GitHub Actions 都只需要持久化 `page/data`。`tokens.enc`、`mfa.enc` 等认证材料也按文件方式保存在同一目录下。

</details>

<details>
<summary><strong>方式二：GitHub Actions</strong></summary>

适合 Fork 后全自动运行：GitHub Actions 定时更新数据，GitHub Pages 展示前端页面，`page` 分支持久化电量数据和加密认证材料。下面是完整配置流程。

GitHub Actions 会从 `page` 分支恢复 `page/data`，运行后把新的 JSON 数据和加密认证材料写回持久化分支。

#### 第一步：Fork 仓库

点击右上角 Fork 按钮，将本仓库复制到你的账号下。

#### 第二步：配置 Secrets

进入你 Fork 的仓库，点击 **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，添加以下必填配置：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `ACCOUNT` | 郑州大学统一认证账号 | 你的学号 |
| `PASSWORD` | 统一认证密码 | 你的密码 |
| `LIGHT_ROOM` | 照明电量房间号 | 使用内置房间查询器获取 |
| `AC_ROOM` | 空调电量房间号 | 使用内置房间查询器获取 |

可选配置：

| 变量名 | 默认值 | 说明 | 示例 |
|--------|--------|------|------|
| `ZZU_DEVICE_ID` | `ZZU.Py` | 统一认证 MFA 可信设备 ID，不填则继承 ZZU.Py 默认 deviceId | 已在安全中心设为可信的 deviceId |
| `NOTIFY_DEDUP` | `false` | 低电量报警去重开关，设为 `true` 后同一低电量状态不会重复报警 | `true` |

**获取房间号：**

1. 访问 [宿舍电量监控](https://elykia093.github.io/ZZU-Electricity-Monitor/)
2. 点击导航栏 **"房间查询"** 按钮
3. 依次选择区域、建筑、单元、房间号
4. 复制显示的照明和空调房间编号
5. 分别配置到 `LIGHT_ROOM` 和 `AC_ROOM`

支持主校区、北校区、东校区、南校区、护理学院、洛阳校区。

#### 第三步：配置 GitHub Pages

进入你 Fork 的仓库，点击 **Settings** → **Pages**：

1. 在 **Source** 部分，将构建和部署源从 **"Deploy from a branch"** 改为 **"GitHub Actions"**
2. 保存设置

这样配置后，GitHub Actions 会自动将生成的页面部署到 GitHub Pages，你就可以通过 `https://你的用户名.github.io/ZZU-Electricity-Monitor/` 访问电量监控页面了。

#### 第四步：启用 Actions

进入 **Actions** 页面，点击 **I understand my workflows, go ahead and enable them** 启用工作流。

**定时触发方式（二选一）：**

- **方式一：GitHub Actions 定时**（简单，但可能有 10-60 分钟延迟）

  编辑 `.github/workflows/update.yml`，取消注释 schedule 部分：
  ```yaml
  on:
    schedule:
      - cron: '0 16,20,0,4,8,12 * * *'  # UTC 时间，对应北京 0,4,8,12,16,20 点
    workflow_dispatch:
  ```

- **方式二：精确定时触发**（推荐，无延迟）

  参考下方 [精确定时触发（可选）](#精确定时触发可选) 配置。

你也可以点击 **Run workflow** 手动触发运行。

#### 第五步：完成 MFA Token 初始化（推荐）

学校统一认证在 2026-06-02 新增了手机号短信验证。项目已适配 `ZZU.Py >= 7.2.0` 的 MFA 流程，但 GitHub Actions 不能交互输入短信验证码。

推荐做法：直接使用 GitHub Actions 初始化，不需要本地 Python 环境。

1. 进入 **Actions** → **Refresh MFA Token**
2. 点击 **Run workflow**，分支选择 `main`，`mode` 选择 `request`，`code` 留空
3. 等待手机收到统一认证短信验证码
4. 再次点击 **Run workflow**，分支选择 `main`，`mode` 选择 `verify`，`code` 填入短信验证码
5. 成功后 workflow 会把 `data/tokens.enc` 写入 `page` 分支
6. 前往 [统一认证安全中心](https://authx-service.s.zzu.edu.cn/security-center/eqIP-management)，把设备 ID 显示为 `ZZU.Py` 的设备设置为可信设备；如果你配置了自定义 `ZZU_DEVICE_ID`，则选择对应的设备 ID
7. 回到 **Actions** → **Update Data**，手动运行一次更新

这个流程会在第一次运行时把 MFA challenge 加密保存为 `data/mfa.enc`，第二次验证成功后删除 `mfa.enc` 并生成 `tokens.enc`。验证码只用于短时间内完成验证，不要把验证码发到 Issue、PR 或聊天里。

<details>
<summary>展开查看本地备用 MFA 与认证文件说明</summary>

本地备用做法：

1. 在本地设置 `ACCOUNT`、`PASSWORD`，建议设置稳定的 `ZZU_DEVICE_ID`
2. 运行 `python auth.py`
3. 按提示输入短信验证码，生成 `page/data/tokens.json`
4. 运行 `python auth.py encrypt` 生成 `page/data/tokens.enc`；该文件使用 `PASSWORD` 加密
5. 前往 [统一认证安全中心](https://authx-service.s.zzu.edu.cn/security-center/eqIP-management)，将设备 ID 显示为 `ZZU.Py` 或你的自定义 `ZZU_DEVICE_ID` 的设备设置为可信设备
6. 将同一个 `ZZU_DEVICE_ID` 配置到 GitHub Secrets；如果本地不设置 `ZZU_DEVICE_ID`，Actions 也会使用 ZZU.Py 默认 deviceId

如果使用本地备用做法，首次启用 MFA 时需要让工作流能读到 `tokens.enc`：

- 推荐：将 `page/data/tokens.enc` 放到 `page` 分支的 `data/` 目录
- 如果只维护自己的私有 fork，可以临时强制添加 `page/data/tokens.enc` 到 `main` 并手动运行一次工作流；公开仓库不建议这样做，因为删除后历史记录中仍会保留该认证材料
- 不要提交 `page/data/tokens.json`

`tokens.enc` 和 `mfa.enc` 虽然是加密文件，但仍是个人认证材料。不要把个人认证文件提交到 `main` 分支；公开仓库的 `page` 分支密文仍可能被他人下载。本项目使用 `PASSWORD` 作为加密密钥，上游维护时不要接收 fork PR 中的个人认证文件。

如果 `page` 分支中存在 `tokens.enc`，但当前 `PASSWORD` 无法解密它，工作流会在解密步骤直接失败。此时请确认加密时使用的密码和 GitHub Secrets 里的 `PASSWORD` 一致，或重新运行 **Refresh MFA Token** 生成新的 `tokens.enc`。

工作流会在上传 GitHub Pages artifact 前移除 `tokens.json`、`tokens.enc`、`mfa.json` 和 `mfa.enc`，避免认证文件直接出现在部署出来的网站目录中；`page` 分支中的 `tokens.enc` 仅用于后续 Actions 读取和刷新。

</details>

#### 第六步：配置通知渠道（可选）

至少配置一个通知渠道以接收电量提醒。推荐使用 Telegram，无发送次数限制。

</details>

## 通知渠道配置

<details>
<summary>展开查看 20+ 通知渠道配置</summary>

免费且最值得优先配置的渠道：Telegram、WxPusher、企业微信群机器人、Microsoft Teams、Discord、Slack、Chanify。它们不依赖付费短信额度，适合日常低电量提醒；如果只想少配几个，优先选 Telegram + 微信系或常用团队 IM。

### Telegram（推荐）

每次运行都会发送通知，无发送次数限制。

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `TELEGRAM_BOT_TOKEN` | Bot Token，从 @BotFather 获取 | 是 |
| `TELEGRAM_CHAT_ID` | Chat ID，从 @userinfobot 获取 | 是 |

**获取方法：**
1. 在 Telegram 搜索 @BotFather，发送 `/newbot` 创建机器人，获取 Token
2. 搜索 @userinfobot，发送任意消息获取你的 Chat ID
3. 给你创建的机器人发送一条消息（激活对话）

### Server酱

仅在电量不足时发送，节约每日免费额度。

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `SERVERCHAN_KEY` | SendKey，从 sct.ftqq.com 获取 | 是 |

### 邮件通知

仅在电量不足时发送。

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `EMAIL` | 邮箱地址（发送和接收） | 是 |
| `SMTP_CODE` | SMTP 授权码（非邮箱密码） | 是 |
| `SMTP_SERVER` | SMTP 服务器地址 | 是 |

**常用 SMTP 服务器：**
- QQ邮箱：`smtp.qq.com`
- 163邮箱：`smtp.163.com`
- Gmail：`smtp.gmail.com`

### Bark（iOS）

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `BARK_KEY` | Bark 推送密钥 | 是 |
| `BARK_URL` | 自建服务器地址 | 否 |

### 钉钉机器人

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `DINGTALK_WEBHOOK` | 机器人 Webhook 地址 | 是 |
| `DINGTALK_SECRET` | 加签密钥 | 否 |

### 飞书机器人

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `FEISHU_WEBHOOK` | 机器人 Webhook 地址 | 是 |
| `FEISHU_SECRET` | 加签密钥 | 否 |

### Discord

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `DISCORD_WEBHOOK` | Discord 频道 Webhook 地址 | 是 |

### Slack

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `SLACK_WEBHOOK` | Slack Incoming Webhook 地址 | 是 |

### Microsoft Teams

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `TEAMS_WEBHOOK` | Microsoft Teams Incoming Webhook 地址 | 是 |

### Matrix

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `MATRIX_HOMESERVER` | Matrix homeserver 地址，例如 `https://matrix.org` | 是 |
| `MATRIX_ACCESS_TOKEN` | Matrix 用户访问令牌 | 是 |
| `MATRIX_ROOM_ID` | 接收房间 ID | 是 |
| `MATRIX_MSGTYPE` | 消息类型，默认 `m.text` | 否 |

### 企业微信

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `WECOM_CORP_ID` | 企业 ID | 是 |
| `WECOM_AGENT_ID` | 应用 AgentId | 是 |
| `WECOM_SECRET` | 应用 Secret | 是 |
| `WECOM_TOUSER` | 接收用户，默认 @all | 否 |

### 企业微信群机器人

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `WECOM_BOT_WEBHOOK` | 群机器人 Webhook 地址 | 是 |

### PushPlus

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `PUSHPLUS_TOKEN` | 推送 Token | 是 |

### 息知

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `XIZHI_TOKEN` | 息知推送 Token | 是 |
| `XIZHI_URL` | 自建或备用接口地址，默认 `https://xizhi.qqoq.net` | 否 |

### go-cqhttp

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `GOCQHTTP_URL` | go-cqhttp 服务地址 | 是 |
| `GOCQHTTP_TOKEN` | 访问令牌 | 否 |
| `GOCQHTTP_TARGET` | 目标 QQ 号 | 是 |

### Gotify

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `GOTIFY_URL` | Gotify 服务器地址 | 是 |
| `GOTIFY_TOKEN` | 应用 Token | 是 |

### iGot

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `IGOT_KEY` | iGot 推送密钥 | 是 |

### PushDeer

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `PUSHDEER_KEY` | PushDeer 推送密钥 | 是 |

### WxPusher

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `WXPUSHER_APP_TOKEN` | WxPusher 应用 AppToken | 是 |
| `WXPUSHER_UIDS` | 接收用户 UID，多个用英文逗号分隔 | 否 |
| `WXPUSHER_TOPIC_IDS` | 主题 ID，多个用英文逗号分隔 | 否 |

`WXPUSHER_UIDS` 和 `WXPUSHER_TOPIC_IDS` 至少配置一个。

### Chanify

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `CHANIFY_TOKEN` | Chanify 发送 Token | 是 |
| `CHANIFY_URL` | 自建服务器地址，默认 `https://api.chanify.net` | 否 |

### Synology Chat

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `SYNOLOGY_CHAT_URL` | Synology Chat 服务器地址 | 是 |
| `SYNOLOGY_CHAT_TOKEN` | Incoming Webhook Token | 是 |

### Qmsg酱

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `QMSG_KEY` | Qmsg 密钥 | 是 |
| `QMSG_QQ` | 指定接收的 QQ 号 | 否 |

### 智能微秘书

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `AIBOTK_KEY` | API Key | 是 |
| `AIBOTK_TARGET` | 目标用户或群 | 是 |

### PushMe

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `PUSHME_KEY` | PushMe 推送密钥 | 是 |

### Pushover

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `PUSHOVER_APP_TOKEN` | Pushover 应用 API Token | 是 |
| `PUSHOVER_USER_KEY` | 接收用户或群组 User Key | 是 |
| `PUSHOVER_DEVICE` | 指定接收设备 | 否 |
| `PUSHOVER_PRIORITY` | 消息优先级 | 否 |
| `PUSHOVER_SOUND` | 提示音名称 | 否 |
| `PUSHOVER_URL` | 附带链接 | 否 |
| `PUSHOVER_URL_TITLE` | 附带链接标题 | 否 |
| `PUSHOVER_RETRY` | 紧急优先级重试间隔 | 否 |
| `PUSHOVER_EXPIRE` | 紧急优先级过期时间 | 否 |

### Chronocat

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `CHRONOCAT_URL` | Chronocat 服务地址 | 是 |
| `CHRONOCAT_TOKEN` | 访问令牌 | 否 |
| `CHRONOCAT_TARGET` | 目标 QQ 号 | 是 |

### ntfy

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `NTFY_TOPIC` | ntfy 主题名称 | 是 |
| `NTFY_URL` | 自建服务器地址 | 否 |
| `NTFY_TOKEN` | 访问令牌 | 否 |

### 自定义 Webhook

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `WEBHOOK_URL` | Webhook 地址 | 是 |
| `WEBHOOK_METHOD` | 请求方法，默认 POST | 否 |
| `WEBHOOK_HEADERS` | 请求头，JSON 格式 | 否 |
| `WEBHOOK_BODY_TEMPLATE` | 请求体模板，支持 `{{title}}` 和 `{{content}}` 占位符 | 否 |

</details>

## 通知逻辑

| 渠道 | 触发条件 | 说明 |
|------|----------|------|
| Telegram | 每次运行 | 无发送限制，推荐作为主要通知渠道 |
| 其他渠道 | 仅低电量 | 电量低于 10 度时发送，避免频繁打扰 |

如果在 Repository Secrets 中设置 `NOTIFY_DEDUP=true`，低电量报警会按状态去重：

- 第一次低于阈值时正常报警
- 后续仍是同一低电量状态时跳过重复报警
- 照明/空调低电量状态发生变化时再次报警

启用后，程序会在 `page/data/notify_state.json` 保存上次报警状态。这个文件只记录是否已经发过低电量提醒和更新时间，不包含账号、密码、token 或房间号。

## 通知示例

**电量充足时（仅 Telegram 收到）：**
```
🏠宿舍电量通报🏠

💡 照明剩余电量：125.0 度（充足）
❄️ 空调剩余电量：80.0 度（偏低）

当前电量充足，请保持关注。
```

**电量不足时（所有渠道都会收到）：**
```
⚠️宿舍电量预警⚠️

💡 照明剩余电量：8.5 度（不足）
❄️ 空调剩余电量：5.0 度（不足）

⚠️ 电量不足，请尽快充电！
```

## 项目结构

```
ZZU-Electricity-Monitor/
├── auth.py              # 统一认证登录、Token 复用与 MFA 初始化
├── data.py              # 数据读写与索引维护
├── main.py              # 运行一次更新
├── monitor.py           # 查询电量
├── notify.py            # 通知模块，支持 20+ 通知渠道
├── config.py            # 配置模块，环境变量读取
├── requirements.txt     # Python 直接依赖
├── .github/workflows/
│   ├── update.yml       # 定时/手动更新电量并发布 Pages
│   ├── mfa.yml          # 手动 MFA 初始化，生成 page 分支 token 密文
│   ├── redeploy.yml     # 仅重新发布当前 page 数据
│   └── ci.yml           # PR/主分支验证
└── page/                # 前端页面
    ├── index.html       # 主页面，数据可视化
    ├── style.css        # 样式文件，支持深色模式
    ├── main.js          # 主要 JavaScript 逻辑
    └── data/            # JSON 数据、token 密文与临时 MFA challenge（page 分支持久化）
        └── rooms/       # 按区域拆分的房间查询器数据
```

## 分支说明

| 分支 | 用途 | 说明 |
|------|------|------|
| `main` | 源代码 | Python 后端、GitHub Actions 工作流、前端模板 |
| `page` | 持久化分支 | GitHub Pages 静态资源快照、电量数据、加密令牌 |

**为什么分两个分支？**

- **数据持久化**：电量数据存储在 `page` 分支，代码更新不会丢失历史数据
- **独立部署**：前端资源与后端代码分离，`main` 分支工作流从 `page/` 上传 GitHub Pages artifact，并同步 `page` 分支作为持久化快照
- **认证文件隔离**：加密令牌 (`tokens.enc`) 和临时 MFA challenge (`mfa.enc`) 仅用于 `page` 分支持久化，部署到 Pages 前会从网站产物移除
- **快速加载**：`page` 分支仅包含静态资源，访问速度更快

## 技术栈

- **Python** - 主程序语言
- **ZZU.Py >= 7.2.0** - 郑州大学统一认证 API 封装，支持 MFA
- **ECharts** - 数据可视化图表
- **GitHub Actions** - CI/CD 自动化
- **GitHub Pages** - 静态页面托管
- **JSON 文件** - `page/data` 持久化电量、通知状态和认证密文
- **AES-256-GCM** - 数据加密

## 常见问题

<details>
<summary><strong>如何获取房间号？</strong></summary>

**方法一：内置房间查询器（推荐）**

1. 访问 [宿舍电量监控](https://elykia093.github.io/ZZU-Electricity-Monitor/)
2. 点击导航栏 **"房间查询"** 按钮
3. 依次选择区域、建筑、单元、房间号
4. 复制显示的房间编号

**方法二：手动查表**

参考教程：[郑州大学宿舍电量监控：ZZU-Electricity-Monitor](https://blog.elykia.cn/posts/22)

</details>

<details>
<summary><strong>为什么没有收到通知？</strong></summary>

1. 检查 Secrets 配置是否正确
2. 检查 Actions 是否启用
3. 查看 Actions 运行日志排查错误

</details>

<details>
<summary><strong>为什么 Actions 运行失败？</strong></summary>

常见原因及解决方法：

1. **账号密码或 MFA 问题**：检查 `ACCOUNT`、`PASSWORD`、`ZZU_DEVICE_ID`，必要时重新运行 **Refresh MFA Token**
2. **房间号错误**：使用房间查询器重新获取正确的房间编号，格式应类似 `99-1--1-101`
3. **网络问题**：GitHub Actions 偶尔会有网络波动，可以手动重新运行
4. **page 分支不存在**：首次运行会自动创建，无需担心

</details>

<details>
<summary><strong>如何查看电量历史数据？</strong></summary>

访问你的 GitHub Pages 页面（`https://你的用户名.github.io/ZZU-Electricity-Monitor/`），页面会显示：
- 当前照明、空调剩余电量和用电统计
- 最近 30 条与按月历史电量趋势图
- 年度用电总结、每日/月度统计和热力图

</details>

<details>
<summary><strong>如何修改运行频率？</strong></summary>

编辑 `.github/workflows/update.yml` 文件中的 cron 表达式：

```yaml
schedule:
  - cron: '0 16,20,0,4,8,12 * * *'  # UTC 时间，对应北京时间 0,4,8,12,16,20 点
```

</details>

<details>
<summary><strong>精确定时触发（可选）</strong></summary>

GitHub Actions 定时任务存在延迟，如需精确定时可使用以下任一平台：

| 平台 | 免费额度 | 自托管 | 特点 |
|------|----------|--------|------|
| [Zapier](https://zapier.com) | 100 次 | 否 | 行业标杆，生态最成熟 |
| [Make](https://make.com) | 1,000 次 | 否 | 托管方案中最慷慨 |
| [n8n](https://n8n.io) | 无限制 | 是 | 完全自由，1000+ 集成 |
| [IFTTT](https://ifttt.com) | 无限基础 | 否 | 适合智能家居，限2个Applet |
| [Power Automate](https://make.powerautomate.com) | 750 次 | 否 | Office 365深度集成 |
| [OttoKit](https://ottokit.com) | 250 次 | 否 | 小企业友好 |
| [Pipedream](https://pipedream.com) | 100 次 | 否 | 开发者友好，支持代码 |
| [Pabbly Connect](https://www.pabbly.com/connect) | 100 次 | 否 | 含高级功能 |
| [Integrately](https://integrately.com) | 100 次 | 否 | 预制食谱 |
| [Activepieces](https://www.activepieces.com) | 无限制 | 是 | 开源，现代界面 |
| [Huginn](https://github.com/huginn/huginn) | 无限制 | 是 | 代理式，Ruby |
| [Node-RED](https://nodered.org) | 无限制 | 是 | IoT 专注 |

**通用配置步骤（以 Make 为例）：**

1. **创建 GitHub Token**
   - GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
   - 勾选 `repo` 和 `workflow` 权限，生成并保存 Token

2. **配置 Make**
   - 注册 Make，创建新 Scenario
   - 触发器选择 **Webhooks** → **Custom webhook**，保存后获得 webhook URL
   - 添加 **HTTP** 模块：
     - URL: `https://api.github.com/repos/你的用户名/ZZU-Electricity-Monitor/actions/workflows/update.yml/dispatches`
     - Method: `POST`
     - Headers:
       - `Content-Type` = `application/json`
       - `Authorization` = `Bearer 你的GitHubToken`
       - `Accept` = `application/vnd.github.v3+json`
     - Body: `{"ref":"main"}`

3. **配置定时**
   - 点击 Webhooks 模块右侧的时钟图标
   - 选择 **不激活**，点击 **添加定时器**
   - 勾选 **高级调度**
   - 添加 6 个时间段：
     - **Item 1**: 从 `00:00` 至 `00:01`
     - **Item 2**: 从 `04:00` 至 `04:01`
     - **Item 3**: 从 `08:00` 至 `08:01`
     - **Item 4**: 从 `12:00` 至 `12:01`
     - **Item 5**: 从 `16:00` 至 `16:01`
     - **Item 6**: 从 `20:00` 至 `20:01`
   - 时区选择 `Asia/Shanghai`

配置完成后，Make 会在精确时间触发 GitHub Actions，无延迟。

</details>

<details>
<summary><strong>如何修改电量阈值？</strong></summary>

编辑 `config.py` 文件：

```python
THRESHOLD = 10.0           # 低电量警告阈值
EXCELLENT_THRESHOLD = 100.0  # 充足电量阈值
```

</details>

## 致谢

- [ZZU.Py](https://github.com/Illustar0/ZZU.Py)
- [ZZU-Electricity](https://github.com/TorCroft/ZZU-Electricity)

## License

[MIT License](LICENSE)
