# 架构说明

## 第二阶段：最小 Agent 闭环

当前阶段实现一次完整的“用户任务 -> 模型 -> 本地工具 -> 模型 -> 最终回答”循环：

```text
命令行界面 -> 配置 -> Agent 运行时 <-> 模型客户端
                             |
                             +-> 本地工具（list_files）
```

- `nju_agent/config.py`：读取环境变量，并校验工作区路径。
- `nju_agent/cli.py`：处理命令行参数和交互式输入输出。
- `nju_agent/model.py`：通过 OpenAI 兼容的 Chat Completions 接口请求模型。
- `nju_agent/tools.py`：定义 `list_files` 工具并在工作区内执行。
- `nju_agent/agent.py`：管理对话历史、解析工具调用、控制循环终止，并处理运行异常。

模型 API Key 在启动骨架时可以为空；用户提交任务时若未配置 API Key 或模型，CLI 会提示补充配置。Agent 默认最多执行 8 步，避免模型反复调用工具导致无限循环。
