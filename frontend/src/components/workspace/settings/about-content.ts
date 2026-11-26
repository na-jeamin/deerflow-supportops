/**
 * About DeerFlow markdown content. Inlined to avoid raw-loader dependency
 * (Turbopack cannot resolve raw-loader for .md imports).
 */
import {
  PROJECT_NAME,
  PROJECT_REPOSITORY_URL,
  UPSTREAM_REPOSITORY_URL,
} from "@/core/branding";
import { APP_VERSION } from "@/version";

export const aboutMarkdown = `# ${PROJECT_NAME}

基于 [DeerFlow](${UPSTREAM_REPOSITORY_URL}) 二次开发的订单与售后助手。

本项目新增订单查询工具、售后申请、人工审批、版本校验、幂等建单和售后工作台。订单使用固定演示数据，申请与工单保存在 SQLite 中。

模型接入、Agent 循环、工具调度和通用聊天界面来自 DeerFlow；下方保留上游介绍与致谢。

[本项目仓库 / SupportOps repository](${PROJECT_REPOSITORY_URL})

An order and after-sales assistant built on DeerFlow. SupportOps adds order tools, persisted requests, human approval, revision checks, idempotent ticket creation and the after-sales workspace. The agent runtime and general chat interface come from DeerFlow.

---

# 🦌 [About DeerFlow ${APP_VERSION}](${UPSTREAM_REPOSITORY_URL})

> **From Open Source, Back to Open Source**

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) is an open-source **super agent harness** that orchestrates **sub-agents**, **memory**, and **sandboxes** to do almost anything — powered by **extensible skills**.

---

## 🚀 Core Features

* **Skills & Tools**: With built-in and extensible skills and tools, DeerFlow can do almost anything.
* **Sub-Agents**: Sub-Agents help the main agent to do the tasks that are too complex to be done by the main agent.
* **Sandbox & File System**: Safely execute code and manipulate files in the sandbox.
* **Context Engineering**: Isolated sub-agent context, summarization to keep the context window sharp.
* **Long-Term Memory**: Keep recording the user's profile, top of mind, and conversation history.

---

## 🌟 GitHub Repository

![Star History Chart](https://api.star-history.com/svg?repos=bytedance/deer-flow&type=Date)

Explore DeerFlow on GitHub: [github.com/bytedance/deer-flow](https://github.com/bytedance/deer-flow)

## 🌐 Official Website

Visit the official website of DeerFlow: [deerflow.tech](https://deerflow.tech/)

## 📧 Support

If you have any questions or need help, please contact us at [support@deerflow.tech](mailto:support@deerflow.tech).

---

## 📜 License

DeerFlow is proudly open source and distributed under the **MIT License**.

---

## 🙌 Acknowledgments

We extend our heartfelt gratitude to the open source projects and contributors who have made DeerFlow a reality. We truly stand on the shoulders of giants.

### Core Frameworks
- **[LangChain](https://github.com/langchain-ai/langchain)**: A phenomenal framework that powers our LLM interactions and chains.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Enabling sophisticated multi-agent orchestration.
- **[Next.js](https://nextjs.org/)**: A cutting-edge framework for building web applications.

### UI Libraries
- **[Shadcn](https://ui.shadcn.com/)**: Minimalistic components that power our UI.
- **[SToneX](https://github.com/stonexer)**: For his invaluable contribution to token-by-token visual effects.

These outstanding projects form the backbone of DeerFlow and exemplify the transformative power of open source collaboration.

### Special Thanks
Finally, we want to express our heartfelt gratitude to the core authors of DeerFlow 1.0 and 2.0:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

Without their vision, passion and dedication, \`DeerFlow\` would not be what it is today.
`;
