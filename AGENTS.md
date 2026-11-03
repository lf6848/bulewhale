# 大肥鱼（AstrBot + SnowLuma）项目规则

## 项目定位

- 项目根目录：`D:\dsh-qq`；这是长期维护的 L2 运维与插件项目。
- 生产系统是阿里云上的 AstrBot 与 SnowLuma 容器。`README.md` 是当前架构、运行方式与历史状态的入口文档。
- 本地源码的主要事实来源是 `tmp/`；`panel/` 为本地只监听回环地址的管理面板；`docs/` 是设计与回放资料。
- 本项目使用 Git，默认分支为 `main`，并跟踪用户指定的 GitHub 远端。由于 Windows 工作区所有者与 Codex 沙箱身份不同，Git 命令使用一次性 `-c safe.directory=D:/dsh-qq`，不得添加全局信任例外。

## 本工作区的用户授权

用户已授权在 `D:\dsh-qq` 内自主创建、修改、覆盖、重命名与删除项目文件，以完成明确的项目任务；无需为工作区内的常规实现步骤再次确认。

- 可使用 PowerShell、CMD、Bash、WSL（如已安装）及本机已安装的项目相关工具。
- 运行工具前仍应确认目标、参数与影响范围；对不可逆或批量删除操作应先核对精确路径。
- 此授权仅覆盖本工作区，且不覆盖 Codex 宿主机的沙箱/托管限制。
- 远程生产写入、上传、容器重启、凭据轮换、恢复备份、外部账户操作及工作区外的实质性改动，仍须取得本轮明确授权。

## 每轮工作入口

1. 阅读本文件、`README.md`，以及 `docs/codex/coordination/ACTIVE_PLAN.md` 和 `HANDOFF.md`。
2. 涉及方案、风险或生产行为时，再阅读 `DECISIONS.md` 和 `REVIEW_QUEUE.md`。
3. 修改前先定位对应本地源文件，并确认是否已部署到服务器；本地文件不是生产状态的证明。
4. 修改后运行对应离线桩测试。用 `D:\anaoconda\ANAOCONDA\python.exe -X utf8`，避免 Windows 控制台编码问题。

## 生产安全边界

- 未经用户本轮明确同意，不执行远程写入、上传、容器重启、cron 修改、配置修改、密钥轮换、备份恢复或公开端口调整。
- 远程只读健康检查可以执行，但输出中不得回显令牌、密码、私钥、完整连接串或聊天内容。
- 任何涉及长期记忆库的备份或恢复，必须把 SQLite 的数据库、`-wal`、`-shm` 作为同一组处理；恢复顺序遵循 README。
- 配置文件与 README 可能包含机密。新文档、测试输出和回复一律以名称或状态代称，禁止复制具体值。

## 当前验证基线（2026-11-03）

- `tmp/brain_read/test_brain_read.py`：通过。
- `tmp/proactive_v2/test_proactive_v2.py`：通过（29 项）。
- `tmp/memory_shadow/test_inject.py`：通过 4 项离线场景；测试创建临时 SQLite fixture，不读取生产库，任一断言失败返回非零退出码。
- `tmp/memory_shadow/accept_v2.py` 依赖生产数据库路径，不能在本地直接作为安全验证运行。

## 文档维护

- 阶段、验证基线或待决风险变化时，同步更新 `docs/codex/coordination/`。
- 交接完成后在最终回复中说明：已更新文件、验证结果、未做的生产动作与全局沉淀结论。
