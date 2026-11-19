# 踩坑与复盘（TaskBridge）
本文件只记录踩过的坑、实测结论与处理方式；设计取舍见 `../README.md`，参数见 README 的配置表。

## opencode 的日志目录可能不可写
默认写 `~/.local/share/opencode/log`，在受限沙箱或只读 HOME 下会直接报 `FileSystem.open(...)` 然后退出。
处理：把 `XDG_DATA_HOME` / `XDG_CACHE_HOME` / `XDG_CONFIG_HOME` 重定向到本服务自己的目录，路径由 `TB_XDG_ROOT` 决定（默认 `logs/taskbridge/ocdata`）。

## worktree 副本方案会把改动写回主仓库
worktree 的 `.git` 只是指针文件，`--git-common-dir` 会解析回主仓库；agent 据此把工程根判成主仓库，改动全落在主仓库、副本里 diff 为空。
处理：改用**分支模型**（原地开 `tb/<任务号>` 分支），不再有副本；同时保留「路径白名单 + diff 非空 + 文件数上限」三道硬校验。

## 多行提示词经 `.cmd` 壳子会被截断
Windows 上 npm 全局安装的 `opencode` 是 `.cmd` 批处理壳子，命令行里的换行会被 `cmd.exe` 截断，多行需求只剩第一行。
处理：解析壳子内容找到真正的 `opencode.exe` 直接调用；同时把提示词里的换行压平成一行的 `\n` 转义（`_flatten`）。

## 容器里的 git 会把整仓看成已修改
仓库从 Windows 宿主挂进 Linux 容器时，工作区是 CRLF，而容器里的 git 默认按 LF 比较 → `git status` 报 400+ 个「已修改」。后果很隐蔽：**基线被污染后，真实改动反而被过滤成「无改动」**，任务全部失败。
处理：镜像里固化 `core.autocrlf true` 与 `core.fileMode false`（WSL 挂载的可执行位也不一致），并加 `safe.directory`（容器内以 root 操作宿主仓库）。

## opencode 的库不跨平台
宿主那份 `logs/taskbridge/ocdata` 是 Windows 版 opencode 建的 SQLite 库，Linux 容器读它会报 `Failed query: select ... from project`。
处理：容器把 `TB_XDG_ROOT` 指到 `/root/ocdata`，并挂独立命名卷 `taskbridge_oc`；宿主与容器各用各的。

## `pythonw` 拉不起 uvicorn
`pythonw.exe` 没有标准输出，uvicorn 启动阶段写日志会失败，进程起来又消失（现象：PID 出现后马上没了，端口不监听）。
处理：不要用 pythonw；无窗口需求改成 `cmd /c ... >> log 2>&1`（或用容器）。

## `run_task` 返回值扩容后要同步所有调用点
为支持只读问答，`agent.run_task` 的返回值从 2 个变成 3 个（多一个完整 stdout）。只改了 ask 分支，正常代码路径仍是 `a, b = ...`，结果每个改代码任务都报 `ValueError: too many values to unpack`。
处理：所有调用点统一解包；这类「改签名」必须全局搜一遍。

## 代理缓存会让「后端已挂」看起来正常
Dify 的 HTTP 节点经 `ssrf_proxy`（squid）出网，squid 默认会缓存 GET 响应。实测停掉后端后，**同一关键词仍返回旧数据**，只有新关键词才会走异常分支。
处理：在 `dify/docker/ssrf_proxy/squid.conf.template` 里加 `cache deny all` 并重建该容器。这条不在本模块内，但排查时容易误判成「TaskBridge 没生效」。

## 应用后自动推送与容器 ssh 依赖
apply 成功后会**先在本地提交，再推远端** —— 两步都在同一次 apply 里完成，无需再手工 push。
推送失败**不回滚**本地提交（提交已在 `tb/<任务号>` 分支上，代码不会丢）：错误按原样回报到 QQ，并附上补救命令，方便人工补推或修正凭据后重试。
容器里必须装 `openssh-client`，且把宿主 `~/.ssh` **只读**挂载进容器；缺任一项时 `git push` 会报 `cannot run ssh`（找不到 ssh 可执行文件或读不到密钥）。
