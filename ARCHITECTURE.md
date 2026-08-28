# 架构说明

## 第三阶段：编程工具集

当前阶段在最小 Agent 闭环中加入文件和命令工具：

```text
命令行界面 -> 配置 -> Agent 运行时 <-> 模型客户端
                             |
                             +-> 本地工具（文件读写、编辑、命令执行）
```

- `nju_agent/config.py`：读取环境变量，并校验工作区路径。
- `nju_agent/cli.py`：处理命令行参数和交互式输入输出。
- `nju_agent/model.py`：通过 OpenAI 兼容的 Chat Completions 接口请求模型。
- `nju_agent/tools.py`：定义并执行 `list_files`、`read_file`、`write_file`、`edit_file`、`run_command`。
- `nju_agent/agent.py`：管理对话历史、解析工具调用、控制循环终止，并处理运行异常。

所有文件路径都会解析并校验为工作区内路径。文件使用 UTF-8 文本读写；编辑要求旧文本恰好出现一次。命令在工作区目录执行，默认超时 30 秒，工具结果超过限制时会截断并明确标记。Agent 默认最多执行 8 步，避免模型反复调用工具导致无限循环。
