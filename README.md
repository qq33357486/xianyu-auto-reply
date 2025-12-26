# xianyu-auto-reply

本项目基于：https://github.com/zhinianboke/xianyu-auto-reply

修点bug自用。

## Docker 部署（推荐）

```bash
# 1. 创建目录
mkdir xianyu && cd xianyu

# 2. 下载 docker-compose.yml
curl -O https://raw.githubusercontent.com/qq33357486/xianyu-auto-reply/main/docker-compose.yml

# 3. 启动
docker compose up -d

# 4. 查看日志
docker compose logs -f
```

访问 http://localhost:8080 ，默认账号 `admin` / `admin123`

### 自定义配置

编辑 `docker-compose.yml` 修改环境变量：
- `ADMIN_PASSWORD`: 管理员密码
- `JWT_SECRET_KEY`: JWT 密钥（生产环境必须修改）
- 端口映射：修改 `8080:8080` 左边的端口
