# 宝塔面板部署教程

域名示例：`bld.atm6.cn`

这个教程适合宝塔面板新手。推荐方案是：

```text
访问者 -> bld.atm6.cn -> 宝塔 Nginx -> 反向代理 -> 127.0.0.1:8000 -> Bili Web 后端
```

不要让 Docker 容器直接占用服务器 80/443 端口，因为宝塔 Nginx 通常已经在使用这两个端口。

## 需要准备

- 一台 Linux 服务器
- 宝塔面板
- 域名 `bld.atm6.cn` 已解析到服务器公网 IP
- 宝塔软件商店安装：
  - Nginx
  - Docker 管理器
  - Python 不需要单独装，Docker 镜像里会带
  - ffmpeg 不需要单独装，Docker 镜像里会自动安装

如果终端提示：

```text
docker: command not found
```

说明 Docker 还没装好。先去宝塔软件商店安装 `Docker 管理器`，安装完成后重新打开宝塔终端，再执行：

```bash
docker --version
docker compose version
```

能显示版本号才继续下一步。

## 第 1 步：检查域名解析

进入你的域名 DNS 管理后台，添加：

```text
类型：A
主机记录：bld
记录值：你的服务器公网 IP
```

等待几分钟后，在自己电脑命令行测试：

```bash
ping bld.atm6.cn
```

能看到服务器 IP 就说明解析基本生效。

## 第 2 步：上传项目

宝塔面板左侧进入：

```text
文件
```

建议上传到：

```text
/www/wwwroot/bili-web
```

如果终端提示：

```text
cd: /www/wwwroot/bili-web: No such file or directory
```

说明项目还没有上传到这个位置，或者目录名字不一致。先执行：

```bash
ls -la /www/wwwroot
```

看里面到底有没有 `bili-web`。如果没有，就回到宝塔文件管理器上传整个 `bili-web` 文件夹。

上传后目录应类似：

```text
/www/wwwroot/bili-web
├── backend
├── frontend
├── docker-compose.baota.yml
├── .env.example
└── README.md
```

## 第 3 步：创建 .env

如果你上传的是我给你的完整 `bili-web` 文件夹，根目录里已经带了 `.env`，这一步可以跳过。

如果你的服务器目录里没有 `.env`，宝塔面板进入：

```text
终端
```

执行：

```bash
cd /www/wwwroot/bili-web
cp .env.example .env
```

如果你只是学习测试，可以先不用改 `.env`。

## 第 4 步：启动 Docker 服务

在宝塔终端执行：

```bash
cd /www/wwwroot/bili-web
docker compose -f docker-compose.baota.yml up -d --build
```

查看是否启动成功：

```bash
docker compose -f docker-compose.baota.yml ps
```

再测试后端是否可访问：

```bash
curl http://127.0.0.1:8000/api/health
```

正常会返回：

```json
{"status":"ok"}
```

如果这里不正常，先不要配置域名，先查看日志：

```bash
docker compose -f docker-compose.baota.yml logs -f
```

## 第 5 步：宝塔添加网站

宝塔面板左侧进入：

```text
网站
```

点击：

```text
添加站点
```

填写：

```text
域名：bld.atm6.cn
根目录：/www/wwwroot/bld.atm6.cn
PHP版本：纯静态
数据库：不创建
```

提交后，访问 `http://bld.atm6.cn` 如果看到宝塔默认 404，这是正常的，因为还没配置反向代理。

## 第 6 步：配置反向代理

在宝塔：

```text
网站 -> 找到 bld.atm6.cn -> 设置 -> 反向代理 -> 添加反向代理
```

填写：

```text
代理名称：bili-web
目标 URL：http://127.0.0.1:8000
发送域名：$host
```

开启后保存。

为了让大文件下载更快，建议再添加一条静态目录规则，让 Nginx 直接发送下载文件：

```text
网站 -> bld.atm6.cn -> 设置 -> 配置文件
```

在 `server { ... }` 里面加入：

```nginx
location /downloads/ {
    alias /www/wwwroot/bili-web/downloads/;
    add_header Content-Disposition "attachment";
    sendfile on;
    tcp_nopush on;
}
```

然后保存，并在宝塔里重载 Nginx。

现在访问：

```text
http://bld.atm6.cn
```

应该能看到 Bili Web 页面。

## 第 7 步：申请 HTTPS

宝塔：

```text
网站 -> bld.atm6.cn -> 设置 -> SSL -> Let's Encrypt
```

选择：

```text
文件验证
```

勾选 `bld.atm6.cn`，点击申请。成功后开启：

```text
强制 HTTPS
```

最终访问：

```text
https://bld.atm6.cn
```

如果申请证书时报：

```text
curl: (7) Failed to connect to 2606:4700:... Network is unreachable
```

通常说明域名解析到了 Cloudflare 的 IPv6，但服务器当前不能访问 IPv6。处理方法：

1. 到域名 DNS 管理后台或 Cloudflare，把 `bld.atm6.cn` 的代理状态临时改成 `DNS only`，也就是灰色云朵。
2. 删除 `bld.atm6.cn` 的 `AAAA` 记录，只保留指向服务器公网 IPv4 的 `A` 记录。
3. 等待几分钟 DNS 生效。
4. 在服务器执行：

```bash
curl -I http://bld.atm6.cn
```

如果不再连接 `2606:4700:...`，再回宝塔申请 Let's Encrypt。

证书申请成功后，可以继续保持 `DNS only`。如果你以后再打开 Cloudflare 代理，建议改用 Cloudflare 的 SSL 证书或 DNS 验证方式。

如果你确认 DNS 面板里只有 `A` 记录，但宝塔仍然连接 `2606:4700:...`，继续排查：

```bash
getent ahosts bld.atm6.cn
curl -4 -I http://bld.atm6.cn
curl -6 -I http://bld.atm6.cn
```

判断方法：

- `getent ahosts` 如果还能看到 `2606:4700:...`，说明 DNS 仍在返回 IPv6，继续检查 `AAAA`、`*` 泛解析、CDN/代理或等待 DNS 缓存过期。
- `curl -4 -I http://bld.atm6.cn` 能访问，说明 IPv4 网站正常。
- `curl -6 -I http://bld.atm6.cn` 失败是正常的，因为服务器没有可用 IPv6。

临时解决办法：在宝塔 SSL 页面选择 `DNS验证`，按宝塔提示去域名解析后台添加一条 TXT 记录。DNS 验证不依赖服务器从 IPv6 访问你的域名，通常能绕过这个问题。

## 常见 404 原因

### 1. 宝塔网站没有配置反向代理

表现：

```text
访问域名显示宝塔 404
```

处理：

```text
网站 -> bld.atm6.cn -> 设置 -> 反向代理
```

目标 URL 必须是：

```text
http://127.0.0.1:8000
```

### 2. Docker 后端没有启动

测试：

```bash
curl http://127.0.0.1:8000/api/health
```

如果连不上，查看日志：

```bash
cd /www/wwwroot/bili-web
docker compose -f docker-compose.baota.yml logs -f
```

### 3. 用错了 compose 文件

宝塔服务器建议用：

```bash
docker compose -f docker-compose.baota.yml up -d --build
```

不要优先用默认 `docker-compose.yml`，因为它会启动自己的 Nginx 容器并尝试占用 80 端口，容易和宝塔 Nginx 冲突。

### 4. 域名没有解析到当前服务器

测试：

```bash
ping bld.atm6.cn
```

看到的 IP 应该是你的服务器公网 IP。

## 解析提示未登录

如果网页解析视频时提示 `未登录`，说明 B 站接口要求登录 Cookie。当前程序会自动尝试降级到普通 MP4 流；如果你需要 720P、1080P、DASH 视频音频分离流或会员内容，推荐在网页里使用 `扫码登录`。

扫码登录成功后，Cookie 会自动填入页面里的输入框。Cookie 是一次性的：不会保存到服务器，也不会保存到浏览器。刷新或关闭页面后需要重新扫码。

获取 Cookie 的方法：

1. 电脑浏览器登录 `https://www.bilibili.com`。
2. 按 `F12` 打开开发者工具。
3. 进入 `Network` / `网络`。
4. 刷新页面。
5. 点击一个 `www.bilibili.com` 请求。
6. 在 `Headers` / `标头` 里找到 `Request Headers` 下的 `Cookie`。
7. 复制整行 Cookie，粘贴到网页的 Cookie 输入框。

常用关键字段是：

```text
SESSDATA
bili_jct
DedeUserID
```

直接复制完整 Cookie 最省事。

填写后先点击网页里的 `检查 Cookie`。如果显示 `已登录`，再去解析视频；如果仍显示 `未登录`，通常是 Cookie 没复制完整、复制到了响应 Cookie 而不是请求 Cookie，或者 B 站登录状态已经过期。

### 扫码登录

网页里点击：

```text
扫码登录
```

然后用手机 B 站 App 扫码确认。成功后页面会自动填入 Cookie，并显示：

```text
扫码登录成功，Cookie 已填入
```

不建议做账号密码登录，因为账号密码登录通常涉及验证码、短信验证、风控和密码安全问题。

如果你想让服务器默认使用某个 Cookie，也可以写到 `.env`：

```bash
cd /www/wwwroot/bili-web
nano .env
```

添加或修改：

```text
BILI_COOKIE=SESSDATA=你的值; bili_jct=你的值; DedeUserID=你的值
```

保存后重启：

```bash
docker compose -f docker-compose.baota.yml up -d --build
```

## 下载很慢或看到 m4s

B 站高清通常是 DASH 流，原始文件会是：

```text
video.m4s
audio.m4a
```

程序下载完成后会用 ffmpeg 合并成 mp4。你最终保存的文件应是 `.mp4`。

下载慢通常不是宝塔问题，而是服务器到 B 站 CDN 的线路慢。美国服务器拉国内 B 站资源经常比较慢。可以尝试：

- 换国内或亚洲线路服务器。
- 选择低一点的清晰度，例如 720P 或 1080P。
- 避开晚高峰。
- 后续增加多线程分片下载。

如果是“下载完成后，从网站保存到自己电脑很慢”，优先检查宝塔 Nginx 是否已经加了这个静态下载规则：

```nginx
location /downloads/ {
    alias /www/wwwroot/bili-web/downloads/;
    add_header Content-Disposition "attachment";
    sendfile on;
    tcp_nopush on;
}
```

没有这条规则时，文件会通过 Python 后端发送，传大文件会更慢。

## 更新项目

上传新文件后执行：

```bash
cd /www/wwwroot/bili-web
docker compose -f docker-compose.baota.yml up -d --build
```

## 停止服务

```bash
cd /www/wwwroot/bili-web
docker compose -f docker-compose.baota.yml down
```
