import asyncio
import os
import logging
from flask import Flask, render_template, request, jsonify, send_file
import json
from typing import Optional
from datetime import datetime
import threading
import queue
from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import DeepResearchTool, MessageRole, ThreadMessage
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

# local testing
if os.path.exists('.env'):
    load_dotenv()

# 检查必需的环境变量（静默检查）
required_env_vars = [
    'AZURE_AI_PROJECT_ENDPOINT',
    'BING_CONNECTION_NAME'
]

# Azure认证相关变量
auth_env_vars = ['AZURE_CLIENT_ID', 'AZURE_CLIENT_SECRET', 'AZURE_TENANT_ID']

missing_vars = [var for var in required_env_vars if not os.environ.get(var)]


auth_vars_configured = all(
    os.environ.get(var) and os.environ.get(var).strip() 
    for var in auth_env_vars
)

# 如果有缺失的环境变量，程序无法运行
if missing_vars:
    # 只在这种情况下立即显示错误
    print(f"❌ 缺少环境变量: {', '.join(missing_vars)}")
    print("请在 .env 文件中配置这些变量")
    exit(1)

# 从环境变量获取配置
AZURE_AI_PROJECT_ENDPOINT = os.environ.get('AZURE_AI_PROJECT_ENDPOINT')
BING_CONNECTION_NAME = os.environ.get('BING_CONNECTION_NAME')
DEEP_RESEARCH_MODEL = os.environ.get('DEEP_RESEARCH_MODEL', 'o3-deep-research')
AGENT_MODEL = os.environ.get('AGENT_MODEL', 'gpt-4o')
AGENT_NAME = os.environ.get('AGENT_NAME', 'my-research-agent')
FLASK_HOST = os.environ.get('FLASK_HOST', '127.0.0.1')
FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

# 创建日志目录
if not os.path.exists('logs'):
    os.makedirs('logs')

log_filename = f"logs/simple_web_{datetime.now().strftime('%Y%m%d')}.log"

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8')
    ]
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

logger = logging.getLogger(__name__)
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)

# 设置第三方库的日志级别
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('flask').setLevel(logging.ERROR)
logging.getLogger('azure').setLevel(logging.WARNING)
logging.getLogger('azure.core').setLevel(logging.ERROR)
logging.getLogger('azure.identity').setLevel(logging.ERROR)
logging.getLogger('azure.ai').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('aiohttp').setLevel(logging.ERROR)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'deep-research-web-ui-secret-key-2025')

# 禁用 Flask 的请求日志
app.logger.setLevel(logging.ERROR)

# 全局状态
status = {
    'is_running': False,
    'messages': [],
    'waiting_for_input': False,
    'error': None,
    'result_file': None
}

# 消息队列用于线程间通信
message_queue = queue.Queue()
response_queue = queue.Queue()

def create_research_summary(message: ThreadMessage, filepath: str = "research_summary.md") -> None:
    """创建研究摘要 - 与demo完全一致"""
    if not message:
        logging.getLogger(__name__).warning("No message content provided, cannot create research summary.")
        return

    with open(filepath, "w", encoding="utf-8") as fp:
        text_summary = "\n\n".join([t.text.value.strip() for t in message.text_messages])
        fp.write(text_summary)

        if message.url_citation_annotations:
            fp.write("\n\n## References\n")
            seen_urls = set()
            for ann in message.url_citation_annotations:
                url = ann.url_citation.url
                title = ann.url_citation.title or url
                if url not in seen_urls:
                    fp.write(f"- [{title}]({url})\n")
                    seen_urls.add(url)

    logging.getLogger(__name__).info(f"研究摘要已写入文件: {filepath}")

async def fetch_and_print_new_agent_response(
    thread_id: str,
    agents_client: AgentsClient,
    last_message_id: Optional[str] = None,
) -> Optional[str]:
    """获取新的助手响应 - 与demo完全一致"""
    file_logger = logging.getLogger(__name__)
    
    response = await agents_client.messages.get_last_message_by_role(
        thread_id=thread_id,
        role=MessageRole.AGENT,
    )

    if not response or response.id == last_message_id:
        return last_message_id

    response_text = "\n".join(t.text.value for t in response.text_messages)
    
    # 添加到状态消息列表
    status['messages'].append({
        'role': 'assistant',
        'content': response_text,
        'timestamp': datetime.now().isoformat()
    })
    
    # 只记录到文件
    file_logger.debug(f"收到新的助手响应，ID: {response.id}")
    file_logger.debug(f"助手响应内容: {response_text[:200]}...")

    for ann in response.url_citation_annotations:
        file_logger.debug(f"URL Citation: [{ann.url_citation.title}]({ann.url_citation.url})")

    return response.id

async def run_research_session():
    """运行研究会话 - 完全按照demo的main()函数逻辑"""
    global status
    
    file_logger = logging.getLogger(__name__)
    agent_id_to_delete = None
    thread_id_to_delete = None
    agents_client_for_cleanup = None
    
    try:
        status['is_running'] = True
        status['messages'] = []
        
        # 等待初始主题
        file_logger.debug("等待用户输入研究主题...")
        initial_topic = message_queue.get()
        
        status['messages'].append({
            'role': 'user',
            'content': initial_topic,
            'timestamp': datetime.now().isoformat()
        })

        logger.info(f"开始研究会话: {initial_topic}")
        file_logger.info(f"开始研究会话，主题: {initial_topic}")

        # Use 'async with' to manage the credential lifecycle
        async with DefaultAzureCredential() as credential:
            project_client = AIProjectClient(
                endpoint=AZURE_AI_PROJECT_ENDPOINT,
                credential=credential,
            )
            
            async with project_client:
                try:
                    agents_client = project_client.agents
                    agents_client_for_cleanup = agents_client

                    conn = await project_client.connections.get(name=BING_CONNECTION_NAME)
                    conn_id = conn.id
                    file_logger.debug(f"获取到Bing连接ID: {conn_id}")
                    
                    deep_research_tool = DeepResearchTool(
                        bing_grounding_connection_id=conn_id,
                        deep_research_model=DEEP_RESEARCH_MODEL,
                    )

                    agent = await agents_client.create_agent(
                        model=AGENT_MODEL,
                        name=AGENT_NAME,
                        instructions=(
                            "You are a helpful Agent that assists in researching scientific topics. "
                            "First, you should ask clarifying questions to get enough information. "
                            "When you have enough information, use the deep_research tool to provide the final answer. "
                            "When calling the deep_research tool, you MUST follow these rules:\n"
                            "1. Only use 'title' and 'prompt' parameters\n"
                            "2. Ensure all parameter values are properly formatted strings\n"
                            "3. Avoid special characters like unmatched parentheses in parameter values\n"
                            "4. Keep parameter values concise and well-formatted\n"
                            "Example format: deep_research(title=\"Research Title\", prompt=\"Your research question here\")"
                        ),
                        tools=deep_research_tool.definitions,
                    )
                    agent_id_to_delete = agent.id
                    file_logger.info(f"研究助手已创建，ID: {agent.id}")

                    thread = await agents_client.threads.create()
                    thread_id_to_delete = thread.id
                    file_logger.info(f"对话线程已创建，ID: {thread.id}")

                    user_message_content = initial_topic
                    last_message_id: Optional[str] = None
                    agent_response_text = ""
                    max_retries = 3
                    current_retries = 0

                    while True:
                        if current_retries >= max_retries:
                            file_logger.error(f"达到最大重试次数 ({max_retries})，终止程序")
                            break

                        if user_message_content:
                            message = await agents_client.messages.create(
                                thread_id=thread.id,
                                role="user",
                                content=user_message_content,
                            )
                            file_logger.debug(f"消息已创建，ID: {message.id}")

                        file_logger.debug("正在处理消息...")
                        
                        if "start_research_task" in agent_response_text:
                            file_logger.info("检测到研究任务开始标志，强制执行工具")
                            run = await agents_client.runs.create(
                                thread_id=thread.id, 
                                agent_id=agent.id,
                                tools=deep_research_tool.definitions
                            )
                        else:
                            run = await agents_client.runs.create(thread_id=thread.id, agent_id=agent.id)
                        
                        while run.status in ("queued", "in_progress"):
                            await asyncio.sleep(5)
                            run = await agents_client.runs.get(thread_id=thread.id, run_id=run.id)
                            
                            new_last_message_id = await fetch_and_print_new_agent_response(
                                thread_id=thread.id,
                                agents_client=agents_client,
                                last_message_id=last_message_id,
                            )
                            if new_last_message_id != last_message_id:
                                last_message_id = new_last_message_id
                                latest_message = await agents_client.messages.get(thread_id=thread.id, message_id=last_message_id)
                                agent_response_text = "\n".join(t.text.value for t in latest_message.text_messages)

                            file_logger.debug(f"运行状态: {run.status}")

                        file_logger.info(f"运行完成，状态: {run.status}")

                        if run.status == "completed":
                            current_retries = 0

                        if run.status == "failed":
                            error_code = run.last_error.get('code') if run.last_error else None
                            error_message = run.last_error.get('message', '') if run.last_error else ''
                            
                            current_retries += 1
                            file_logger.warning(f"运行失败，重试 {current_retries}/{max_retries}")
                            file_logger.warning(f"错误详情: {error_message}")

                            if error_code == 'tool_server_error':
                                if 'too many values to unpack' in error_message:
                                    correction_message = "You previously failed to call the deep_research tool because you provided the wrong number of parameters. Please try again, and ONLY use the 'title' and 'prompt' parameters for the tool call. Make sure the parameter values are properly formatted strings without special characters."
                                elif 'could not be parsed' in error_message or 'unmatched' in error_message:
                                    correction_message = (
                                        "You previously failed to call the deep_research tool due to a parsing error. "
                                        "Please ensure you:\n"
                                        "1. Only use 'title' and 'prompt' parameters\n"
                                        "2. Properly format all parameter values as strings\n"
                                        "3. Avoid special characters like unmatched parentheses, quotes, or brackets\n"
                                        "4. Use simple, clean text for both title and prompt\n"
                                        "Please try calling the tool again with corrected formatting."
                                    )
                                else:
                                    correction_message = (
                                        "There was an error with the deep_research tool. Please try again with:\n"
                                        "- Only 'title' and 'prompt' parameters\n"
                                        "- Simple, clean text without special formatting\n"
                                        "- Proper string formatting"
                                    )
                                
                                await agents_client.messages.create(
                                    thread_id=thread.id,
                                    role="user",
                                    content=correction_message
                                )
                                user_message_content = None 
                                agent_response_text = ""
                                continue
                            elif error_code == 'server_error' and 'Sorry, something went wrong' in error_message:
                                file_logger.info("临时服务器错误，直接重试")
                                user_message_content = None 
                                agent_response_text = ""
                                continue
                            else:
                                file_logger.error(f"运行失败，不可恢复的错误: {run.last_error}")
                                break
                    
                        final_message = await agents_client.messages.get_last_message_by_role(
                            thread_id=thread.id, role=MessageRole.AGENT
                        )

                        if final_message:
                            agent_response_text = "\n".join(t.text.value for t in final_message.text_messages)
                            if final_message.id != last_message_id:
                                file_logger.debug("收到最终助手响应")
                                last_message_id = final_message.id

                        if final_message and final_message.url_citation_annotations:
                            logger.info("研究完成，生成报告中...")
                            file_logger.info("找到引用资料，生成最终报告...")
                            timestamp = int(datetime.now().timestamp())
                            result_file = f"research_summary_{timestamp}.md"
                            create_research_summary(final_message, filepath=result_file)
                            status['result_file'] = result_file
                            status['waiting_for_input'] = False
                            break
                        
                        if "start_research_task" not in agent_response_text:
                            status['waiting_for_input'] = True
                            logger.info("等待用户补充信息")
                            file_logger.info("等待用户补充信息...")
                            
                            # 等待用户输入
                            try:
                                user_message_content = message_queue.get(timeout=300)  # 5分钟超时
                                status['messages'].append({
                                    'role': 'user',
                                    'content': user_message_content,
                                    'timestamp': datetime.now().isoformat()
                                })
                                status['waiting_for_input'] = False
                                
                                if user_message_content.lower() in ["exit", "quit"]:
                                    file_logger.info("用户退出对话")
                                    break
                            except queue.Empty:
                                file_logger.warning("用户输入超时")
                                break
                        else:
                            user_message_content = None
                
                except Exception as e:
                    logger.error(f"研究过程中发生错误: {e}")
                    file_logger.error(f"研究过程中发生错误: {e}", exc_info=True)
                    status['error'] = str(e)
                
                finally:
                    # 清理资源
                    file_logger.info("开始清理资源...")
                    if agent_id_to_delete and agents_client_for_cleanup:
                        try:
                            await agents_client_for_cleanup.delete_agent(agent_id_to_delete)
                            file_logger.info("✓ 助手已删除")
                        except Exception as e:
                            file_logger.warning(f"✗ 无法删除助手: {e}")
                    
                    if thread_id_to_delete and agents_client_for_cleanup:
                        try:
                            await agents_client_for_cleanup.threads.delete(thread_id_to_delete)
                            file_logger.info("✓ 线程已删除")
                        except Exception as e:
                            file_logger.warning(f"✗ 无法删除线程: {e}")
    
    except Exception as e:
        logger.error(f"研究会话发生错误: {e}")
        file_logger.error(f"研究会话发生错误: {e}", exc_info=True)
        status['error'] = str(e)
    finally:
        status['is_running'] = False
        logger.info("研究会话结束")
        file_logger.info("研究会话结束")

def run_research_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_research_session())
    finally:
        loop.close()

@app.route('/')
def index():
    return render_template('simple_index.html')

@app.route('/api/status')
def get_status():
    return jsonify(status)

@app.route('/api/start_research', methods=['POST'])
def start_research():
    global status
    
    if status['is_running']:
        return jsonify({'error': '研究会话已在运行中'}), 400
    
    data = request.get_json()
    topic = data.get('topic', '').strip()
    
    if not topic:
        return jsonify({'error': '请提供研究主题'}), 400
    
    logger.info(f"启动新研究: {topic}")
    
    # 重置状态
    status = {
        'is_running': False,
        'messages': [],
        'waiting_for_input': False,
        'error': None,
        'result_file': None
    }
    
    # 发送主题到队列
    message_queue.put(topic)
    
    # 启动研究线程
    research_thread = threading.Thread(target=run_research_worker, daemon=True)
    research_thread.start()
    
    return jsonify({'success': True, 'message': '研究会话已启动'})

@app.route('/api/send_message', methods=['POST'])
def send_message():
    global status
    
    if not status['is_running']:
        return jsonify({'error': '没有活跃的研究会话'}), 400
    
    if not status['waiting_for_input']:
        return jsonify({'error': '当前不需要用户输入'}), 400
    
    data = request.get_json()
    message = data.get('message', '').strip()
    
    if not message:
        return jsonify({'error': '消息不能为空'}), 400
    
    logger.info(f"收到用户消息: {message}")
    
    # 发送消息到队列
    message_queue.put(message)
    
    return jsonify({'success': True, 'message': '消息已发送'})

@app.route('/api/download/<filename>')
def download_file(filename):
    try:
        logging.getLogger(__name__).info(f"下载文件: {filename}")
        return send_file(filename, as_attachment=True)
    except FileNotFoundError:
        logging.getLogger(__name__).warning(f"文件未找到: {filename}")
        return jsonify({'error': '文件未找到'}), 404

if __name__ == '__main__':
    # 只在主进程中显示配置信息
    print("✅ 项目配置环境变量已配置")
    
    if auth_vars_configured:
        print("✅ 使用应用注册凭据进行认证")
    else:
        print("ℹ️  使用 Azure CLI 认证（请确保已执行 'az login'）")
    
    print(f"🔧 配置信息:")
    print(f"   Project Endpoint: {AZURE_AI_PROJECT_ENDPOINT}")
    print(f"   Bing Connection: {BING_CONNECTION_NAME}")
    print(f"   Research Model: {DEEP_RESEARCH_MODEL}")
    print(f"   Agent Model: {AGENT_MODEL}")
    
    port = int(os.environ.get('PORT', 5000))
    
    print("🔍 启动 Deep Research Web UI...")
    if FLASK_HOST == '127.0.0.1':
        print(f"📍 本地访问地址: http://localhost:{port}")
        print(f"📍 或者访问: http://127.0.0.1:{port}")
    else:
        print(f"📍 访问地址: http://{FLASK_HOST}:{port}")
    print("📄 日志文件: " + log_filename)
    print("⏹️  按 Ctrl+C 停止服务")
    print("-" * 50)
    
    # 生产环境配置
    app.run(debug=FLASK_DEBUG, host=FLASK_HOST, port=port)