# remote-claude-control

飞书 → tmux → Claude Code 远程遥控工具（单机模式）。

> **平台：macOS 与 Linux。** macOS 用 launchd 常驻 bridge、Homebrew 装依赖；Linux（已在 Amazon Linux 2023 与 Ubuntu 24.04、x86_64 与 arm64 实测）用 systemd 常驻 bridge、发行版包管理器装依赖。两套安装见下方——**Mac 用户按〈安装（cc-remote CLI，推荐）〉，Linux 用户按〈Linux / EC2 安装〉**。核心代码同一份，只是常驻方式与依赖装法按平台分流。

## 用途

在飞书手机端用文字输入（或飞书客户端的语音转文字），发送给飞书机器人后，自动转发到远程 Mac 上运行 Claude Code 的 tmux session；Claude 跑完一轮，Stop hook 自动把终端截图 + 回复文字发回飞书。

> 「语音」指**飞书 App 自带的语音转文字**——机器人只接收文字消息，未转文字的纯语音消息会被忽略。

## 前置条件

照本 README 操作前，先备齐：

1. **macOS 或 Linux**（Linux 见下方〈Linux / EC2 安装〉，其余步骤通用）。
2. **Claude Code 本体已安装并登录过**——本工具只是「把飞书消息喂给 tmux 里的 `claude`」，不含 Claude Code 本身。先 `npm i -g @anthropic-ai/claude-code`（或按官方文档装），跑一次 `claude` 完成认证，确认终端里 `claude` 命令可用。**这一步漏了，遥控链路会静默断**（消息打进终端但没有 Claude 在跑，永远等不到截图回传）。
3. **Python 3.8+**（macOS 自带的 `python3` 一般够；Linux 见下方说明——某些发行版需用 venv，依赖装不进系统 python）。
4. **包管理器**：macOS 用 **Homebrew**，Linux 用发行版自带的 **dnf**（Amazon Linux / RHEL 系）或 **apt**（Ubuntu / Debian 系）——用于装 freeze / webp / tmux / librsvg + 字体。
5. **一个飞书账号**，能登录[飞书开放平台](https://open.feishu.cn/)创建自建应用（见下方〈飞书应用配置〉）。

```
飞书手机 → 飞书服务器 → WebSocket → bridge.py → tmux → Claude Code
                                        ↑ Stop hook 截图回传
```

> **多机模式（Roadmap）**：多机 Hub + Agent 模式尚未验证，作为 roadmap 保留在
> [`experimental/hub/`](experimental/hub/)，当前不支持。本 README 只覆盖单机模式。

## 代码结构

工具代码在 `ccremote/` 包里（`config` / `feishu` / `signals` / `tmux` / `screenshot`），
`bridge.py`、`hook_notify.py` 是薄入口。`cc-remote install` 会把整个包拷到
`~/.cc_remote/bin/`，入口脚本从旁边 `import ccremote`。

## 安装（cc-remote CLI，推荐）— macOS

> Linux / EC2 用户请直接跳到下方〈Linux / EC2 安装〉。本节是 macOS 流程（launchd + Homebrew）。

把工具装到 `~/.cc_remote/`（自包含的家：脚本、`.env`、数据都在这），之后在**任意项目目录**一条命令开工——不再绑定本 repo 目录。

```bash
# 0. 先装依赖（freeze 必需；webp/tmux 见下方说明）
brew install charmbracelet/tap/freeze webp tmux
pip install lark-oapi python-dotenv

# 1. 在本 repo 里安装（拷 ccremote 包 + 入口脚本到 ~/.cc_remote/bin、建目录、生成 .env 模板）
python3 cc-remote install
# 把 ~/.cc_remote/bin 加进 PATH（cc-remote 安装在这里；install 末尾也会提示这条）
echo 'export PATH="$HOME/.cc_remote/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc

# 2. 填飞书凭证 + Claude 启动命令
$EDITOR ~/.cc_remote/.env        # FEISHU_APP_ID / SECRET / ALLOWED_USERS / TMUX_SESSION
                                 # CLAUDE_CMD=claude --dangerously-skip-permissions
                                 #   ↑ 远程遥控必须带 bypass,否则会卡权限弹窗
                                 # ALLOWED_USERS 怎么填见下方〈飞书应用配置〉最后一步

# 3. 启动常驻 bridge（launchd：登录自启、崩溃自动重拉）
cc-remote bridge start

# 4. 自检：依赖、凭证、bridge 是否都就绪
cc-remote doctor

# 5. 在任意项目目录开工
cd ~/some/project
cc-remote setup                  # 合并 Stop hook + 起 tmux,用 .env 的 CLAUDE_CMD 启动 Claude
#   --claude-cmd "claude --resume xxx"   临时覆盖本次启动命令
#   --no-launch                          只配 hook,不起 tmux/claude(自己手动起)
tmux attach -t cc                # 本地接入（可选）

# 排查 / 管理
cc-remote bridge status|stop
```

依赖说明：
- `pip install lark-oapi python-dotenv` —— **必需**（bridge / hook 全靠它们）。
- `freeze`（`brew install charmbracelet/tap/freeze`）—— **必需**：把终端渲染成图片（无需 GUI，屏幕锁了也能截）。缺了截图 / `/read` 会失败。
- `webp`（`brew install webp`，提供 `cwebp`）—— **可选**：把截图转 WebP（更小更快）。缺了会自动降级发 PNG，功能不受影响、只是图大些。
- `tmux`（`brew install tmux`）—— **必需**：Claude 跑在 tmux session 里。
- `cc-remote install` / `doctor` 都会检查这些并给出缺失提示，装完跑一次 `doctor` 最稳妥。

> 工作机制:`setup` 往**项目级** `.claude/settings.json` 合并两样东西:(1) Stop hook（指向固定的
> `~/.cc_remote/bin/hook_notify.py`），所以只有你 `setup` 过的目录才会自动截图回传，纯本地用的其他
> 目录不受打扰；(2) `permissions.deny: ["AskUserQuestion"]`——禁用 Claude 的交互式提问,因为手机端
> 点不了那种弹窗。`setup` 是**合并而非覆盖**——已有的 `.claude/settings.json` 配置会保留,重复跑也
> 不会产生重复 hook。

## Linux / EC2 安装

在 **Amazon Linux 2023** 与 **Ubuntu 24.04**、**x86_64 与 arm64（Graviton）** 上均已实测。与 macOS 的差别只有两处：**依赖用发行版包管理器装**、**常驻 bridge 走 systemd 而非 launchd**。核心代码、飞书配置、`setup`/`/switch` 等用法完全一致——配完依赖后，下方〈飞书应用配置〉及之后的章节通用。

> 典型场景是云上的无头（headless）服务器（如 EC2）：终端截图由 `freeze` 纯软件渲染，**不需要 X11 / 显示器 / GUI**。

### 1. 装依赖（按发行版选一套）

Linux 上有两个 macOS 没有的关键点：

- **`rsvg-convert`（librsvg）是中文渲染的命脉，不是可选项。** `freeze` 若在 PATH 上找到 `rsvg-convert` 就用它（经 fontconfig 读系统字体、逐字形 fallback），否则退回只认拉丁字母的内嵌引擎——届时**终端里的中文、UI 符号会变成豆腐块**。macOS 因为一般装过 librsvg 不暴露这点，headless Linux 必须显式装。
- **要装字体**：CJK、TUI 符号（`✶ ❯ ⏵`）、emoji 各属不同 Unicode 区段，需不同字体覆盖。彩色 emoji 本渲染链不支持，最佳效果是「单色轮廓」（装单色 emoji 字体即可消除豆腐块）。

**Amazon Linux 2023 / RHEL 系（dnf）：**

```bash
# tmux + cwebp + Python 工具链
sudo dnf install -y tmux libwebp-tools python3-pip

# freeze（来自 charm 官方 yum repo；含 aarch64 build）
sudo tee /etc/yum.repos.d/charm.repo >/dev/null <<'EOF'
[charm]
name=Charm
baseurl=https://repo.charm.sh/yum/
enabled=1
gpgcheck=1
gpgkey=https://repo.charm.sh/yum/gpg.key
EOF
sudo dnf install -y freeze

# 渲染依赖：librsvg（中文命脉）+ 字体（CJK / 符号 / emoji）
sudo dnf install -y librsvg2-tools fontconfig \
  google-noto-sans-cjk-ttc-fonts \      # 中文（注意 -ttc 后缀）
  google-noto-sans-symbols2-fonts \     # ⏵ U+23F5 唯一来源
  dejavu-sans-fonts \                   # ✶ ❯ 等符号兜底
  google-noto-emoji-fonts               # emoji 单色轮廓（消豆腐块）
sudo fc-cache -f
```

**Ubuntu 24.04 / Debian 系（apt）：**

```bash
# tmux + cwebp + Python venv（包名与 dnf 不同：cwebp 是 webp，不是 libwebp-tools）
sudo apt-get update && sudo apt-get install -y tmux webp python3-pip python3-venv

# freeze（来自 charm 官方 apt repo；含 arm64 build）
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://repo.charm.sh/apt/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg
echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" | sudo tee /etc/apt/sources.list.d/charm.list
sudo apt-get update && sudo apt-get install -y freeze

# 渲染依赖：librsvg（-bin，不是 -tools）+ 字体
sudo apt-get install -y librsvg2-bin fontconfig \
  fonts-noto-cjk \          # 中文
  fonts-noto-core \         # 含 Noto Symbols2（⏵）
  fonts-dejavu \            # ✶ ❯
  fonts-noto-color-emoji    # emoji
sudo fc-cache -f
```

> apt 源那行字面的 `* *` 是 charm flat-repo 布局，照抄、别替换成 dist/component。

### 2. 创建 venv 装 Python 依赖

部分发行版（Ubuntu 24.04 等）开启了 PEP 668「externally-managed」，**裸 `pip install` 进系统 python 会被拒**。统一用 venv，既绕开这道闸、也不污染 OS 自带的 `python3`：

```bash
python3 -m venv ~/.cc_remote_venv
~/.cc_remote_venv/bin/pip install lark-oapi python-dotenv
```

记下这个解释器路径 `~/.cc_remote_venv/bin/python3`——下面安装、起 bridge、配 hook 都要用它。

### 3. 安装 + 配置（**注意：用 venv 的 python 跑 `cc-remote`**）

> **关键**：`cc-remote` 命令本身要读 `.env`，依赖 `python-dotenv`。所以**跑 `cc-remote` 时要用上面 venv 里的 python**，而不是系统 `python3`——否则它读不到 `.env`，会误报「凭证缺失或是占位符」。

```bash
# 在本 repo 目录里安装（拷代码到 ~/.cc_remote/bin、建目录、生成 .env 模板）
~/.cc_remote_venv/bin/python3 cc-remote install
echo 'export PATH="$HOME/.cc_remote/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc

# 填飞书凭证 + Claude 启动命令 + 指定带依赖的解释器
$EDITOR ~/.cc_remote/.env
#   FEISHU_APP_ID / FEISHU_APP_SECRET / ALLOWED_USERS / TMUX_SESSION
#   CLAUDE_CMD=claude --dangerously-skip-permissions   ← 远程遥控必须带 bypass
#   CC_HOOK_PYTHON=/home/<你>/.cc_remote_venv/bin/python3
#     ↑ 让 Stop hook 用带 lark_oapi 的解释器（系统 python3 没装依赖会静默失败）
```

`CC_HOOK_PYTHON` 必须填**绝对路径**、指向上面那个 venv python。它有两个作用：(1) Stop hook 用它截图回传；(2) `cc-remote` 自身也优先用它跑（PATH 里 `cc-remote` 的 shebang 是系统 python，但它会读 `CC_HOOK_PYTHON` 来执行需要依赖的子任务）。最稳的习惯：**所有 `cc-remote ...` 命令都写成 `~/.cc_remote_venv/bin/python3 ~/.cc_remote/bin/cc-remote ...`**，或确保当前 shell 的 `python3` 就是 venv 那个。

### 4. 起 systemd 常驻 bridge

`cc-remote bridge start` 在 Linux 上会**生成 systemd system service** `/etc/systemd/system/ccremote-bridge.service` 并 `enable --now`（开机自启 + 立即启动 + 崩溃自动重拉），等价于 macOS 的 launchd。它**以你的普通用户身份运行**（非 root），日志写到 `~/.cc_remote/bridge.log`：

```bash
~/.cc_remote_venv/bin/python3 ~/.cc_remote/bin/cc-remote bridge start
~/.cc_remote_venv/bin/python3 ~/.cc_remote/bin/cc-remote doctor    # 自检依赖/凭证/服务
~/.cc_remote_venv/bin/python3 ~/.cc_remote/bin/cc-remote bridge status

# 也可直接用 systemctl 观察（读状态不需 sudo）
systemctl status ccremote-bridge.service
journalctl -u ccremote-bridge.service -f
```

> `bridge start/stop` 内部会调 `sudo systemctl`（写 unit、daemon-reload、enable/disable），所以这两条命令会触发一次 sudo 提权；`status` 与 `journalctl` 只读、不需要 sudo。

之后在任意项目目录 `cc-remote setup`（同 macOS）就能开工。`doctor` 在 Linux 上会额外检查 `en_US.UTF-8` locale 是否存在（缺则中文路径/文本可能出错；Ubuntu 可 `sudo locale-gen en_US.UTF-8`）。

### Linux 依赖速查

| 依赖 | Amazon Linux 2023（dnf） | Ubuntu 24.04（apt） | 必需性 |
|---|---|---|---|
| tmux | `tmux` | `tmux` | 必需 |
| freeze | charm yum repo | charm apt repo | 必需（终端→图片）|
| cwebp | `libwebp-tools` | `webp` | 可选（缺则降级发 PNG）|
| **rsvg-convert** | `librsvg2-tools` | `librsvg2-bin` | **必需**（中文渲染命脉）|
| CJK 字体 | `google-noto-sans-cjk-ttc-fonts` | `fonts-noto-cjk` | 含中文时必需 |
| 符号字体（⏵ 等）| `google-noto-sans-symbols2-fonts` + `dejavu-sans-fonts` | `fonts-noto-core` + `fonts-dejavu` | Claude TUI 必需 |
| emoji（单色轮廓）| `google-noto-emoji-fonts` | `fonts-noto-color-emoji` | 可选（消豆腐块）|
| Python 依赖 | venv + `lark-oapi python-dotenv` | 同左（PEP 668 强制 venv）| 必需 |

> **彩色 emoji 说明**：`freeze` 的渲染链不支持彩色 emoji（位图/矢量彩色字形层），最佳效果是单色轮廓。装了单色 emoji 字体后 emoji 显示为黑白轮廓、不再是豆腐块——这是 headless Linux 上的预期最佳状态，不影响中文与 UI 符号（那些已能完整正常渲染）。

## 飞书端使用

| 命令 | 作用 |
|------|------|
| `/read` | 截取**当前 active 项目**的终端屏幕并以图片发回（解卡时看为什么卡住）|
| `/status` | 查看当前 active 项目的 session 名、是否在线 |
| `/switch <别名>` | 切换当前 active 项目（多项目路由，见下节）|
| `/projects` | 列出已注册项目，★ 标记当前 active，🔗 标记已绑群 |
| `/bind <别名>` | （群里发）把当前群绑定到项目，见〈群路由〉|
| `/unbind` | （群里发）解除当前群绑定 |
| `/whoami` | （群里发）查看当前群绑的项目 |
| `/enter` | 在终端按回车（确认弹窗 / 选 Yes / 提交）|
| `/esc` | 在终端按 ESC（取消弹窗 / 退出模式）|
| `/up` `/down` | 在终端按上/下方向键（在多选弹窗里移动光标）|
| `/ctrl-c` | 在终端按 Ctrl+C（中断当前运行）|
| 普通文字 | 转发到当前 active 项目的 tmux session |
| `# ...` | 备注，不转发 |

> 控制键（`/enter` `/esc` `/up` `/down` `/ctrl-c`）是远程托底:即便开了 bypass，万一某个
> 命令卡在需要键盘操作的弹窗,先 `/read` 看屏幕,再用这些键把它解开。
>
> 控制键还会**按需补信号**:若当前没有任何命令在等待截图(例如你在电脑上敲好提示词、
> 再从飞书 `/enter` 启动 Claude),控制键会顺手挂一个信号,让 Claude 跑完后把结果截图
> 回传到这条控制键消息;若已有命令在等(从飞书发起的),则只推进它、不重复。

## 多项目路由（/switch）

一个 bridge 可以管多个项目，每个项目是一个长驻 tmux session（各自独立的 Claude + 上下文）。
飞书消息默认发给**当前 active 项目**；用 `/switch` 改变路由指向，`/projects` 查看列表。

```bash
# 给项目起别名并配 hook（在项目目录下；--name 即注册进多项目 registry）
cd ~/dev/projectA
cc-remote setup --name projA                 # session 名默认取别名，可用 --session 覆盖

# 注册一个已经在跑的 session（不碰它的 settings.json / 不重起 tmux）
cc-remote projects add projB --session cc-projB --dir ~/dev/projectB

cc-remote projects list                      # 列出所有项目 + 在线状态
cc-remote projects rm projB                   # 注销
```

飞书端：

- `/projects` —— 列出已注册项目，★ 标记当前 active，●live/○dead 标在线状态。
- `/switch <别名>` —— 把 active 指针切到该项目；之后普通文字、`/read`、控制键都路由到它。
  - 目标 session 必须已在运行（Phase A：`/switch` 只改路由，不会替你起/恢复 session）。
- 不带 `--name` 的 `setup` 仍是单项目模式（兼容老行为），消息路由到 `TMUX_SESSION`（默认 `cc`）。

## 群路由（多项目并行）

默认你和 bot 在一个私聊里，用 `/switch <别名>` 在项目间切换（同一时刻聊一个）。
如果你想**同时**盯多个项目，可以给每个项目建一个飞书群、把 bot 拉进去，让群和项目一一绑定——
之后在哪个群发消息就直达哪个项目，互不干扰，Claude 的回复/截图也只回到对应群。

### 一次性准备（飞书后台）

1. 给应用**订阅群消息**：事件 `im.message.receive_v1` 对群聊生效（与私聊同一事件）。
2. 加权限 **`im:chat`**（更新群信息）——用于 `/bind` 时自动把群名改成项目名。
   未开通也能用，只是不会自动改名（你可手动改群名）。

### 绑定一个群

1. 在电脑上为该项目 setup：`cc-remote setup --name <别名>`（注册到项目表）。
2. 新建一个飞书群，把 bot 拉进去。
3. 在群里发 `/bind <别名>`。bot 会把这个群绑到该项目，并尝试把群名改成 `🤖 <别名>`。

之后这个群里发的任何文字都直接进该项目，无需 `/switch`、无需前缀。

### 群内命令

| 命令 | 作用 |
|---|---|
| `/bind <别名>` | 把当前群绑定到项目（并自动改群名）|
| `/unbind` | 解除当前群的绑定（改回默认路由）|
| `/whoami` | 查看当前群绑的是哪个项目 |
| `/projects` | 全局项目列表（🔗 标记已绑群的项目）|

> 私聊不受影响：未绑定的会话（私聊，或没 `/bind` 过的群）仍走 `/switch` + active 指针的老逻辑。
> 群里若需要 @bot 才能触发，命令前缀照常识别（`@bot /bind web` 等价于 `/bind web`）。

## 富文本回复（飞书卡片 markdown）

Claude 每轮的回复正文与 `/projects` 列表以飞书 **消息卡片（card JSON v2）** 的
markdown 组件发送，标题、**粗体**、`行内代码`、代码块、有序/无序列表、表格、引用、
链接都会被渲染成真正的富文本。其余命令回执（如 `/switch`、`/bind` 的结果）仍是纯文本。

- 发送卡片复用既有的 `im:message:send_as_bot` 权限，**无需额外 scope**。
- 任何一条卡片发送失败时，会自动降级为纯文本重发，保证消息不丢。
- 回复过长会被截断并提示「完整内容见截图」（截图照常发送）。卡片可容纳的字符数由
  `MAX_CARD_CHARS` 控制（默认 8000，保守值；纯文本降级仍按 `MAX_TEXT_CHARS`，默认 4000）。
- 回复卡片底部带一行状态页脚（仿 Claude Code 的 statusline）：`🤖 <模型> · ctx <占比>%
  (<已用>/<上限>) · ⎇ <分支>`，缺数据的段会自动省略。用 `CARD_FOOTER=false` 关闭整行页脚。
  上下文占比的分母由 `CONTEXT_WINDOW_SIZE` 控制（默认 200000；用 1M 上下文请设为 `1000000`）。

## 飞书应用配置

1. [飞书开放平台](https://open.feishu.cn/) → 创建企业自建应用
2. 「凭证与基础信息」页拿到 **App ID** 和 **App Secret** → 填进 `~/.cc_remote/.env` 的
   `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
3. 添加「机器人」能力
4. 事件订阅 → 选择 **长连接 / WebSocket 模式**（无需公网 IP，不要选「发送到开发者 URL」）
5. 订阅事件：`im.message.receive_v1`
6. 权限：
   - `im:message`（收发单聊/群组消息，含消息 reaction）
   - `im:message:send_as_bot`（以机器人身份回复/发图——回执、截图、`/read` 必需）
   - `im:resource`（下载消息中的图片——接收图片功能必需）
7. **发布版本**（权限/事件改完必须发版才生效）；企业租户还需确认应用「可用范围」包含你自己
8. 在飞书里**单独私聊**机器人即可开始用（单项目默认就是私聊控制；多项目并行见〈群路由〉，需把 bot 拉进群）

### 拿到你自己的 open_id（填 `ALLOWED_USERS`）

`ALLOWED_USERS` 限定谁能遥控（见〈安全〉）。它要填的是**你的飞书 open_id**（形如 `ou_...`，且**每个应用各不相同**）。最简单的拿法——让 bridge 帮你打出来：

1. 先把 `.env` 里的 `ALLOWED_USERS` **留空**，`cc-remote bridge start`。
2. 在飞书里给机器人**随便发一条消息**。
3. 读日志拿 open_id：
   ```bash
   grep 'open_id' ~/.cc_remote/bridge.log | tail -1
   ```
   会看到 `Message from open_id: ou_xxxxxxxx...`，那串 `ou_...` 就是你的。
4. 把它填回 `.env` 的 `ALLOWED_USERS`，`cc-remote bridge stop && cc-remote bridge start` 重启生效。

> 留空期间 = 任何人都能遥控,所以**拿到后尽快填上**。
> ⚠️ `ALLOWED_USERS` 留空期间**不要把 bot 拉进任何群**——群里任何成员的消息都会被打进 Claude。先填好 `ALLOWED_USERS` 再用〈群路由〉。

> 没收到回复? 先看运行机器的日志:出现 `Sent to tmux` 即代表指令已送达,只是缺 `send_as_bot` 权限发不出回执。

## 发图给 Claude

私聊机器人**发图片** → 自动下载到 `CC_REMOTE_DIR/images/` → 机器人回执「📷 图片已接收 (共 N 张待处理)」。
**下一条文字**消息会自动带上这些图片路径（`[图片] <路径>`），Claude Code 即可用 Read 读图。
多张图会累加，直到被下一条文字消费。

## 执行结果自动截图回传（Stop hook）

远程发命令后，无需手动 `/read`，自动收到执行结果：

1. bridge 收到命令 → 给你的消息贴「处理中」reaction（`REACTION_PROCESSING`，默认 `OnIt`）
   → 在 `signals/` 写一个**每命令一个**的信号文件 → 转发进 tmux
2. Claude Code 执行完该轮 → **Stop hook** 把终端渲染成图片发回飞书；**确认发送成功后**
   才把 reaction 换成「完成」（`REACTION_DONE`，默认 `DONE`）
3. 若截图生成/发送失败 → reaction 换成「失败」（`REACTION_ERROR`，默认 `CrossMark`）并回一条
   文字说明，绝不让消息卡在「处理中」

> reaction 显示成什么图标取决于飞书对这些 `emoji_type` 的渲染；合法值见飞书「表情文案说明」文档。
> emoji 旁边会显示机器人名（飞书客户端固定行为，无法去掉）。

**前置依赖**（macOS）：

```bash
brew install charmbracelet/tap/freeze   # 终端→图片渲染（无需 GUI，屏幕锁了也能截）
brew install webp                        # cwebp：把截图转 WebP，体积小、加载快、不损清晰度
```

> Linux 见〈Linux / EC2 安装〉——除 freeze/webp 外还需 **librsvg + Noto 字体**，否则截图里的中文/符号会变豆腐块。

**配置 Stop hook**：`cc-remote setup` 会把它合并进项目级 `.claude/settings.json`，命令为
`"${CC_HOOK_PYTHON:-python3}" "$HOME/.cc_remote/bin/hook_notify.py"`（指向安装好的入口，
脚本从旁边 `import ccremote`）。hook 自读 `.env`，只在「自己就是 `TMUX_SESSION` 里的那个
Claude」且有待处理信号时才发送——本地手敲命令、别的目录的 Claude 都不会打扰手机。

> 若 `python3` 不带 `lark_oapi` 依赖（例如系统 python 与装了依赖的解释器不是同一个），
> 把 `CC_HOOK_PYTHON` 设为带依赖的解释器路径并 export 到运行 Claude Code 的环境。

> 关键：Claude Code 必须运行在 `TMUX_SESSION`（默认 `cc`）这个 tmux session 里，hook 才能截到它的画面。
> 若 Claude 没在该 session 里运行，命令会被打进终端但永远不会有 Stop 事件——届时信号会在
> `SIGNAL_TTL_SEC`（默认 30 分钟）后过期清理。

> 截图尺寸：`cc-remote setup` 起的是 detached tmux session，默认几何为 **80×24**，截图会偏小、长行被截断。
> 想要更大画面,可在本地 `tmux attach -t cc` 后让客户端把 session 撑大,或自己用
> `tmux new-session -d -s cc -x 200 -y 50 -c <dir>`（带 `-x/-y`）先建好 session 再 `cc-remote setup --no-launch`。

## Proactive notifications: `cc-remote notify`

The Stop hook fires once per finished turn. If Claude kicks off a background
task and returns before it completes, the hook has already run — so the task's
result would never reach you. `cc-remote notify` fixes that: run it from inside
a controlled tmux session to push a notification card back to the chat that
issued the original command.

```bash
# positional message
cc-remote notify "load test done, p99 = 42ms"

# or pipe long output via stdin, with a custom header
echo "$REPORT" | cc-remote notify --title "🔔 nightly run"
```

The bridge records, per tmux session, the chat that last drove it, so notify
sends to the right place automatically — no chat id needed. Tell Claude to call
it when you hand off a long-running job:

> "Run the 30-min stress test in the background; when it finishes, run
> `cc-remote notify` to tell me the p99 latency."

## tmux 配置建议

```bash
# 应用推荐配置（优化鼠标滚动）
cat tmux.conf.recommended >> ~/.tmux.conf
tmux source ~/.tmux.conf
```

主要优化：
- 鼠标/触控板滚动支持
- vi 模式浏览（/ 搜索，Ctrl+U/D 翻页）
- 50000 行历史记录

## 网络要求

- bridge 主动连接飞书 WebSocket，无需公网 IP、无需开放任何端口。
- 远程机器（Mac 或 Linux）只要能访问外网即可。云上 headless 服务器（如 EC2）同样适用——bridge 是出站长连接，无需为它开任何入站端口。

## 安全

- `ALLOWED_USERS` 限制只有指定飞书 open_id 可以发送命令（留空 = 允许所有人，不建议）。
- 凭证只存放在 `~/.cc_remote/.env`（gitignored，不在 repo 里）。
- 远程遥控通常带 `--dangerously-skip-permissions`（`CLAUDE_CMD`）以避免卡在手机上点不了的
  权限弹窗——这等于让 Claude 在该 session 里跳过确认，只在你信任的机器/目录上这么用。

## License

MIT
