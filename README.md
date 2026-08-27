# NJU Agent

南京大学软件学院预推免考核项目：从零实现一个能够读写文件、执行命令并与大语言模型协作完成编程任务的智能体。

当前版本为 `0.2.0`，已完成第二阶段的最小 Agent 闭环，具备：

- Python CLI 入口：`nju-agent`；
- 从环境变量加载运行配置；
- 工作区路径校验；
- OpenAI 兼容接口模型客户端（默认 DeepSeek）；
- `list_files` 本地工具；
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

配置示例见 `.env.example`，默认面向 `deepseek-v4-pro`。设置 API Key 和模型后，启动 CLI 即可发送真实任务。API Key 只能通过环境变量或未入库配置文件提供，不能写入 Git 仓库。

## 架构方向

后续实现将保持以下边界：`config` 负责配置，`model` 负责模型请求，`tools` 负责本地工具定义与执行，`agent` 负责对话历史、工具调用解析、循环终止和错误处理，`cli` 负责用户交互。
