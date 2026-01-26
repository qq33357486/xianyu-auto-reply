"""超级鹰打码平台工具"""
import requests
from loguru import logger


def chaojiying_recognize(image_bytes: bytes, codetype: str = '9101') -> dict:
    """调用超级鹰打码平台识别滑块位置
    
    codetype 常用类型:
    - 9101: 通用定位（人工识别），返回固定1个坐标，适合各种滑块
    - 9902: 滑块专用（机器识别），返回两个图形块中心点坐标，适合标准拼图滑块
    - 9901: 单图形块，返回中心点坐标 x,y
    """
    try:
        from db_manager import db_manager
        
        # 从数据库读取配置
        enabled = db_manager.get_system_setting('chaojiying_enabled')
        if enabled not in [True, 'true', '1', 1]:
            logger.info("超级鹰打码平台未启用")
            return None
        
        username = db_manager.get_system_setting('chaojiying_username') or ''
        password = db_manager.get_system_setting('chaojiying_password') or ''
        softid = db_manager.get_system_setting('chaojiying_softid') or ''
        
        if not all([username, password, softid]):
            logger.warning("超级鹰配置不完整，请在系统设置中配置")
            return None
        
        url = "https://upload.chaojiying.net/Upload/Processing.php"
        data = {
            'user': username,
            'pass': password,
            'softid': softid,
            'codetype': codetype
        }
        files = {'userfile': ('captcha.png', image_bytes, 'image/png')}
        response = requests.post(url, data=data, files=files, timeout=30)
        result = response.json()
        logger.info(f"超级鹰返回: err_no={result.get('err_no')}, pic_str={result.get('pic_str')}, codetype={codetype}")
        
        if result.get('err_no') == 0:
            pic_str = result.get('pic_str', '')
            
            # 9902 格式: "x1,y1|x2,y2" - 两个图形块的中心点坐标
            if '|' in pic_str:
                parts = pic_str.split('|')
                coord1 = parts[0].split(',')
                coord2 = parts[1].split(',')
                x1, y1 = int(coord1[0]), int(coord1[1])
                x2, y2 = int(coord2[0]), int(coord2[1])
                # 滑动距离 = 两个x坐标的差的绝对值
                distance = abs(x2 - x1)
                logger.info(f"超级鹰9902解析: 坐标1({x1},{y1}), 坐标2({x2},{y2}), 滑动距离={distance}px")
                return {
                    'x1': x1, 'y1': y1,
                    'x2': x2, 'y2': y2,
                    'x': x1,  # 兼容旧代码
                    'y': y1,
                    'distance': distance,
                    'pic_id': result.get('pic_id')
                }
            # 单坐标格式: "x,y" (9101返回)
            elif ',' in pic_str:
                coords = pic_str.split(',')
                x, y = int(coords[0]), int(coords[1])
                logger.info(f"超级鹰9101解析: 目标坐标({x},{y})")
                return {
                    'x': x,
                    'y': y,
                    'distance': None,
                    'pic_id': result.get('pic_id')
                }
            # 纯数字格式（滑动距离）
            elif pic_str.isdigit():
                distance = int(pic_str)
                logger.info(f"超级鹰解析: 滑动距离={distance}px")
                return {
                    'x': None,
                    'y': None,
                    'distance': distance,
                    'pic_id': result.get('pic_id')
                }
            else:
                logger.warning(f"超级鹰返回格式未知: {pic_str}")
                return None
        else:
            logger.warning(f"超级鹰识别失败: {result.get('err_str')}")
        return None
    except Exception as e:
        logger.error(f"超级鹰API调用异常: {e}")
        return None
