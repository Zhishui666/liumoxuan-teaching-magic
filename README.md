# 一备多用适配器

> 一个输入，多场景版本输出。围绕“备一次，用在十个地方”的减负增效工具项目。

## 项目主题

教师常常把同一份核心教学内容反复改写成不同版本：三种层次的课堂讲法、学生自学版、家长能听懂的说明、请假补学版、复习清单版。这个项目要把这件事产品化：输入一份真实核心教学内容，输出多份可直接使用的场景版本。

当前项目原型来自截图任务：

- 赛道：赛道二 · 减负增效
- 组别：第 17 组
- 题目：备一次，用在十个地方
- 核心产物：一备多用适配器

语音输入接入已规划为 v1 增强方案，当前不阻塞 Markdown + Prompt 的第一阶段闭环；云端 ASR 选型已切换为火山引擎豆包流式语音识别。

## 第一阶段目标

1. 建立“核心内容输入”的结构标准。
2. 建立“版本输出”的场景矩阵。
3. 设计一份可复用的 Prompt 合约。
4. 用真实语文教学内容跑通 3 个以上版本输出。
5. 沉淀为后续可开发成工具的项目骨架。

## 目录结构

```text
.
├── .env.example
├── README.md
├── README-设计哲学.md
├── assets/
│   └── reference/
├── docs/
│   ├── 00-项目简报.md
│   ├── 01-MVP需求.md
│   ├── 02-版本适配矩阵.md
│   └── 03-火山引擎豆包语音识别接入方案.md
├── examples/
│   ├── input/
│   └── output/
├── prompts/
│   └── 一备多用适配器-v0.md
├── scripts/
│   ├── check_volcengine_asr_config.py
│   └── volcengine_streaming_asr_mvp.py
└── src/
    └── README.md
```

## 当前状态

本仓库已完成项目立项骨架。下一步优先做一份真实核心教学内容样例，验证“一份输入 -> 多份版本输出”的质量稳定性。
语音输入方向可按 `docs/03-火山引擎豆包语音识别接入方案.md` 另行验证。

## 语音识别 MVP

准备环境：

```bash
python3 -m pip install -r requirements.txt
```

还需要本机可用 `ffmpeg`。macOS 可用：

```bash
brew install ffmpeg
```

复制配置模板并填入火山引擎 API Key：

```bash
cp .env.example .env
```

检查配置：

```bash
python3 scripts/check_volcengine_asr_config.py
```

生成一段本地中文测试音频并调用火山引擎豆包流式 ASR：

```bash
python3 scripts/volcengine_streaming_asr_mvp.py --make-sample
```

转写自己的音频：

```bash
python3 scripts/volcengine_streaming_asr_mvp.py --audio path/to/audio.wav
```

输出会保存到 `outputs/asr/`。
