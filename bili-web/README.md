# Bili Web

作者：阿童木  
联系方式：2595213474@qq.com

Bili Web 是一个个人学习用的哔哩哔哩视频解析下载小站，基于 FastAPI 后端和原生 HTML/CSS/JS 前端实现。项目用于学习视频解析流程、Docker 部署、Nginx 反向代理、HTTPS 配置、文件下载任务管理等 Web 工程实践。

## 项目解说

这个项目的目标是把本地下载工具改造成一个可以部署到服务器上的网页工具。用户可以在网页中粘贴 BV 号、AV 号、完整视频链接或手机分享短链接，后端负责解析视频信息、获取可用清晰度、下载视频流和音频流，并通过 ffmpeg 合并成 MP4 文件。前端提供扫码登录、临时 Cookie、清晰度选择、任务列表、下载进度、速度显示、封面显示和封面下载等功能。

项目整体采用前后端分离但轻量化的结构：前端是静态页面，后端是 FastAPI 服务，部署时通过 Docker Compose 启动，再由 Nginx 或宝塔面板反向代理到域名。它更适合个人学习、自用测试和部署练习，不建议作为公开商业服务使用。

## 功能特性

- BV / AV / 视频链接解析
- 手机分享短链接解析
- 分 P 选择
- DASH 视频、音频流识别
- 后台下载
- ffmpeg 合并视频和音频
- 任务列表、取消任务、失败原因展示
- 分片下载、备用链接重试、下载速度和剩余时间显示
- 过期文件自动清理，默认保留 24 小时
- 扫码登录、临时 Cookie 检查、登录昵称和头像显示
- 视频封面显示和封面下载
- 图片代理，减少头像和封面破图问题
- Docker + Nginx 部署骨架

## 免责声明

本项目仅供个人学习、技术研究和自用测试，主要用于理解 Web 服务搭建、接口封装、任务队列、媒体流处理和服务器部署流程。

请勿将本项目用于侵犯版权、批量抓取、商业盗版传播、绕过平台限制或违反哔哩哔哩用户协议的用途。使用者应自行遵守当地法律法规、平台规则和版权要求，并自行承担因使用本项目造成的账号风控、服务器流量消耗、版权纠纷或其他风险。

本项目不提供任何视频资源，也不存储第三方平台内容。项目中的解析、下载、合并等功能仅作为技术学习示例。若你将本项目部署到公网，请务必增加访问控制、频率限制和安全保护，避免被他人滥用。

如果本项目基于或参考了其他开源项目，请遵守对应开源许可证。若你基于原 Bili23 Downloader 源码继续改造，需要遵守原项目的 GPL-3.0 许可证。

## 项目定位

这个项目默认不需要登录，也不需要额外访问密钥，适合放在自己的服务器和域名下学习部署流程。公开视频解析下载会涉及版权、平台条款、带宽成本和账号风控，请只用于个人学习研究或自用工具。若你基于原 Bili23 Downloader 源码继续改造，需要遵守原项目的 GPL-3.0 许可证。

## 为什么保留后端

纯前端页面会遇到几个硬限制：浏览器跨域限制、B 站媒体直链防盗链、以及视频流和音频流需要 ffmpeg 合并。因此这里保留了一个很薄的 FastAPI 后端，前端只负责交互，后端负责解析、下载和合并。

## 本地运行

```bash
cd bili-web
cp .env.example .env
docker compose up -d --build
```

打开：

```text
http://localhost
```

不要直接双击打开 `frontend/index.html`。网页需要通过后端服务访问，否则浏览器无法请求 `/api/health`、`/api/parse` 等接口，页面会显示后端未连接。

## 服务器部署

如果你使用宝塔面板，优先看：[BAOTA_DEPLOY.md](./BAOTA_DEPLOY.md)。

1. 安装 Docker 和 Docker Compose。
2. 把 `bili-web` 上传到服务器，例如 `/opt/bili-web`。
3. 配置环境变量：

```bash
cd /opt/bili-web
cp .env.example .env
nano .env
```

4. 启动服务：

```bash
docker compose up -d --build
```

5. 域名解析到服务器 IP。
6. 使用 Nginx Proxy Manager、宝塔、1Panel，或服务器自带 Nginx/Caddy 配置 HTTPS 反代到本项目的 80 端口。

`nginx/https-example.conf` 里放了一个原生 Nginx + Let's Encrypt 的反代参考，示例域名已按 `bld.atm6.cn` 填好。宝塔面板用户通常不需要使用这个文件，直接在宝塔里添加反向代理即可。

## 环境变量

- `BILI_COOKIE`: 可选。需要登录状态、高画质或会员内容时填写浏览器里的 B 站 Cookie。
- `MAX_DOWNLOAD_MB`: 单个媒体流最大体积，默认 2048 MB。
- `MAX_PARALLEL_DOWNLOADS`: 同时下载任务数，默认 2。
- `CHUNK_DOWNLOAD_WORKERS`: 单个大文件分片下载线程数，默认 6。
- `CHUNK_DOWNLOAD_MIN_MB`: 超过多少 MB 开启分片下载，默认 20。
- `DOWNLOAD_RETRY_COUNT`: 下载失败自动重试次数，默认 3。
- `FILE_RETENTION_HOURS`: 下载完成后的文件保留小时数，默认 24。
- `CLEANUP_INTERVAL_MINUTES`: 自动清理检查间隔，默认 30。

## API

解析：

```http
POST /api/parse
Content-Type: application/json

{"url":"https://www.bilibili.com/video/BVxxxx","page":1}
```

创建下载任务：

```http
POST /api/download
Content-Type: application/json

{"url":"https://www.bilibili.com/video/BVxxxx","page":1,"quality":80,"kind":"merged"}
```

查询任务：

```http
GET /api/tasks/{task_id}
```

任务列表：

```http
GET /api/tasks
```

取消任务：

```http
POST /api/tasks/{task_id}/cancel
```

清理过期文件：

```http
POST /api/tasks/cleanup
```

下载文件：

```http
GET /api/files/{task_id}
```

## 下一步可增强

- 任务持久化，服务重启后保留记录
- 前端替换为 Vue + Vite
- 增加服务器磁盘空间显示
