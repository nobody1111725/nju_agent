# NJU Agent

南京大学软件学院预推免考核项目：从零实现一个能够读写文件、执行命令并与大语言模型协作完成编程任务的智能体。

当前版本为 `0.4.0`，已完成第四阶段的可靠性与安全控制，具备：

- Python CLI 入口：`nju-agent`；
- 从环境变量加载运行配置；
- 工作区路径校验；
- OpenAI 兼容接口模型客户端（默认 DeepSeek）；
- `list_files`、`read_file`、`write_file`、`edit_file` 和 `run_command` 本地工具；
- 文件路径限制在配置的工作区内；
- 命令超时和工具输出长度限制；
- `.env` 自动加载，且不会覆盖已有环境变量；
- 危险命令拦截、模型响应校验和重复工具失败熔断；
- 工作区内的运行日志，不记录 API Key；
- 模型决定调用工具、工具执行、结果回传模型的闭环；
- 最大循环步数和模型、工具错误处理。

## 运行

需要 Python 3.10 或更高版本。开发模式下可直接运行：

```text
python -m nju_agent.cli
```

也可以安装当前项目后使用命令：

```text
python -m pip install -e .
nju-agent
```

配置示例见 `.env.example`，默认面向 `deepseek-v4-pro`。可将配置复制到项目根目录的 `.env`，启动 CLI 即可发送真实任务。`.env` 和运行日志均已忽略，不会被提交；API Key 不能写入 README 或 Git 仓库。

## 架构方向

后续实现将保持以下边界：`config` 负责配置，`model` 负责模型请求，`tools` 负责本地工具定义与执行，`agent` 负责对话历史、工具调用解析、循环终止和错误处理，`cli` 负责用户交互。
