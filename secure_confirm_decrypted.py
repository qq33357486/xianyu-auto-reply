"""
自动确认发货模块 - 解密版本
这是secure_confirm_ultra.py的解密版本，用于自动确认发货功能
"""

import asyncio
import json
import time
import aiohttp
from loguru import logger
from utils.xianyu_utils import generate_sign, trans_cookies


class SecureConfirm:
    """自动确认发货类"""

    def __init__(self, session, cookies_str, cookie_id, main_instance=None):
        """
        初始化确认发货实例

        Args:
            session: aiohttp会话对象
            cookies_str: Cookie字符串
            cookie_id: Cookie ID
            main_instance: 主实例对象（XianyuLive）
        """
        self.session = session
        self.cookies_str = cookies_str
        self.cookie_id = cookie_id
        self.main_instance = main_instance

        # 解析cookies
        self.cookies = trans_cookies(cookies_str) if cookies_str else {}

        # Token相关属性
        self.current_token = None
        self.last_token_refresh_time = 0
        self.token_refresh_interval = 3600  # 1小时

    def _safe_str(self, obj):
        """安全字符串转换"""
        try:
            return str(obj)
        except:
            return "无法转换的对象"

    async def _get_real_item_id(self):
        """从数据库中获取一个真实的商品ID"""
        try:
            from db_manager import db_manager
            
            # 获取该账号的商品列表
            items = db_manager.get_items_by_cookie(self.cookie_id)
            if items:
                # 返回第一个商品的ID
                item_id = items[0].get('item_id')
                if item_id:
                    logger.debug(f"【{self.cookie_id}】获取到真实商品ID: {item_id}")
                    return item_id
            
            # 如果该账号没有商品，尝试获取任意一个商品ID
            all_items = db_manager.get_all_items()
            if all_items:
                item_id = all_items[0].get('item_id')
                if item_id:
                    logger.debug(f"【{self.cookie_id}】使用其他账号的商品ID: {item_id}")
                    return item_id
            
            logger.warning(f"【{self.cookie_id}】数据库中没有找到任何商品ID")
            return None
            
        except Exception as e:
            logger.error(f"【{self.cookie_id}】获取真实商品ID失败: {self._safe_str(e)}")
            return None

    async def _update_config_cookies(self):
        """更新数据库中的Cookie配置"""
        try:
            from db_manager import db_manager
            # 更新数据库中的cookies
            db_manager.update_cookie_account_info(self.cookie_id, cookie_value=self.cookies_str)
            logger.debug(f"【{self.cookie_id}】已更新数据库中的Cookie")
        except Exception as e:
            logger.error(f"【{self.cookie_id}】更新数据库Cookie失败: {self._safe_str(e)}")


    async def auto_confirm(self, order_id, item_id=None, retry_count=0):
        """自动确认发货 - 使用真实商品ID刷新token"""
        if retry_count >= 4:  # 最多重试3次
            logger.error("自动确认发货失败，重试次数过多")
            return {"error": "自动确认发货失败，重试次数过多"}

        # 保存item_id供Token刷新使用
        if item_id:
            self._current_item_id = item_id
            logger.debug(f"【{self.cookie_id}】设置当前商品ID: {item_id}")

        # 确保session已创建
        if not self.session:
            raise Exception("Session未创建")

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': str(int(time.time()) * 1000),
            'sign': '',
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.logistic.consign.dummy',
            'sessionOption': 'AutoLoginOnly',
        }

        data_val = '{"orderId":"' + order_id + '", "tradeText":"","picList":[],"newUnconsign":true}'
        data = {
            'data': data_val,
        }

        # 始终从最新的cookies中获取_m_h5_tk token（刷新后cookies会被更新）
        token = trans_cookies(self.cookies_str).get('_m_h5_tk', '').split('_')[0] if trans_cookies(self.cookies_str).get('_m_h5_tk') else ''

        if token:
            logger.info(f"使用cookies中的_m_h5_tk token: {token}")
        else:
            logger.warning("cookies中没有找到_m_h5_tk token")

        sign = generate_sign(params['t'], token, data_val)
        params['sign'] = sign

        # 构建请求头，必须包含Cookie
        headers = {
            'accept': 'application/json',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.goofish.com',
            'referer': 'https://www.goofish.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'cookie': self.cookies_str
        }

        try:
            logger.info(f"【{self.cookie_id}】开始自动确认发货，订单ID: {order_id}")
            
            # 【修复】使用 asyncio.wait_for 包装请求，避免 aiohttp 内部超时上下文错误
            async def do_confirm_request():
                async with self.session.post(
                    'https://h5api.m.goofish.com/h5/mtop.taobao.idle.logistic.consign.dummy/1.0/',
                    params=params,
                    data=data,
                    headers=headers
                ) as response:
                    res_json = await response.json()
                    # 返回响应头和JSON数据（使用不同变量名避免作用域冲突）
                    response_headers = dict(response.headers)
                    return response_headers, res_json
            
            try:
                response_headers, res_json = await asyncio.wait_for(do_confirm_request(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error(f"【{self.cookie_id}】自动确认发货请求超时（30秒）")
                if retry_count < 2:
                    logger.info(f"【{self.cookie_id}】超时，准备重试...")
                    return await self.auto_confirm(order_id, item_id, retry_count + 1)
                return {"error": "请求超时", "order_id": order_id}

            # 检查并更新Cookie
            if 'set-cookie' in response_headers or 'Set-Cookie' in response_headers:
                new_cookies = {}
                cookie_header = response_headers.get('set-cookie') or response_headers.get('Set-Cookie', '')
                if isinstance(cookie_header, str):
                    cookie_list = [cookie_header]
                else:
                    cookie_list = cookie_header if isinstance(cookie_header, list) else []
                
                for cookie in cookie_list:
                    if '=' in cookie:
                        name, value = cookie.split(';')[0].split('=', 1)
                        new_cookies[name.strip()] = value.strip()

                # 更新cookies
                if new_cookies:
                    self.cookies.update(new_cookies)
                    # 生成新的cookie字符串
                    self.cookies_str = '; '.join([f"{k}={v}" for k, v in self.cookies.items()])
                    # 更新数据库中的Cookie
                    await self._update_config_cookies()
                    logger.debug("已更新Cookie到数据库")

            logger.info(f"【{self.cookie_id}】自动确认发货响应: {res_json}")

            # 检查响应结果
            if res_json.get('ret') and res_json['ret'][0] == 'SUCCESS::调用成功':
                logger.info(f"【{self.cookie_id}】✅ 自动确认发货成功，订单ID: {order_id}")
                return {"success": True, "order_id": order_id}
            else:
                error_msg = res_json.get('ret', ['未知错误'])[0] if res_json.get('ret') else '未知错误'
                logger.warning(f"【{self.cookie_id}】❌ 自动确认发货失败: {error_msg}")

                # 检测Token过期错误，触发强制刷新后再重试
                if ('TOKEN_EXOIRED' in error_msg or 'TOKEN_EXPIRED' in error_msg or 'ILLEGAL_ACCESS' in error_msg):
                    if retry_count < 2 and self.main_instance:
                        logger.info(f"【{self.cookie_id}】检测到Token过期，触发强制刷新...")
                        
                        # 调用主实例的强制刷新方法（绕过冷却机制）
                        try:
                            refresh_success = await self.main_instance.force_refresh_token()
                            
                            if refresh_success:
                                # 刷新成功，同步最新cookies后重试
                                self.cookies_str = self.main_instance.cookies_str
                                self.cookies = trans_cookies(self.cookies_str)
                                logger.info(f"【{self.cookie_id}】Token刷新成功，准备重试确认发货...")
                                await asyncio.sleep(1)  # 等待1秒让新Token生效
                                return await self.auto_confirm(order_id, item_id, retry_count + 1)
                            else:
                                logger.warning(f"【{self.cookie_id}】Token刷新失败，将订单加入待确认队列...")
                                # 将订单加入待确认队列，等下次Token刷新成功后自动重试
                                await self.main_instance.add_pending_confirm_order(order_id, item_id)
                                return {"error": "Token刷新失败，已加入待确认队列", "order_id": order_id, "queued": True}
                        except Exception as refresh_e:
                            logger.error(f"【{self.cookie_id}】强制刷新Token异常: {self._safe_str(refresh_e)}")
                            # 刷新异常时也加入队列
                            try:
                                await self.main_instance.add_pending_confirm_order(order_id, item_id)
                            except:
                                pass
                            return {"error": f"Token刷新异常: {self._safe_str(refresh_e)}", "order_id": order_id}
                    else:
                        # 没有主实例或重试次数已达上限，尝试从主实例同步cookies后重试
                        if self.main_instance:
                            self.cookies_str = self.main_instance.cookies_str
                            self.cookies = trans_cookies(self.cookies_str)
                            logger.info(f"【{self.cookie_id}】已同步最新cookies，准备重试...")

                return await self.auto_confirm(order_id, item_id, retry_count + 1)

        except Exception as e:
            logger.error(f"【{self.cookie_id}】自动确认发货API请求异常: {self._safe_str(e)}")
            await asyncio.sleep(0.5)

            # 网络异常也进行重试
            if retry_count < 2:
                logger.info(f"【{self.cookie_id}】网络异常，准备重试...")
                return await self.auto_confirm(order_id, item_id, retry_count + 1)

            return {"error": f"网络异常: {self._safe_str(e)}", "order_id": order_id}
