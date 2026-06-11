# remote-claude-control

飞书 → tmux → Claude Code 远程遥控工具（单机模式）。

## 用途

在飞书手机端用文字或语音输入，发送给飞书机器人后，自动转发到远程 Mac 上运行 Claude Code 的 tmux session；Claude 跑完一轮，Stop hook 自动把终端截图 + 回复文字发回飞书。

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

## 安装（cc-remote CLI，推荐）

把工具装到 `~/.cc_remote/`（自包含的家：脚本、`.env`、数据都在这），之后在**任意项目目录**一条命令开工——不再绑定本 repo 目录。

```bash
# 1. 在本 repo 里安装（拷 ccremote 包 + 入口脚本到 ~/.cc_remote/bin、建目录、生成 .env 模板）
python3 cc-remote install
ln -sf ~/.cc_remote/bin/cc-remote ~/.local/bin/cc-remote   # 加进 PATH
# 若 ~/.local/bin 不在 PATH：在 shell rc 里加 export PATH="$HOME/.local/bin:$PATH"

# 2. 填飞书凭证 + Claude 启动命令
$EDITOR ~/.cc_remote/.env        # FEISHU_APP_ID / SECRET / ALLOWED_USERS / TMUX_SESSION
                                 # CLAUDE_CMD=claude --dangerously-skip-permissions
                                 #   ↑ 远程遥控必须带 bypass,否则会卡权限弹窗

# 3. 启动常驻 bridge（launchd：登录自启、崩溃自动重拉）
cc-remote bridge start

# 4. 在任意项目目录开工
cd ~/some/project
cc-remote setup                  # 合并 Stop hook + 起 tmux,用 .env 的 CLAUDE_CMD 启动 Claude
#   --claude-cmd "claude --resume xxx"   临时覆盖本次启动命令
#   --no-launch                          只配 hook,不起 tmux/claude(自己手动起)
tmux attach -t cc                # 本地接入（可选）

# 排查 / 管理
cc-remote doctor                 # 自检依赖、凭证、bridge、当前目录是否已配
cc-remote bridge status|stop
```

依赖：`brew install charmbracelet/tap/freeze webp`、`pip install lark-oapi python-dotenv`。

> 工作机制:`setup` 把 Stop hook 写进**项目级** `.claude/settings.json`（指向固定的
> `~/.cc_remote/bin/hook_notify.py`），所以只有你 `setup` 过的目录才会自动截图回传，
> 纯本地用的其他目录不受打扰。`setup` 是**合并而非覆盖**——已有的 `.claude/settings.json`
> 配置会保留,重复跑也不会产生重复 hook。

## 飞书端使用

| 命令 | 作用 |
|------|------|
| `/read` | 截取当前终端屏幕并以图片发回（解卡时看为什么卡住）|
| `/status` | 查看 tmux session 是否在线 |
| `/enter` | 在终端按回车（确认弹窗 / 选 Yes / 提交）|
| `/esc` | 在终端按 ESC（取消弹窗 / 退出模式）|
| `/up` `/down` | 在终端按上/下方向键（在多选弹窗里移动光标）|
| `/ctrl-c` | 在终端按 Ctrl+C（中断当前运行）|
| `/help` | 帮助 |
| 普通文字 | 转发到活跃机器的 tmux |
| `# ...` | 备注，不转发 |

> 控制键（`/enter` `/esc` `/up` `/down` `/ctrl-c`）是远程托底:即便开了 bypass，万一某个
> 命令卡在需要键盘操作的弹窗,先 `/read` 看屏幕,再用这些键把它解开。
>
> 控制键还会**按需补信号**:若当前没有任何命令在等待截图(例如你在电脑上敲好提示词、
> 再从飞书 `/enter` 启动 Claude),控制键会顺手挂一个信号,让 Claude 跑完后把结果截图
> 回传到这条控制键消息;若已有命令在等(从飞书发起的),则只推进它、不重复。

## 飞书应用配置

1. [飞书开放平台](https://open.feishu.cn/) → 创建企业自建应用
2. 添加「机器人」能力
3. 事件订阅 → 选择 **长连接 / WebSocket 模式**（无需公网 IP，不要选「发送到开发者 URL」）
4. 订阅事件：`im.message.receive_v1`
5. 权限：
   - `im:message`（收发单聊/群组消息，含消息 reaction）
   - `im:message:send_as_bot`（以机器人身份回复/发图——回执、截图、`/read` 必需）
   - `im:resource`（下载消息中的图片——接收图片功能必需）
6. **发布版本**（权限/事件改完必须发版才生效）
7. 在飞书里**单独私聊**机器人（代码只处理 p2p 单聊，不响应群里 @）

> 没收到回复? 先看运行机器的日志:出现 `Sent to tmux` 即代表指令已送达,只是缺 `send_as_bot` 权限发不出回执。

## 发图给 Claude

私聊机器人**发图片** → 自动下载到 `CC_REMOTE_DIR/images/` → 机器人回执「📷 已接收」。
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

**前置依赖**：

```bash
brew install charmbracelet/tap/freeze   # 终端→图片渲染（无需 GUI，屏幕锁了也能截）
brew install webp                        # cwebp：把截图转 WebP，体积小、加载快、不损清晰度
```

**配置 Stop hook**：`cc-remote setup` 会把它合并进项目级 `.claude/settings.json`，命令为
`"${CC_HOOK_PYTHON:-python3}" "$HOME/.cc_remote/bin/hook_notify.py"`（指向安装好的入口，
脚本从旁边 `import ccremote`）。hook 自读 `.env`，只在「自己就是 `TMUX_SESSION` 里的那个
Claude」且有待处理信号时才发送——本地手敲命令、别的目录的 Claude 都不会打扰手机。

> 若 `python3` 不带 `lark_oapi` 依赖（例如系统 python 与装了依赖的解释器不是同一个），
> 把 `CC_HOOK_PYTHON` 设为带依赖的解释器路径并 export 到运行 Claude Code 的环境。

> 关键：Claude Code 必须运行在 `TMUX_SESSION`（默认 `cc`）这个 tmux session 里，hook 才能截到它的画面。
> 若 Claude 没在该 session 里运行，命令会被打进终端但永远不会有 Stop 事件——届时信号会在
> `SIGNAL_TTL_SEC`（默认 30 分钟）后过期清理。

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
- 远程 Mac 只要能访问外网即可。

## 安全

- `ALLOWED_USERS` 限制只有指定飞书 open_id 可以发送命令（留空 = 允许所有人，不建议）。
- 凭证只存放在 `~/.cc_remote/.env`（gitignored，不在 repo 里）。
- 远程遥控通常带 `--dangerously-skip-permissions`（`CLAUDE_CMD`）以避免卡在手机上点不了的
  权限弹窗——这等于让 Claude 在该 session 里跳过确认，只在你信任的机器/目录上这么用。

## License

MIT
