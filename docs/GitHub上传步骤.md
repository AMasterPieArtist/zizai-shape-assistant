# 上传 GitHub 与简历链接

本次交付是已整理的源码包和截图，尚未代为创建仓库或上传。可以今天先上传源码并在简历放仓库链接，不必等待在线应用部署。

## 1. 解压项目包

解压后进入 `zizai-shape-assistant` 文件夹。应直接看到 `README.md`、`app.py`、`web`、`zizai`、`docs`、`tests`、`data` 和 `.env.example` 等。

**上传这个文件夹里面的内容，而不是只上传 ZIP，也不要再套一层文件夹。** README 和 app.py 应出现在仓库根目录，截图放在 `docs/screenshots/portfolio/`。这是已排除个人数据的副本；不要从日常运行目录额外复制 `.env` 或 SQLite 进来。

## 2. 创建仓库

1. 登录 GitHub，右上角 **+ → New repository**。
2. 仓库名可用 `zizai-shape-assistant`；描述可填“自在身材｜AI 日常饮食与运动陪伴助手，产品经理实践项目”。
3. 如用于公开简历展示，选择 **Public**。
4. 不勾选初始化 README；本包已包含。许可证按你自己的发布意愿选择，本次没有替你添加。
5. 点击 **Create repository**。

## 3. 上传源码

空仓库页面点击 **uploading an existing file**；已有仓库使用 **Add file → Upload files**。从解压后的项目目录将里面的文件和文件夹拖进上传区，确认包含 README、docs 中的图片、data/reference 数据以及 `.gitignore`。填写提交说明，如 `Add Zizai Shape AI MVP and product portfolio`，点击 **Commit changes**。

GitHub 网页上传每批最多 100 个文件、单文件最大 25 MiB；若超过上限，分批上传并保留目录结构，或使用 GitHub Desktop。本次包的数量与大小见发布检查报告。[GitHub 官方上传说明](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)

## 4. 上传后检查

- 仓库首页自动展示 README，三张主要截图均显示。
- 点击“全部界面截图”、PRD、运行说明能正常打开或下载。
- 仓库根目录有 `app.py` 与 `README.md`，而不是只有一个 ZIP。
- 没有真实 `.env`、`.sqlite3`、数据库备份或个人导出。
- 用未登录的浏览器打开仓库链接，确认面试官可以查看。

README 使用相对图片路径，只要源码和截图一起按目录上传即可。[GitHub README 官方说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)

## 5. 放进简历

复制你的实际仓库地址，格式为 `https://github.com/你的用户名/你的仓库名`。

链接标签建议：**项目作品与源码（含界面截图、PRD）**。此时它是项目介绍与源码入口，不是在线使用地址。后续公开部署完成，再添加独立的“在线体验”链接。

别人看截图不需要运行程序；想完整本地体验，需要下载源码、安装 Python 并启动服务。`127.0.0.1` 地址不能作为面试官的远程体验链接。[分享与上线说明](分享试用与简历展示说明.md)
