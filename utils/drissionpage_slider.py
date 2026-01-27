#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 DrissionPage 的滑块验证处理模块
利用 DrissionPage 内置的人类化拖拽功能处理滑块验证
"""

import time
import random
import traceback
from typing import Optional, Tuple, Any
from loguru import logger

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    DRISSIONPAGE_AVAILABLE = True
except ImportError:
    DRISSIONPAGE_AVAILABLE = False
    logger.warning("DrissionPage 未安装")


class DrissionPageSlider:
    """基于 DrissionPage 的滑块验证处理器"""

    def __init__(self, user_id="default", headless=True):
        self.user_id = user_id
        self.headless = headless
        self.page = None
        self.pure_user_id = self._extract_pure_user_id(user_id)
        if not DRISSIONPAGE_AVAILABLE:
            raise ImportError("DrissionPage 未安装")

    def _extract_pure_user_id(self, user_id):
        """提取纯用户ID"""
        if "_" in user_id:
            parts = user_id.split("_")
            if len(parts) >= 2 and parts[-1].isdigit() and len(parts[-1]) >= 10:
                return "_".join(parts[:-1])
        return user_id

    def init_browser(self):
        """初始化浏览器"""
        try:
            logger.info(f"[{self.pure_user_id}][DrissionPage] 初始化浏览器...")
            options = ChromiumOptions()
            if self.headless:
                options.headless(True)
            options.set_argument("--no-sandbox")
            options.set_argument("--disable-blink-features=AutomationControlled")
            options.set_argument("--disable-dev-shm-usage")
            options.set_argument("--disable-gpu")
            options.set_argument("--lang=zh-CN")
            width = random.choice([1920, 1680, 1600, 1440])
            height = random.choice([1080, 1050, 900])
            options.set_argument(f"--window-size={width},{height}")
            self.page = ChromiumPage(options)
            logger.info(f"[{self.pure_user_id}][DrissionPage] 浏览器初始化成功")
            return True
        except Exception as e:
            logger.error(f"[{self.pure_user_id}][DrissionPage] 初始化浏览器失败: {e}")
            return False

    def navigate_to(self, url):
        """导航到指定URL"""
        try:
            if not self.page:
                return False
            logger.info(f"[{self.pure_user_id}][DrissionPage] 导航到: {url}")
            self.page.get(url)
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"[{self.pure_user_id}][DrissionPage] 导航失败: {e}")
            return False

    def find_slider_elements(self):
        """查找滑块元素"""
        try:
            if not self.page:
                return None, None
            button_selectors = ["#nc_1_n1z", ".nc_iconfont", ".btn_slide"]
            track_selectors = ["#nc_1_n1t", ".nc_scale", ".nc-scale"]
            slider_button = None
            slider_track = None
            for selector in button_selectors:
                try:
                    element = self.page.ele(selector, timeout=1)
                    if element:
                        logger.info(f"[{self.pure_user_id}][DrissionPage] 找到滑块按钮: {selector}")
                        slider_button = element
                        break
                except Exception:
                    continue
            for selector in track_selectors:
                try:
                    element = self.page.ele(selector, timeout=1)
                    if element:
                        logger.info(f"[{self.pure_user_id}][DrissionPage] 找到滑块轨道: {selector}")
                        slider_track = element
                        break
                except Exception:
                    continue
            return slider_button, slider_track
        except Exception as e:
            logger.error(f"[{self.pure_user_id}][DrissionPage] 查找滑块元素失败: {e}")
            return None, None

    def calculate_distance(self, slider_button, slider_track):
        """计算滑动距离"""
        try:
            track_rect = slider_track.rect
            button_rect = slider_button.rect
            distance = track_rect["width"] - button_rect["width"]
            distance += random.uniform(-2, 2)
            logger.info(f"[{self.pure_user_id}][DrissionPage] 计算滑动距离: {distance:.1f}px")
            return distance
        except Exception as e:
            logger.error(f"[{self.pure_user_id}][DrissionPage] 计算滑动距离失败: {e}")
            return 0

    def solve_slider(self, max_retries=3):
        """处理滑块验证"""
        try:
            logger.info(f"[{self.pure_user_id}][DrissionPage] 开始处理滑块验证...")
            for attempt in range(1, max_retries + 1):
                logger.info(f"[{self.pure_user_id}][DrissionPage] 第 {attempt}/{max_retries} 次尝试")
                slider_button, slider_track = self.find_slider_elements()
                if not slider_button:
                    logger.warning(f"[{self.pure_user_id}][DrissionPage] 未找到滑块按钮")
                    time.sleep(1)
                    continue
                if not slider_track:
                    logger.warning(f"[{self.pure_user_id}][DrissionPage] 未找到滑块轨道")
                    time.sleep(1)
                    continue
                distance = self.calculate_distance(slider_button, slider_track)
                if distance <= 0:
                    logger.warning(f"[{self.pure_user_id}][DrissionPage] 滑动距离无效")
                    continue
                try:
                    logger.info(f"[{self.pure_user_id}][DrissionPage] 执行拖拽: {distance:.1f}px")
                    slider_button.hover()
                    time.sleep(random.uniform(0.1, 0.3))
                    slider_button.drag(distance, 0, duration=random.uniform(0.5, 1.0))
                    logger.info(f"[{self.pure_user_id}][DrissionPage] 拖拽完成")
                except Exception as drag_e:
                    logger.error(f"[{self.pure_user_id}][DrissionPage] 拖拽失败: {drag_e}")
                    continue
                time.sleep(1.5)
                if self.check_success():
                    logger.success(f"[{self.pure_user_id}][DrissionPage] 滑块验证成功!")
                    return True
                else:
                    logger.warning(f"[{self.pure_user_id}][DrissionPage] 验证未通过，准备重试...")
                    time.sleep(1)
            logger.error(f"[{self.pure_user_id}][DrissionPage] 滑块验证失败，已尝试 {max_retries} 次")
            return False
        except Exception as e:
            logger.error(f"[{self.pure_user_id}][DrissionPage] 处理滑块验证异常: {e}")
            return False

    def check_success(self):
        """检查验证是否成功"""
        try:
            slider_button, _ = self.find_slider_elements()
            if not slider_button:
                logger.info(f"[{self.pure_user_id}][DrissionPage] 滑块元素已消失，验证成功")
                return True
            success_selectors = [".nc-success", "text:验证成功", "text:验证通过"]
            for selector in success_selectors:
                try:
                    element = self.page.ele(selector, timeout=0.5)
                    if element:
                        return True
                except Exception:
                    continue
            failure_selectors = ["text:验证失败", "text:点击框体重试", "text:请重试"]
            for selector in failure_selectors:
                try:
                    element = self.page.ele(selector, timeout=0.5)
                    if element:
                        try:
                            element.click()
                            time.sleep(1)
                        except Exception:
                            pass
                        return False
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.error(f"[{self.pure_user_id}][DrissionPage] 检查验证结果失败: {e}")
            return False

    def close_browser(self):
        """关闭浏览器"""
        try:
            if self.page:
                self.page.quit()
                self.page = None
                logger.info(f"[{self.pure_user_id}][DrissionPage] 浏览器已关闭")
        except Exception as e:
            logger.warning(f"[{self.pure_user_id}][DrissionPage] 关闭浏览器时出错: {e}")


def solve_slider_with_drissionpage(url, user_id="default", headless=True, max_retries=3):
    """使用 DrissionPage 处理滑块验证的便捷函数"""
    slider = None
    try:
        slider = DrissionPageSlider(user_id=user_id, headless=headless)
        if not slider.init_browser():
            return False, None
        if not slider.navigate_to(url):
            return False, None
        time.sleep(2)
        success = slider.solve_slider(max_retries=max_retries)
        if success:
            try:
                cookies = slider.page.cookies(as_dict=True)
                return True, cookies
            except Exception:
                return True, None
        return False, None
    except Exception as e:
        logger.error(f"[{user_id}][DrissionPage] 处理滑块验证异常: {e}")
        return False, None
    finally:
        if slider:
            slider.close_browser()


if __name__ == "__main__":
    test_url = "https://example.com/slider"
    success, cookies = solve_slider_with_drissionpage(
        url=test_url, user_id="test_user", headless=False, max_retries=3
    )
    print(f"验证结果: {'成功' if success else '失败'}")
