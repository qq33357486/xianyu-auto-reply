"""
AI回复引擎模块
集成XianyuAutoAgent的AI回复功能到现有项目中

【P0/P1 最小化修改版】
- 修复 P1-1 (高成本): detect_intent 改为本地关键词
- 修复 P0-2 (部署陷阱): 移除客户端缓存，实现无状态
- 修复 P1-3 (健壮性): 增强 Gemini 消息格式化
- 遵照指示，未修复 P0-1 (议价竞争条件)
"""

import os
import json
import time
import sqlite3
import requests  # 确保已导入
import threading
from typing import List, Dict, Optional
from loguru import logger
from openai import OpenAI
from db_manager import db_manager


class AIReplyEngine:
    """AI回复引擎"""
    
    def __init__(self):
        # 修复 P0-2: 移除有状态的缓存，以支持多进程部署
        # self.clients = {}  # 已移除
        # self.agents = {}   # 已移除
        # self.client_last_used = {}  # 已移除
        self._init_default_prompt()
        # 用于控制同一chat_id消息的串行处理
        self._chat_locks = {}
        self._chat_locks_lock = threading.Lock()
    
    def _init_default_prompt(self):
        """初始化默认提示词（统一提示词，不再分类）"""
        self.default_system_prompt = '''你是一位资深闲鱼卖家客服，负责回复买家咨询。

## 回复要求
- 语言简短友好，每句≤15字，总字数≤50字
- 像真人聊天一样自然，不要太官方
- 根据对话上下文智能判断买家意图并回复

## 你需要处理的场景
1. **议价**：友好但坚定，可适当给小优惠，但要守住底线
2. **商品咨询**：基于商品信息如实回答，不过度承诺
3. **物流售后**：耐心解答，给出实用建议
4. **闲聊**：简短回应，引导回到交易

## 注意事项
- 结合商品信息和对话历史回复
- 如果买家发图片，仔细查看并针对性回答
- 议价时参考议价设置中的优惠限制'''
    
    def _create_openai_client(self, cookie_id: str) -> Optional[OpenAI]:
        """
        (原 get_client) 创建指定账号的OpenAI客户端
        修复 P0-2: 移除了缓存逻辑，以支持多进程无状态部署
        """
        settings = db_manager.get_ai_reply_settings(cookie_id)
        if not settings['ai_enabled'] or not settings['api_key']:
            return None
        
        try:
            logger.info(f"创建新的OpenAI客户端实例 {cookie_id}: base_url={settings['base_url']}, api_key={'***' + settings['api_key'][-4:] if settings['api_key'] else 'None'}")
            client = OpenAI(
                api_key=settings['api_key'],
                base_url=settings['base_url']
            )
            logger.info(f"为账号 {cookie_id} 创建OpenAI客户端成功，实际base_url: {client.base_url}")
            return client
        except Exception as e:
            logger.error(f"创建OpenAI客户端失败 {cookie_id}: {e}")
            return None

    def _is_dashscope_api(self, settings: dict) -> bool:
        """判断是否为DashScope API - 只有选择自定义模型时才使用"""
        model_name = settings.get('model_name', '')
        base_url = settings.get('base_url', '')

        is_custom_model = model_name.lower() in ['custom', '自定义', 'dashscope', 'qwen-custom']
        is_dashscope_url = 'dashscope.aliyuncs.com' in base_url

        logger.info(f"API类型判断: model_name={model_name}, is_custom_model={is_custom_model}, is_dashscope_url={is_dashscope_url}")

        return is_custom_model and is_dashscope_url

    def _is_gemini_api(self, settings: dict) -> bool:
        """判断是否为Gemini API (通过模型名称)"""
        model_name = settings.get('model_name', '').lower()
        return 'gemini' in model_name

    def _call_dashscope_api(self, settings: dict, messages: list, max_tokens: int = 1024, temperature: float = 0.7) -> str:
        """调用DashScope API"""
        base_url = settings['base_url']
        if '/apps/' in base_url:
            app_id = base_url.split('/apps/')[-1].split('/')[0]
        else:
            raise ValueError("DashScope API URL中未找到app_id")

        url = f"https://dashscope.aliyuncs.com/api/v1/apps/{app_id}/completion"

        system_content = ""
        user_content = ""
        for msg in messages:
            if msg['role'] == 'system':
                system_content = msg['content']
            elif msg['role'] == 'user':
                user_content = msg['content'] # 假设 user prompt 已在 generate_reply 中构建好

        if system_content and user_content:
            prompt = f"{system_content}\n\n用户问题：{user_content}\n\n请直接回答用户的问题："
        elif user_content:
            prompt = user_content
        else:
            prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

        data = {
            "input": {"prompt": prompt},
            "parameters": {"max_tokens": max_tokens, "temperature": temperature},
            "debug": {}
        }
        headers = {
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json"
        }

        logger.info(f"DashScope API请求: {url}")
        logger.info(f"发送的prompt: {prompt[:100]}...") # 避免 prompt 过长
        logger.debug(f"请求数据: {json.dumps(data, ensure_ascii=False)}")

        response = requests.post(url, headers=headers, json=data, timeout=180)

        if response.status_code != 200:
            logger.error(f"DashScope API请求失败: {response.status_code} - {response.text}")
            raise Exception(f"DashScope API请求失败: {response.status_code} - {response.text}")

        result = response.json()
        logger.debug(f"DashScope API响应: {json.dumps(result, ensure_ascii=False)}")

        if 'output' in result and 'text' in result['output']:
            return result['output']['text'].strip()
        else:
            raise Exception(f"DashScope API响应格式错误: {result}")

    def _call_gemini_api(self, settings: dict, messages: list, max_tokens: int = 1024, temperature: float = 0.7) -> str:
        """
        调用Google Gemini REST API (v1beta)
        """
        api_key = settings['api_key']
        model_name = settings['model_name'] 
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

        headers = {"Content-Type": "application/json"}

        # --- 转换消息格式 (修复 P1-3: 增强健壮性) ---
        system_instruction = ""
        user_content_parts = []

        # 遍历消息，找到 system 和所有的 user parts
        for msg in messages:
            if msg['role'] == 'system':
                system_instruction = msg['content']
            elif msg['role'] == 'user':
                # 我们只关心 user content
                user_content_parts.append(msg['content'])
        
        # 将所有 user parts 合并为最后的 user_content
        # 在我们的使用场景中 (generate_reply)，只会有一个 user part，但这样更安全
        user_content = "\n".join(user_content_parts)

        if not user_content:
            logger.warning(f"Gemini API 调用: 未在消息中找到 'user' 角色内容。Messages: {messages}")
            raise ValueError("未在消息中找到用户内容 (user content)")
        # --- 消息格式转换结束 ---

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_content}]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        logger.info(f"Calling Gemini REST API: {url.split('?')[0]}")
        logger.debug(f"Gemini Payload: {json.dumps(payload, ensure_ascii=False)}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=180)

        if response.status_code != 200:
            logger.error(f"Gemini API 请求失败: {response.status_code} - {response.text}")
            raise Exception(f"Gemini API 请求失败: {response.status_code} - {response.text}")
            
        result = response.json()
        logger.debug(f"Gemini API 响应: {json.dumps(result, ensure_ascii=False)}")

        try:
            reply_text = result['candidates'][0]['content']['parts'][0]['text']
            return reply_text.strip()
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Gemini API 响应格式错误: {result} - {e}")
            raise Exception(f"Gemini API 响应格式错误: {result}")

    def _call_openai_api(self, client: OpenAI, settings: dict, messages: list, max_tokens: int = 8319, temperature: float = 0.7) -> str:
        """调用OpenAI兼容API"""
        try:
            logger.info(f"调用OpenAI API: model={settings['model_name']}, base_url={settings.get('base_url', 'default')}")
            response = client.chat.completions.create(
                model=settings['model_name'],
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=180
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API调用失败: {e}")
            # 如果有详细的错误信息，打印出来
            if hasattr(e, 'response'):
                logger.error(f"响应状态码: {getattr(e.response, 'status_code', 'unknown')}")
                logger.error(f"响应内容: {getattr(e.response, 'text', 'unknown')}")
            raise

    def is_ai_enabled(self, cookie_id: str) -> bool:
        """检查指定账号是否启用AI回复"""
        settings = db_manager.get_ai_reply_settings(cookie_id)
        return settings['ai_enabled']
    
    def _get_system_prompt(self, settings: dict) -> str:
        """获取系统提示词（优先使用自定义，否则使用默认）"""
        custom_prompt = settings.get('custom_prompts', '')
        if custom_prompt:
            # 兼容旧的 JSON 格式：如果是 JSON，取 default 值
            if custom_prompt.strip().startswith('{'):
                try:
                    prompts_dict = json.loads(custom_prompt)
                    # 优先取 default，否则取第一个值
                    return prompts_dict.get('default', list(prompts_dict.values())[0] if prompts_dict else self.default_system_prompt)
                except json.JSONDecodeError:
                    pass
            # 新格式：直接是 Markdown 字符串
            return custom_prompt
        return self.default_system_prompt
    
    def _get_chat_lock(self, chat_id: str) -> threading.Lock:
        """获取指定chat_id的锁，如果不存在则创建"""
        with self._chat_locks_lock:
            if chat_id not in self._chat_locks:
                self._chat_locks[chat_id] = threading.Lock()
            return self._chat_locks[chat_id]
    
    def generate_reply(self, message: str, item_info: dict, chat_id: str,
                      cookie_id: str, user_id: str, item_id: str,
                      skip_wait: bool = False, image_urls: list = None) -> Optional[str]:
        """生成AI回复
        
        Args:
            message: 用户消息文本
            item_info: 商品信息
            chat_id: 聊天ID
            cookie_id: Cookie ID
            user_id: 用户ID
            item_id: 商品ID
            skip_wait: 是否跳过内部等待
            image_urls: 用户发送的图片URL列表（用于多模态AI）
        """
        if not self.is_ai_enabled(cookie_id):
            return None
        
        try:
            # 在锁外先保存用户消息到数据库，让所有消息都能立即保存
            message_created_at = self.save_conversation(chat_id, cookie_id, user_id, item_id, "user", message)
            
            # 如果调用方已经实现了去抖（debounce），可以通过 skip_wait=True 跳过内部等待
            if not skip_wait:
                logger.info(f"【{cookie_id}】消息已保存，等待10秒收集后续消息: {message[:20]}... (时间:{message_created_at})")
                # 固定等待10秒，等待可能的后续消息（在锁外延迟，避免阻塞其他消息保存）
                time.sleep(10)
            else:
                logger.info(f"【{cookie_id}】消息已保存（外部防抖已启用，跳过内部等待）: {message[:20]}... (时间:{message_created_at})")
            
            # 获取该chat_id的锁，确保同一对话的消息串行处理
            chat_lock = self._get_chat_lock(chat_id)
            
            # 使用锁确保同一chat_id的消息串行处理
            with chat_lock:
                # 获取最近时间窗口内的所有用户消息
                # 如果 skip_wait=True（外部防抖），查询窗口为6秒（1秒防抖 + 5秒缓冲）
                # 如果 skip_wait=False（内部等待），查询窗口为25秒（10秒等待 + 10秒消息间隔 + 5秒缓冲）
                query_seconds = 6 if skip_wait else 25
                recent_messages = self._get_recent_user_messages(chat_id, cookie_id, seconds=query_seconds)
                logger.info(f"【{cookie_id}】最近{query_seconds}秒内的消息: {[msg['content'][:20] for msg in recent_messages]}")
                
                if recent_messages and len(recent_messages) > 0:
                    # 只处理最后一条消息（时间戳最新的）
                    latest_message = recent_messages[-1]
                    if message_created_at != latest_message['created_at']:
                        logger.info(f"【{cookie_id}】检测到有更新的消息，跳过当前消息: {message[:20]}... (时间:{message_created_at})，最新消息: {latest_message['content'][:20]}... (时间:{latest_message['created_at']})")
                        return None
                    else:
                        logger.info(f"【{cookie_id}】当前消息是最新消息，开始处理: {message[:20]}... (时间:{message_created_at})")
                
                # 1. 获取AI回复设置
                settings = db_manager.get_ai_reply_settings(cookie_id)

                # 3. 获取对话历史
                context = self.get_conversation_context(chat_id, cookie_id)

                # 4. 获取议价次数
                bargain_count = self.get_bargain_count(chat_id, cookie_id)

                # 5. 获取系统提示词（统一提示词，不再分类）
                system_prompt = self._get_system_prompt(settings)

                # 7. 构建商品信息
                item_desc = f"商品标题: {item_info.get('title', '未知')}\n"
                item_desc += f"商品价格: {item_info.get('price', '未知')}元\n"
                item_desc += f"商品描述: {item_info.get('desc', '无')}"

                # 8. 构建对话历史
                context_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in context[-10:]])  # 最近10条

                # 9. 构建用户消息
                max_bargain_rounds = settings.get('max_bargain_rounds', 3)
                max_discount_percent = settings.get('max_discount_percent', 10)
                max_discount_amount = settings.get('max_discount_amount', 100)

                # 处理图片消息：当用户发送图片时，message 可能为空或 "[图片]"
                # 需要明确告知 AI 查看并分析图片
                if image_urls and len(image_urls) > 0:
                    # 用户发送了图片
                    if not message or message.strip() in ["", "[图片]", "图片"]:
                        # 纯图片消息，没有附带文字
                        user_message_text = f"用户发送了 {len(image_urls)} 张图片，请仔细查看图片内容并给出相关回复。如果图片是商品截图、问题截图或其他咨询相关内容，请针对性回答。"
                    else:
                        # 图片+文字消息
                        user_message_text = f"{message}\n\n（用户同时发送了 {len(image_urls)} 张图片，请结合图片内容回复）"
                else:
                    user_message_text = message

                user_prompt = f"""商品信息：
{item_desc}

对话历史：
{context_str}

议价设置：
- 当前议价次数：{bargain_count}
- 最大议价轮数：{max_bargain_rounds}
- 最大优惠百分比：{max_discount_percent}%
- 最大优惠金额：{max_discount_amount}元

用户消息：{user_message_text}

请根据以上信息生成回复："""

                # 10. 调用AI生成回复
                # 构建用户消息内容（支持多模态：文本+图片）
                if image_urls and len(image_urls) > 0:
                    # 多模态消息格式（OpenAI兼容格式）
                    user_content = [{"type": "text", "text": user_prompt}]
                    for img_url in image_urls:
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": img_url}
                        })
                    logger.info(f"【{cookie_id}】构建多模态消息，包含 {len(image_urls)} 张图片")
                else:
                    # 纯文本消息
                    user_content = user_prompt
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]

                reply = None # 初始化 reply 变量

                if self._is_dashscope_api(settings):
                    logger.info(f"使用DashScope API生成回复")
                    reply = self._call_dashscope_api(settings, messages, max_tokens=1024, temperature=0.7)
                
                elif self._is_gemini_api(settings):
                    logger.info(f"使用Gemini API生成回复")
                    reply = self._call_gemini_api(settings, messages, max_tokens=1024, temperature=0.7)
                
                else:
                    logger.info(f"使用OpenAI兼容API生成回复")
                    # 修复 P0-2: 调用已修改的无状态客户端创建方法
                    client = self._create_openai_client(cookie_id)
                    if not client:
                        return None
                    logger.info(f"messages:{messages}")
                    reply = self._call_openai_api(client, settings, messages, max_tokens=8319, temperature=0.7)

                # 11. 保存AI回复到对话记录
                self.save_conversation(chat_id, cookie_id, user_id, item_id, "assistant", reply)
                
                logger.info(f"AI回复生成成功 (账号: {cookie_id}): {reply}")
                return reply
                
        except Exception as e:
            logger.error(f"AI回复生成失败 {cookie_id}: {e}")
            if hasattr(e, 'response') and hasattr(e.response, 'url'):
                logger.error(f"请求URL: {e.response.url}")
            if hasattr(e, 'request') and hasattr(e.request, 'url'):
                logger.error(f"请求URL: {e.request.url}")
            return None

    async def generate_reply_async(self, message: str, item_info: dict, chat_id: str,
                                   cookie_id: str, user_id: str, item_id: str,
                                   skip_wait: bool = False, image_urls: list = None) -> Optional[str]:
        """
        异步包装器：在独立线程池中执行同步的 `generate_reply`，并返回结果。
        这样可以在异步代码中直接 await，而不阻塞事件循环。
        """
        try:
            import asyncio as _asyncio
            return await _asyncio.to_thread(self.generate_reply, message, item_info, chat_id, cookie_id, user_id, item_id, skip_wait, image_urls)
        except Exception as e:
            logger.error(f"异步生成回复失败: {e}")
            return None
    
    def get_conversation_context(self, chat_id: str, cookie_id: str, limit: int = 20) -> List[Dict]:
        """获取对话上下文"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                cursor.execute('''
                SELECT role, content FROM ai_conversations 
                WHERE chat_id = ? AND cookie_id = ? 
                ORDER BY created_at DESC LIMIT ?
                ''', (chat_id, cookie_id, limit))
                
                results = cursor.fetchall()
                context = [{"role": row[0], "content": row[1]} for row in reversed(results)]
                return context
        except Exception as e:
            logger.error(f"获取对话上下文失败: {e}")
            return []
    
    def save_conversation(self, chat_id: str, cookie_id: str, user_id: str, 
                         item_id: str, role: str, content: str, intent: str = None) -> Optional[str]:
        """保存对话记录，返回创建时间"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                cursor.execute('''
                INSERT INTO ai_conversations 
                (cookie_id, chat_id, user_id, item_id, role, content, intent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (cookie_id, chat_id, user_id, item_id, role, content, intent))
                db_manager.conn.commit()
                
                # 获取刚插入记录的created_at
                cursor.execute('''
                SELECT created_at FROM ai_conversations 
                WHERE rowid = last_insert_rowid()
                ''')
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"保存对话记录失败: {e}")
            return None
    def get_bargain_count(self, chat_id: str, cookie_id: str) -> int:
        """获取议价次数"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                cursor.execute('''
                SELECT COUNT(*) FROM ai_conversations 
                WHERE chat_id = ? AND cookie_id = ? AND intent = 'price' AND role = 'user'
                ''', (chat_id, cookie_id))
                
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"获取议价次数失败: {e}")
            return 0
    
    def _get_recent_user_messages(self, chat_id: str, cookie_id: str, seconds: int = 2) -> List[Dict]:
        """获取最近seconds秒内的所有用户消息（包含内容和时间戳）"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                # 先查询所有该chat的user消息，用于调试
                cursor.execute('''
                SELECT content, created_at, 
                       julianday('now') - julianday(created_at) as time_diff_days,
                       (julianday('now') - julianday(created_at)) * 86400.0 as time_diff_seconds
                FROM ai_conversations 
                WHERE chat_id = ? AND cookie_id = ? AND role = 'user' 
                ORDER BY created_at DESC LIMIT 10
                ''', (chat_id, cookie_id))
                
                all_messages = cursor.fetchall()
                logger.info(f"【调试】chat_id={chat_id} 最近10条user消息: {[(msg[0][:10], msg[1], f'{msg[3]:.2f}秒前') for msg in all_messages]}")
                
                # 正式查询
                cursor.execute('''
                SELECT content, created_at FROM ai_conversations 
                WHERE chat_id = ? AND cookie_id = ? AND role = 'user' 
                AND julianday('now') - julianday(created_at) < (? / 86400.0)
                ORDER BY created_at ASC
                ''', (chat_id, cookie_id, seconds))
                
                results = cursor.fetchall()
                return [{"content": row[0], "created_at": row[1]} for row in results]
        except Exception as e:
            logger.error(f"获取最近用户消息列表失败: {e}")
            return []
    
    def increment_bargain_count(self, chat_id: str, cookie_id: str):
        """(此方法已废弃，通过 get_bargain_count 的 SQL 查询实现)"""
        pass
    
    #
    # --- 修复 P0-2: 移除所有有状态的缓存管理方法 ---
    #
    
    # def clear_client_cache(self, cookie_id: str = None):
    #     """(已移除) 清理客户端缓存"""
    #     pass
    
    # def cleanup_unused_clients(self, max_idle_hours: int = 24):
    #     """(已移除) 清理长时间未使用的客户端"""
    #     pass


# 全局AI回复引擎实例
ai_reply_engine = AIReplyEngine()
