NJU Agent

Git 仓库地址
https://github.com/nobody1111725/nju_agent

如何运行
1. 环境要求：Python 3.10+。
2. 在项目根目录创建.env：
   NJU_AGENT_API_KEY=你的 DeepSeek API Key
   NJU_AGENT_MODEL=deepseek-v4-pro
   NJU_AGENT_BASE_URL=https://api.deepseek.com/v1
   NJU_AGENT_WORKSPACE=.
   API Key只保存在本地，不提交到Git。
3. 安装并启动CLI：
   python -m pip install -e .
   python -m nju_agent.cli
4. 启动浏览器界面：
   python -m nju_agent.cli --web
   浏览器访问 http://127.0.0.1:8765，可用 --port 指定端口。
5. 运行测试：
   python -m unittest discover

特色功能
- Agent完成“理解需求、制定计划、操作文件、执行命令、测试、总结”的编程闭环。
- 不使用LangChain、LlamaIndex等Agent框架；模型请求、工具解析和循环控制由项目实现。
- 本地工具支持列出、读取、原地写入和编辑文件、执行命令，并限制路径在工作区内。
- Web通过SSE实时显示具体工具指令、参数和状态，且按对话轮次保存。
- 回答以带闪烁光标的打字机效果逐字显示，并支持Markdown。
- 提供类似GitHub的文件修改前后差异视图，可直接打开本次修改的文件。
- 支持代码或文本附件拖拽上传、取消上传，并在历史消息保留附件名。
- 会话、计划、工具记录和差异保存在本地，可恢复会话继续工作。
- 具备路径校验、危险命令拦截、命令超时、输出限制、上下文压缩、重复调用提醒和错误熔断。

其它说明
默认配置面向DeepSeek OpenAI兼容接口，也可替换为同接口模型。Web默认只监听本机。正文逐字显示是前端打字机效果，并非token级流式响应。代码执行和文件修改均在指定本地工作区完成。
