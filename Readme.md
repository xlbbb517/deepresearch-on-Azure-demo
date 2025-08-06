# Deep Research Web UI on Azure

一个基于Azure AI Projects的智能研究助手Web应用，支持深度研究和报告生成。

## ✨ 功能特性

- 🔍 **智能研究助手**: 基于Azure AI Agent进行深度研究
- 🤖 **交互式对话**: 支持澄清问题和补充信息
- 📊 **自动报告生成**: 生成带引用资料的研究报告
- 🌐 **Web界面**: 简洁友好的用户界面
- ☁️ **Azure集成**: 完全集成Azure AI服务和Bing搜索


## 📋 环境要求

- Python 3.8+
- Azure订阅
- Azure AI Projects资源
- Bing Search API连接

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd deepresearch-demo-ui
```

### 2. 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv deepresearch
source deepresearch/bin/activate  # Linux/Mac
# 或
deepresearch\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

创建 `.env` 文件：

```env
# Azure AI Project 配置 (必需)
AZURE_AI_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/api/projects/your-project
BING_CONNECTION_NAME=your-bing-connection

# Azure 认证配置 (可选)
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
AZURE_TENANT_ID=your-tenant-id

# 模型配置 (可选)
DEEP_RESEARCH_MODEL=o3-deep-research
AGENT_MODEL=gpt-4o
AGENT_NAME=my-research-agent

```



## 🌐 部署到Azure

### 使用VS Code Azure扩展部署

1. 安装Azure App Service扩展
2. 登录Azure账户
3. 右键项目文件夹 → "Deploy to Web App..."
4. 按照向导创建或选择Web App
5. 配置环境变量（见下方）

### 使用Azure CLI部署

```bash
# 登录Azure
az login

# 创建资源组
az group create --name deepresearch-rg --location "West US 2"

# 创建App Service计划
az appservice plan create --name deepresearch-plan --resource-group deepresearch-rg --sku B1 --is-linux

# 创建Web App
az webapp create --resource-group deepresearch-rg --plan deepresearch-plan --name your-unique-app-name --runtime "PYTHON|3.11"

# 配置启动命令
az webapp config set --resource-group deepresearch-rg --name your-unique-app-name --startup-file "gunicorn --bind 0.0.0.0:8000 --timeout 0 simple_web_app:app"

# 部署代码
az webapp up --resource-group deepresearch-rg --name your-unique-app-name --runtime "PYTHON|3.11"
```

### Azure环境变量配置


| 变量名 | 说明 | 必需 |
|--------|------|------|
| `AZURE_AI_PROJECT_ENDPOINT` | Azure AI Project端点 | ✅ |
| `BING_CONNECTION_NAME` | Bing搜索连接名称 | ✅ |
| `AZURE_CLIENT_ID` | Azure应用客户端ID | ✅ |
| `AZURE_CLIENT_SECRET` | Azure应用客户端密钥 | ✅ |
| `AZURE_TENANT_ID` | Azure租户ID | ✅ |


## 📁 项目结构

```
deepresearch-demo-ui/
├── simple_web_app.py          # 主应用文件
├── requirements.txt           # Python依赖
├── .env.example              # 环境变量示例
├── .gitignore               # Git忽略文件
├── README.md                # 项目文档
├── templates/
│   └── simple_index.html    # 前端模板
├── logs/                    # 日志文件
└── static/                  # 静态资源（如需要）
```

## 🔧 配置说明

### Azure AI Project设置

1. 在Azure Portal中创建AI Project
2. 配置Bing Search连接
3. 获取项目端点和连接名称
4. 确保应用有足够的权限访问AI服务

### 权限配置

您的Azure应用注册需要以下权限：

- **资源角色**: AI Project的 `AI Developer` 或 `Contributor`
- **Bing资源**: `Cognitive Services User`

## 🚀 使用指南

1. **输入研究主题**: 在文本框中输入您要研究的主题
2. **开始研究**: 点击"开始研究"按钮
3. **交互对话**: 根据助手的问题提供补充信息
4. **等待结果**: 系统将自动进行深度研究
5. **下载报告**: 研究完成后下载生成的报告

### 示例研究主题

```
Give me the latest research into quantum computing over the last year.
Analyze the current trends in renewable energy technology.
What are the recent breakthroughs in artificial intelligence?
Research the impact of climate change on agriculture.
```

## 📊 监控和日志

### 本地开发

- 日志文件: `logs/simple_web_YYYYMMDD.log`
- 控制台输出: 实时显示重要信息

### Azure部署

- 应用日志: Azure Portal → App Service → Logs
- 实时日志: `az webapp log tail --name your-app-name --resource-group your-resource-group`
- 下载日志: `az webapp log download --name your-app-name --resource-group your-resource-group`

## 🔧 故障排除

### 调试模式

设置 `FLASK_DEBUG=True` 启用调试模式，获取详细错误信息。


## 📈 版本历史

- **v1.0.0** - 初始版本
  - 基础研究功能
  - Web界面
  - Azure集成
  - 报告生成
