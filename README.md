# video-lecture-html (`vlh`)

把**中文技术演讲 mp4**转成**可搜索的静态 HTML 学习资料**。

> 产品语义说明  
> - **「逐帧」** = hybrid 关键帧 / 幻灯片换页去重（粗召回 + 局部差异精修），**不是** 25fps 真逐帧导出。  
> - **「翻译」** = 中文语音**转写** + 结构化 HTML；默认**不做**中→英机器翻译。

适合本地私有课程目录（例如 UWA / 极客时间本地归档），生成可离线打开的学习站：目录索引、幻灯片图、带时间戳的转写段落，并可链接回原视频。

## 功能

| 模块 | 说明 |
|------|------|
| ASR | 优先 [FunASR](https://github.com/modelscope/FunASR)（Paraformer-zh / SenseVoice，带时间戳）；失败可回退 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) |
| 抽帧 | `ffmpeg` + hybrid-keyframe（采样/I 帧粗召回 + OpenCV 帧差 / 简化 SSIM） |
| OCR | 可选 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)（`--ocr on`，默认 off） |
| 输出 | Jinja2 静态站：`index.html` + `talks/<slug>/page.html` + `meta.json` |
| 批处理 | 可跳过同文件大小重复；从 `【UWA 2024】标题` 类文件名解析分类做索引分组 |
| 内容分析 | 规则引擎：从已有转写+关键帧生成概览/大纲/分章精读/要点；`vlh enrich` 可无重跑 ASR |

**本仓库不包含模型权重**，也不上传你的视频。

## 针对本机视频目录（作者环境）

```text
D:\Notes\GeekTimeLearning\_learning\uwa_learning
```

该目录体量大（数十个 mp4、数 GB），**不要**提交进 Git。只在本机跑 `vlh batch`，输出到例如：

```text
D:\Notes\GeekTimeLearning\_learning\uwa_learning_html
```

## 环境要求

- Python **3.10+**
- [ffmpeg](https://ffmpeg.org/) 在 `PATH` 中（Windows 可用 `winget install ffmpeg`）
- 可选 NVIDIA GPU + CUDA（FunASR / faster-whisper 会快很多；作者机器曾用 RTX 5080）

## 安装

```bash
git clone https://github.com/MJX1010/video-lecture-html.git
cd video-lecture-html
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install -U pip
pip install -e .

# 推荐中文 ASR（按需）
pip install funasr modelscope torch

# 或英文/通用回退
# pip install faster-whisper

# 可选 OCR
# pip install paddlepaddle paddleocr
```

验证 CLI：

```bash
vlh --help
python -m vlh --help
```

## 用法

### 单文件

```bash
vlh process path\to\talk.mp4 -o path\to\out ^
  --asr funasr --ocr off --lang zh --video-mode link
```

### 批处理目录

```bash
vlh batch "D:\Notes\GeekTimeLearning\_learning\uwa_learning" ^
  -o "D:\Notes\GeekTimeLearning\_learning\uwa_learning_html" ^
  --asr funasr --ocr off --lang zh --video-mode link --site-title "UWA Learning"
```

### 先冒烟（无模型 / 无 GPU）

只搭页面结构，或只抽帧：

```bash
vlh process talk.mp4 -o out --dry-run
vlh process talk.mp4 -o out --slides-only --ocr off
vlh batch uwa_learning -o out --dry-run --limit 3
```

`--video-mode`：

- `link`（默认）：HTML 用相对/绝对路径引用原 mp4，**不复制**视频  
- `copy`：把视频拷进 `talks/<slug>/`（占空间，一般不推荐）  
- `none`：页面不挂视频播放器  

## 输出结构

```text
out/
  index.html
  assets/styles.css
  talks/
    <slug>/
      page.html
      meta.json
      slides/slide_0000.jpg ...
```

浏览器打开 `index.html` 即可搜索标题/分类/转写摘要；讲次页可按时间轴跳转（在 `link`/`copy` 模式下）。

## 设计取舍

1. **不做真逐帧**：节省磁盘与时间；换页检测对「幻灯片演讲」足够。  
2. **默认不做英译**：输入已是中文技术内容；转写即可检索与复习。  
3. **模型外置**：避免仓库膨胀与许可证纠纷；首次跑 FunASR 会按官方流程拉权重。  
4. **密钥/视频永不入库**：`.gitignore` 已忽略 `*.mp4` 与常见缓存目录。

## 致谢 / 相关项目

- [FunASR](https://github.com/modelscope/FunASR)  
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)  
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)  
- 开源社区中各类 lecture-to-notes / 课件抽帧思路（本工具为独立实现，MIT）

详见根目录 `NOTICE`。

## License

MIT — 见 `LICENSE`。


### AI Agent 精读重写（推荐）

在已有 `meta.json` 转写基础上，用 LLM map-reduce 生成可读精读笔记：

```bash
# 默认自动探测 DeepSeek / Ollama 等（密钥走环境变量，不入库）
set VLH_LLM_API_KEY=...          # 或 DEEPSEEK_API_KEY
set VLH_LLM_BASE_URL=https://api.deepseek.com
set VLH_LLM_MODEL=deepseek-chat

vlh ai-enrich path/to/uwa_html_site --concurrency 4
# 试点某一讲：
vlh ai-enrich path/to/uwa_html_site --only 2ce902f5 -j 4
```

章节结果缓存于 `talks/<slug>/ai_analysis.json`，可随时续跑。失败时默认回退规则分析。

