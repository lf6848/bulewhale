# 大肥鱼（AstrBot + SnowLuma）项目说明

> 本文件是这个工作区（`D:\dsh-qq`）的"交接文档"：写清项目是什么、每个文件夹装了什么、做到哪一步、还剩什么、常用操作怎么做。
> 最后更新：2026-11-03

---

## 1. 这是什么

一台阿里云 ECS 上跑着两个容器：**SnowLuma**（真机 QQ 客户端 + OneBot 协议网关，跑在 Xvfb 里）和 **AstrBot**（聊天机器人框架）。
两者用 OneBot v11 反向 WS 连接，QQ 收到的消息经 SnowLuma 转给 AstrBot，AstrBot 调 DeepSeek / MiMo 生成回复再经 SnowLuma 发回 QQ。

```
手机QQ ──扫码登录──> [SnowLuma 容器]  QQ客户端(Linux, Xvfb :1) + Hook
                          │  OneBot WS  上联 ws://astrbot:6199/ws（SnowLuma 是 ws-client）
                          ▼
                    [AstrBot 容器]  平台适配器 aiocqhttp
                          │
        ┌─────────────────┼──────────────────┬─────────────────┐
        ▼                 ▼                  ▼                 ▼
   DeepSeek(主)      MiMo-vision(看图)   自研插件           日记/自我/记忆
   deepseek-chat     mimo-v2.6-flash    （见 §6）         （宿主机 cron 生成）
```

- 机器人 QQ：**3952927705**，昵称「大肥鱼」，主人在 **1034867860**。
- 主要在用的群：**726921160**（6 人）。
- 服务器：`118.178.98.186`（华东1 杭州，2 核 2G，Ubuntu 22.04，Docker 29.9.2）。

---

## 2. 现在怎么用

三个 Web 入口都只监听服务器 `127.0.0.1`，**靠本机 SSH 隧道**暴露到本地：

| 用途 | 地址 | 账号 / 密码 |
|---|---|---|
| AstrBot 控制台 | http://127.0.0.1:6185 | 用户名 `lflove02`（密码已被用户改过，非默认值） |
| SnowLuma 面板 | http://127.0.0.1:15099 | `admin` / `Qjy_20060610` |
| noVNC（看 QQ 桌面、扫码） | http://127.0.0.1:16081/vnc.html | 密码 `snow2026` |

> 端口映射：本地 `6185→6185`、`15099→服务器 5099`、`16081→服务器 6081`（本地 5099 曾被别的程序占用，所以错开）。三个地址复制时**别把中文说明粘进链接**，否则 noVNC 会 404。

**隧道不在了（地址打不开）怎么办**

```bat
schtasks /run /tn "dshqq-tunnel"
```

或双击 `D:\dsh-qq\start-tunnel.cmd`（脚本会先试计划任务，失败就直接起 ssh）。验证：`netstat -ano | findstr "6185"` 看到 LISTENING 即可。
隧道本体是 `tunnel-run.cmd`（断线 5 秒后自动重连），由计划任务 `dshqq-tunnel` 拉起。

> **重启电脑后隧道不会自己起来**（计划任务是一次性触发，不是开机自启）。开机后双击一次 `start-tunnel.cmd` 即可。

**本地管理面板（可选）**：双击 `启动管理面板.bat` → 打开 http://127.0.0.1:8770 ，里面聚合了三个入口、服务器状态、机器人信息与运行日志。

---

## 3. 服务器上的东西

### 容器

| 容器 | 镜像 | 端口（都绑 127.0.0.1） | 备注 |
|---|---|---|---|
| `astrbot` | `soulter/astrbot:latest`（v4.29.3） | 6185 WebUI、6199 OneBot WS | 数据卷 `/opt/astrbot/data`；cgroup 上限 500M/800M |
| `snowluma` | `motricseven7/snowluma:latest` | 6081 noVNC、5900 VNC、5099 WebUI、3000 HTTP API、3001 WS | 特权参数 `SYS_PTRACE`、`seccomp=unconfined`；cgroup 上限 1000M/1600M |

两个容器同一 `qqnet` 网络，AstrBot 用容器名互访（`ws://astrbot:6199/ws`）。

### 目录

| 路径 | 内容 |
|---|---|
| `/opt/astrbot/data/cmd_config.json` | AstrBot 主配置（带 UTF-8 BOM，读写必须 `utf-8-sig`） |
| `/opt/astrbot/data/plugins/<名>/` | 插件源码（自研 6 个 + 上游若干） |
| `/opt/astrbot/data/config/<插件>_config.json` | 各插件配置（多数热加载） |
| `/opt/astrbot/data/plugin_data/` | 插件运行数据（数据库、状态文件） |
| `/opt/astrbot/data/data_v4.db` | AstrBot 主库（含 `platform_message_history` 全量聊天记录） |
| `/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db` | 长期记忆库（WAL 模式，**备份必须 db+wal+shm 三个一起**） |
| `/opt/astrbot/data/plugin_data/astrbot_brain/` | `self.md` 自我、`diary/` 日记、`self_history/` 历史版本、`diary_index.json`、`recall_log.json`、`self_log.json` |
| `/usr/local/bin/` | `health.sh`、`mem-watchdog.sh`、`memory-prune.py`、`brain-night.py`、`snapshot.sh`、`restore.sh`、`host-bootstrap.sh` |
| `/var/backups/dsh-qq/` | 服务器端快照（每天 04:50，保留 10 份） |
| `/var/log/` | `health.log`、`mem-watchdog.log`、`brain-night.log`、`snapshot.log`、`memory-prune.log` |

### cron

```
*/2  *  * * *   mem-watchdog.sh                    内存看门狗（可用<80MB 或 swap>1100MB 就重启容器）
*    *  * * *   health.sh                          每分钟记录内存/负载/容器占用
5    4  * * *   docker restart snowluma            每天重启清 Chromium 泄漏（QQ 自动重登，不用扫码）
40   4  * * *   brain-night.py                     写日记 + 修订自我
50   4  * * *   snapshot.sh                        打快照
30   5  * * 7   memory-prune.py --apply ...        每周日清理记忆库（超 90MB 删到 70MB）
```

---

## 4. 本工作区 `D:\dsh-qq` 目录说明

### 根目录

| 文件 | 说明 |
|---|---|
| `id_deploy` / `id_deploy.pub` / `_dsh-aa.pem` | 服务器密钥（`id_deploy` 是 pem 复制出来的副本，给 MSYS ssh 用） |
| `key_ssh` | 同一把私钥的副本，**ACL 已收紧**成仅当前用户可读 —— Windows OpenSSH 只认这个 |
| `sshx` | 一行 ssh 包装脚本：`./sshx '<命令>'` 直接跑服务器命令，日常最常用 |
| `tunnel-run.cmd` | 隧道本体（断线自动重连），计划任务 `dshqq-tunnel` 调它 |
| `tunnel.cmd` / `tunnel.sh` | 早期单次隧道脚本（保留备用，会写 `tunnel.log`） |
| `start-tunnel.cmd` | 一键启动隧道（`schtasks /run`） |
| `backup.ps1` | 本地备份主逻辑：拉服务器快照 + 打包本工作区 + 轮转（本地留 14 份） |
| `backup.bat` | 手动双击备份（转调 `backup.ps1`，纯 ASCII 防编码坑） |
| `backup-loop.cmd` / `backup-silent.cmd` | 原先开机自启的循环备份（**2026-11-03 已按要求关闭开机自启**） |
| `启动管理面板.bat` | 打开本地管理面板（含"面板已在跑就只开浏览器"的逻辑） |
| `add_provider.py`、`fix_ws.py`、`wire.py`、`rescue.sh` | 早期一次性脚本（配 provider、修 ws 配置、应急），留档 |
| `shot*.png` | 早期排查 noVNC/QQ 登录时的截图 |

### `panel/` —— 本地管理面板

| 文件 | 说明 |
|---|---|
| `server.ps1` | 纯 ASCII 的 PS 5.1 后端；`TcpListener` 手写 HTTP 监听 8770，`/api/status` 单次 ssh 拉全部数据（4 秒缓存） |
| `index.html` | 面板页面：三入口卡片、服务器状态、机器人信息、日志双标签 |
| `health.sh`、`mem-watchdog.sh` | 与服务器 `/usr/local/bin/` 同名脚本的本地副本（改完要手动同步上去） |
| `_probe.ps1` | 早期探针，可删 |

### `docs/` —— 设计文档

| 文件 | 说明 |
|---|---|
| `遗忘树设计.md` | 记忆层 v5 设计：强度公式、有效强化、事实更新字段、三路召回、权限开关、验收指标 |
| `三层记忆设计.md` | 日记 / 自我 / 事实三层设计：选材表、修订约定、token 预算、已知缺口 |
| `迁移到新服务器.md` | 换机步骤：装 docker → 还原快照 → 跑 host-bootstrap → 改 4 处 IP → 验收清单 |
| `replay/questions.jsonl` | 20 题回放题集（记忆检索回归用） |

### `tmp/` —— 插件源码与调试脚本（**真正需要备份的是这里**）

| 路径 | 说明 |
|---|---|
| `tmp/brain-night.py` | 夜间任务源码（日记 + 自我），部署到 `/usr/local/bin/brain-night.py` |
| `tmp/brain_read/` | 插件 `astrbot_brain_read`（注入自我与日记）+ 桩测试 |
| `tmp/memory_shadow/` | 插件 `astrbot_memory_shadow`（记忆 v2 影子/灰度读路径）+ `engine.py` 引擎 + 验收/回放脚本 |
| `tmp/proactive_v2/` | 插件 `astrbot_proactive_v2`（主动消息）+ 29 项桩测试 |
| `tmp/short_recall_main.py` | 插件 `astrbot_short_recall`（48 小时短期回忆） |
| `tmp/group_attention_main.py` | 插件 `astrbot_group_attention`（判断群里是否在叫它） |
| `tmp/quote_focus_main.py` | 插件 `astrbot_quote_focus`（把引用内容提到正文前面） |
| `tmp/snapshot.sh`、`tmp/restore.sh`、`tmp/host-bootstrap.sh`、`tmp/memory-prune.py` | 服务器运维脚本的本地源文件 |
| `tmp/brain_read/_stub/`、`tmp/proactive_v2/_data/` | 桩测试用的假数据目录（可忽略） |
| `tmp/*.py` 其余 | 一次性诊断/测量脚本（`forget_check.py`、`weekly_report.py`、`prod_perm_check.py`、`_measure*.py` 等），保留以便复现结论 |

### `backup/` —— 本地备份仓

| 内容 | 说明 |
|---|---|
| `snapshot-YYYYMMDD-HHMMSS.tar.gz` | 服务器全量快照（约 12MB，含插件、配置、记忆库、日记/自我、bin 脚本、crontab、容器信息） |
| `workspace-YYYYMMDD-HHMM.zip` | 本工作区源码打包（`docs/ tmp/ panel/` + 根目录脚本，约 160KB） |
| `brain-latest/` | 从最新快照解出来的可读副本：`自我.md`、`日记\`、`自我历史\`、`self_log.json` 等 |

### `_backup/`

`SnowLuma-local-20261026/`：已卸载的**本地** SnowLuma 的配置存档（与服务器无关，留档用）。

---

## 5. 模型与凭据

| 项 | 值 |
|---|---|
| 主模型 | `deepseek-chat`（`https://api.deepseek.com/v1`，key 在 `cmd_config.json`） |
| 视觉模型 | `mimo-v2.6-flash`（`https://api.xiaomimimo.com/v1`），作为 `fallback_provider_ids` 与图片字幕 provider |
| 关键约定 | provider 的 `modalities` 必须含 `"tool_use"`，否则**整份工具列表被静默清空**（搜索/记忆工具全失效，日志不报错） |
| OneBot HTTP | `http://127.0.0.1:3000`；凭据仅保存在服务器侧，不进入仓库 |
| OneBot WS | `ws://snowluma:3001`；凭据仅保存在服务器侧，不进入仓库 |

> 提交后的 `memory-prune.py` 从运行环境读取 `ONEBOT_TOKEN`。部署更新前，请在服务器的任务运行环境中配置该变量；不要将令牌重新写回源码或文档。

---

## 6. 自研插件一览

| 插件 | 作用 | 配置 | 数据 |
|---|---|---|---|
| `astrbot_proactive_v2` | 主动消息：自己选题、自己刷热榜、开口前二次判断；私聊+群聊双目标 | `astrbot_proactive_v2_config.json` | `proactive.db`、`interests.md` |
| `astrbot_brain_read` | 把 `self.md`（每轮）和日记（按时间/主题命中）注入 prompt | `astrbot_brain_read_config.json` | 读 `astrbot_brain/` |
| `astrbot_short_recall` | 近 48 小时短期回忆（只读时间窗检索 + LLM 工具） | `astrbot_short_recall_config.json` | 只读主库 |
| `astrbot_group_attention` | 判断群里是不是在叫它（别名/引用/@别人/「你」→ LLM 判定） | `astrbot_group_attention_config.json` | `learned_aliases.json` |
| `astrbot_quote_focus` | 把被引用的消息搬到正文前面，避免模型忽略 | `astrbot_quote_focus_config.json` | 无 |
| `astrbot_memory_shadow` | 记忆 v2 影子 + 白名单灰度读路径（注入 `<v2_memory>` 块） | `astrbot_memory_shadow_config.json` | `shadow_log`、`memories_shadow` |
| 上游 `astrbot_plugin_memory_system` | 长期事实记忆（Zxin-Pro v1.2.0，已改提炼提示词与阈值） | `astrbot_plugin_memory_system_config.json` | `memory_system.db` |
| 上游 `astrbot_plugin_proactive_chat` | 旧主动消息（**自动触发已关**，仅保留其 Web 管理端） | — | — |

---

## 7. 进度

### 已完成

1. **部署**：服务器环境（4G swap、swappiness、oomd、镜像加速、qqnet、容器内存上限）→ SnowLuma + AstrBot 跑通 → QQ 扫码登录（UIN 3952927705）→ OneBot 双向打通。
2. **稳定性**：早期每天被内存打崩（2G 机器 + QQ 客户端），做了三层防护（cgroup 上限、每 2 分钟看门狗、systemd-oomd），之后没再整机失联；QQ 重启后自动重登、不需要重新扫码。
3. **访问与运维**：SSH 隧道常驻（含断线重连）、本地管理面板（三入口 + 状态 + 日志）、本地/服务器双层备份（每天快照 + 本地 zip）、迁移文档、`host-bootstrap.sh` 一键复刻宿主环境。
4. **模型能力**：DeepSeek 主模型 + MiMo 视觉替补（看图/表情包）；修好 `modalities` 缺 `tool_use` 导致工具全失效的老问题；联网搜索（anysearch 匿名）可用。
5. **人格与记忆三层**：
   - 人格提示词瘦身 2505→807 字（身份与边界由提示词兜底，性格交给 self）；
   - `self.md` 五段、每轮注入（白名单内），夜间自动修订（diff 驱动、允许零修改、可回滚历史）；
   - 日记层：每天 04:40 生成，分层翻阅（昨天全文/前几天一句/按主题或日期定位）；修掉了"读不到对话导致日记重复"的 UTC/TEXT 比较 bug，并重写了 10-28~11-01 五篇；
   - 事实层：长期记忆 144 条（summary 119 + 事实 25），支持跨场景可见、`/reset` 不清记忆。
6. **主动消息**：从上游插件换成自研 v0.4.1 —— 90 分钟均值（30–120 指数分布）、9–23 点、每天≤8 条、自己刷热榜≤3 条、在意的事≤1 条、开口前 veto 二次判断、支持私聊 + 群聊双目标（群里有人说话就不插话、私事不进群）。
7. **群聊行为**：@别人不再误判成叫它；引用消息会被提到正文前；能识别"你"指向谁。

### 进行中 / 待办

| 事项 | 状态 |
|---|---|
| 记忆 v2 灰度 | `read_path_v2` 只对 1034867860 开，`write_path_v2`/`maintain_v2` 仍关；满七天评估后再决定是否切写 |
| 三个检索参数 | **冻结中**：注入上限 5→3、称呼类词降权、importance 分档校准 —— 等复盘一起定 |
| 群聊主动消息的噪声 | 群聊 3 条/天与私聊独立，最坏一天 9 条；观察后可降到 1–2 条或把"群里安静 30 分钟"改 60 分钟 |
| `focus` 状态机 | 已上线（问过 90 分钟内不追、等结果 24 小时不催、了结后从 self 真删）；还需观察真实命中率 |
| 关系段未拆范围 | `self.md` 目前仍是整篇全局注入，未按 `relations/<user_id>.md` 拆分（设计文档已标为缺口） |
| 记忆合并 | 陈老师 4 条重复记忆（id90 + id129/130/131）待用户告知约谈结果后合并 |
| 长期记忆提炼质量 | `importance` 84% 挤在 0.7，区分度不足（属冻结项） |
| 本地备份开机自启 | **2026-11-03 按要求关闭**（删除了启动项 `dshqq-backup.lnk`）；现在需要手动双击 `backup.bat`，或重新启用 `backup-loop.cmd` |

### 已知坑（改代码前先看）

- `cmd_config.json` 带 BOM，读写一律 `encoding="utf-8-sig"`。
- `platform_message_history.created_at` 是 **UTC 文本**，`memories.created_at` 是 **REAL epoch** —— 两张表边界比较方式不同。
- 备份记忆库必须 `db + -wal + -shm` 三个一起，且恢复顺序是"先 `data/` 后 `plugin_data/`"。
- 给 Windows 写 `.ps1` 必须 UTF-8 **带 BOM** + CRLF；给 cmd 写 `.bat` 用 GBK 或纯 ASCII。
- 本机 `schtasks`、`Get-ScheduledTask`、`Get-CimInstance` 在沙箱里常报"拒绝访问"，需要 danger-full-access；用 `netstat -ano` 判端口，别用 `Get-NetTCPConnection`。
- 插件桩测试用 `__new__` 造实例，新增字段要给 `getattr(self, "x", 默认值)` 兜底。

---

## 8. 常用操作

```bat
:: 连服务器（最常用）
cd /d D:\dsh-qq
sshx "docker ps"
sshx "docker logs astrbot --since 10m 2>&1 | grep -E '主动v2|影子|大脑'"

:: 改插件（示例：主动消息）
:: 1) 改 tmp\proactive_v2\main.py  2) 跑桩测试  3) 上传 + 重启
python tmp\proactive_v2\test_proactive_v2.py
:: 上传用 base64 避免引号/编码问题：
::   b=$(base64 -w0 tmp/proactive_v2/main.py)
::   sshx "echo '$b' | base64 -d > /opt/astrbot/data/plugins/astrbot_proactive_v2/main.py && docker restart astrbot"

:: 手动备份（本地）
backup.bat

:: 服务器立刻打一次快照
sshx "/usr/local/bin/snapshot.sh"

:: 健康检查
sshx "tail -3 /var/log/health.log; free -m | head -2; docker stats --no-stream"
```

---

## 9. 最近变更

| 日期 | 变更 |
|---|---|
| 2026-11-03 | 关闭本地开机自启（`dshqq-backup.lnk`）；隧道计划任务重建并恢复（三个地址 200） |
| 2026-11-02 | 人格重写 807 字、self 改五段、修日记重复 bug 并重跑五篇、主动消息加群聊目标（v0.4.1） |
| 2026-11-02 | 主动消息改指数间隔（均值 90 分钟）；`focus` 状态机（结果驱动，不再靠时间屏蔽） |
| 2026-10-29 | 记忆库迁移到 v2 schema（23 列 + 4 表）、影子插件、四条验收、灰度读路径 |
| 2026-10-28 | 长期记忆插件上线并修好"不记事实"；48 小时短期回忆插件上线 |
| 2026-10-26 | 群聊注意力 v0.3、引用加强插件上线；服务器三层内存防护定型 |
