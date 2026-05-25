# browser-harness 协作

`yt-dlp` 是默认抓取路径 (~90% 场景覆盖)。剩下 10% 由 `browser-harness` 接管。

## browser-harness 是啥

直接通过 CDP (Chrome DevTools Protocol) 控制**用户正在跑的本机 Chrome** (端口 9222), 复用所有 cookies / SSO / 会员状态. Repo: https://github.com/browser-use/browser-harness

## 何时切到 browser-harness

| 场景 | 解法 |
|---|---|
| B 站 UP 主热度 top-N 列表 | DOM 排序 (`--up <UID>`) |
| yt-dlp `extract_info` 失败 (站点反爬升级) | browser-harness 打开页面, 监听 network 抓 manifest URL + headers, 喂给 ffmpeg |
| 充电专属 / 会员独占视频 yt-dlp 拒绝 | 同上 (浏览器有会员态, 实际能播 → 能抓) |
| 私有教程站 / SaaS 课程 / 自定义播放器 | 同上 |
| DRM 加密流 (Netflix, Apple TV 这种) | **没办法** — 媒体密钥在系统层, browser-harness 也拿不到, 只能录系统音频 |

## `--up` 是怎么工作的

`transcribe --up 676494894 --top 3` 实际触发的子流程:

```python
# scripts/transcribe.py 里的 fetch_up_top() 函数
browser-harness -c '
new_tab("https://space.bilibili.com/{UID}/upload/video?order=click")
wait_for_load()
time.sleep(4)
print(js("""
  const cards = document.querySelectorAll('[class*=upload-video-card]');
  const items = [];
  cards.forEach(c => {
    const a = c.querySelector("a[href*=/video/BV]");
    if (a) items.push(a.href.match(/BV[a-zA-Z0-9]+/)[0]);
  });
  return JSON.stringify(items.slice(0, N));
"""))
'
```

`order=click` 是 B 站 URL 参数, 视频列表按播放量降序; 取前 N 个 BV id 出来, 然后正常走 yt-dlp 流程。

## 兜底流程 (yt-dlp 失败时, **未来扩展**)

当前脚本: yt-dlp 失败直接报错 (`raise RuntimeError`). 未来加 `--fallback browser-harness` 选项, 实现如下:

```python
# 伪代码
result = yt_dlp_extract(url)
if result.failed:
    print("yt-dlp 失败, 切 browser-harness 兜底")
    manifest, headers, cookies = browser_harness_capture_stream(url)
    audio = ffmpeg_with_headers(manifest, headers)
    transcribe(audio)
```

`browser_harness_capture_stream` 会做:
1. `new_tab(url) + wait_for_load`
2. `cdp("Network.enable")` 开网络监听
3. 自动点击播放按钮 (或等用户手动播)
4. 收集所有匹配 m3u8 / mpd / m4s / ts URL 的 request
5. 从 cookies + headers 里抠出 Cookie / Referer / Authorization
6. 把 (manifest_url, headers_dict) 返回

## 配置

`scripts/transcribe.py` 假设:
- Chrome 已启动 + 9222 debug 端口
- `browser-harness` 在 $PATH (`pip install browser-harness` 或 clone repo + symlink)

不装 browser-harness 也能用 — 只是 `--up` 和未来兜底用不了, 主流程不受影响。

## 边界

| 工具 | 干什么 |
|---|---|
| **video-transcribe** (本 skill) | 转写流水线: 元数据 → 抓流 → ffmpeg → STT |
| **browser-harness** (外部 skill) | 浏览器自动化原语: new_tab / click / js / cdp / network 监听 |

video-transcribe 调 browser-harness, 不反过来。
