"""超级鹰打码平台工具"""
import requests
from loguru import logger


def chaojiying_recognize(image_bytes: bytes, codetype: str = '9101') -> dict:
    """调用超级鹰打码平台识别滑块位置
    
    codetype 常用类型:
    - 9101: 滑块验证码，返回滑动距离（单个数字）
    - 9102: 滑块验证码，返回坐标 x,y
    - 9004: 坐标点选，返回 x,y
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
            
            # 根据不同的返回格式解析
            if ',' in pic_str:
                # 坐标格式: "123,45"
                coords = pic_str.split(',')
                return {
                    'x': int(coords[0]),
                    'y': int(coords[1]),
                    'distance': None,
                    'pic_id': result.get('pic_id')
                }
            elif pic_str.isdigit():
                # 滑动距离格式: "123"
                return {
                    'x': None,
                    'y': None,
                    'distance': int(pic_str),
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
