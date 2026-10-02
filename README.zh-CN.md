# ExamScribe

[English](README.md) | **简体中文**

一个 Agent Skill（智能体技能），把教科书变成学生可以信赖的备考材料：

- **为主动回忆设计的学习笔记**：先做课前小测，再逐一学习每个关键术语、公式、例题和图表，每项都附有课本原文定义、通俗解释和常见错误；答案先模糊显示，学生自己尝试之后才揭晓
- **自测题**（单选、判断、数值、填空、简答），答案由独立的一轮"盲解"重新解出核对
- **Anki 记忆卡**、康奈尔式**复习表**、每周的**交错练习**、限时**模拟考试**、**速查表**、**易错点**页面，开卷考试还有**查找索引**
- **学习日历**（.ics），从考试日期倒推安排间隔复习
- **核实报告**，明确列出需要人工复核的每一处

输入：PDF（有文字层的或扫描版，任何语言）、EPUB、Markdown、纯文本，或书页照片。有文字层的 PDF 几秒内直接读取；扫描件和照片用 OCR 识别，而且只识别考试范围内的页面。

准确性第一。每条陈述都引用课本原文并注明页码。脚本逐一核对每条引文、每个数字和每个计算；另有一轮独立的核对确认每条陈述，并用故意植入的错误陈述（"金丝雀"）检验核对者是否认真。未经核实的内容绝不会被当作已核实的内容呈现。

它也专为**能力较弱的模型**设计。由脚本驱动的状态机每次只派发一个小任务；骨架预先填好结构和证据提示；严格的检查器（linter）会解释每一个问题；尝试次数有上限；模型分级（tier）在任务大小与安全性之间取舍。详见 [`exam-scribe/references/model-tiers.md`](exam-scribe/references/model-tiers.md)（英文）。

## 仓库结构

```
exam-scribe/                 技能本体（安装或打包的就是这个文件夹）
  SKILL.md                   模型阅读的指令
  scripts/examscribe.py      命令行工具：init、next、check、status、config、plan、build ……
  scripts/examscribe_lib/    提取、清单、笔记格式、检查器、计算器、核实、金丝雀、流水线、
                             渲染、记忆卡、学习计划、报告
  references/                按需加载的指南、学科配置、完整示例
  assets/                    学习页面的 CSS 和 JavaScript
  evals/                     skill-creator 评测提示和示例教材（不打包）
tests/                       144 个单元测试和集成测试（python -m unittest discover -s tests），包括由
                             tests/fixtures/lang_books.py 生成的 9 种语言的文字版和扫描版 PDF，以及来自真实
                             书籍的回归测试（test_realworld.py）
tools/                       开发工具：示例工作区、变异测试、指标统计、文档生成、Python 兼容性检查
trials/                      真实书籍评测脚本和小模型试运行说明（书籍本身和试运行工作区不在仓库中，
                             见 trials/corpus/README.md）
docs/EVALUATION.md           如何衡量质量：从单元测试到真实教科书（中文版：docs/EVALUATION.zh-CN.md）
```

## 运行环境

Python 3.9+，需要 `pymupdf`、`markdown-it-py`、`mdit-py-plugins`，`genanki` 可选：

```
python -m pip install -r exam-scribe/requirements.txt
python exam-scribe/scripts/examscribe.py doctor
```

如果无法安装 PyMuPDF，文字版 PDF 仍可用 `pdfplumber` 或 `pypdf` 读取（较慢，没有图片，不支持 OCR）。扫描版书籍需要 OCR 引擎：Windows 10/11 使用系统自带的引擎（无需安装）；在任何电脑上，`python exam-scribe/scripts/examscribe.py ocr-setup --language xx` 都会下载 Tesseract 语言数据（1-5 MB；引擎已包含在 PyMuPDF 中）；识别中文时 `rapidocr_onnxruntime` 最准确。Microsoft Edge 或 Google Chrome 可选（用于导出 PDF）。

## 速度

有文字层的 PDF（任何语言）直接读取，从不做 OCR。以下数据在 2 核虚拟机上测得（普通笔记本电脑更快）：

| 书籍 | 步骤 | 用时 |
|---|---|---|
| 200 页中文 / 俄文文字版 PDF | 提取 + 清单 | 2.5 秒 / 1.8 秒（不用 PyMuPDF 约 11 秒） |
| 640 页文字版 PDF | `probe` / 提取 / 清单 | 1 秒 / 3.8 秒 / 1.1 秒 |
| 640 页文字版 PDF | `extract` 导出为 Markdown | 4.5 秒 |
| 640 页文字版 PDF | 一章的图片和公式截图 | 0.4 秒（只为要学习的章节生成图片） |
| 120 页扫描件（300 dpi） | Windows 引擎 OCR，2 个进程 | 27 秒（每秒 4.4 页），字符正确率 99.7% |
| 640 页扫描件，考试范围 2 章 | 只识别这 32 页 | 6 秒 |
| 361 页 1914 年扫描件（Internet Archive） | 识别 32 页，Windows 引擎 | 39 秒（每页 1.2 秒） |
| 5 页法 / 德 / 俄 / 西班牙文扫描件 | Tesseract OCR（数据来自 `ocr-setup`） | 4-6 秒 |
| 292 页中文扫描件，考试范围为第 1 章 | 用 RapidOCR 识别其中 16 页 | 在这台虚拟机上 5-10 分钟（笔记本电脑上每页 2-5 秒） |

OCR 只用于扫描件和损坏的文字层；它会等考试信息问答（intake）结束后才开始，只识别考试范围内的页面；结果按页缓存，中断后可以接着识别。模型从不自己读取 PDF。详见 `exam-scribe/references/ingest.md`（英文）。

## 语言

已用中文、日文、韩文、俄文、德文、法文和西班牙文的文字版 PDF 以及同一批书的扫描版测试：能找到章、节、章末部分、图、公式、例题、习题和关键术语，引文也能通过核对。德文、中文、法文和韩文的笔记都能通过检查器；核对者的注意力测试（植入的错误陈述）用笔记的语言生成：12 种语言的否定、反义和量词变换，任何语言都适用的数字和术语替换，再加上"无关段落"兜底。文字层损坏的阿拉伯文和印地文 PDF 会被识别出来并改用 OCR（Tesseract）。`init` 会检测书籍的语言。结构词表在 `exam-scribe/scripts/examscribe_lib/lang.py` 中。学生在笔记之外看到的一切（页面标签、按钮、说明、记忆卡、学习计划和日历、Obsidian 笔记以及核实报告页面）在中文、日文、韩文、德文、法文、西班牙文和俄文笔记下都使用笔记的语言（`exam-scribe/scripts/examscribe_lib/ui.py`；其他语言使用英文标签）。给智能体看的命令输出保持英文。

## 在真实书籍上的测试

除了生成的测试用书，提取功能还在真实书籍上检验过：五本从网上下载的书（开放许可或公有领域；来源见 [`trials/corpus/README.md`](trials/corpus/README.md)），以及一位用户提供的扫描版教科书。每本书都暴露了一些问题，现已修复，并有回归测试覆盖（`tests/test_realworld.py`、`tests/test_scanned_languages.py`）：

| 书籍 | 类型 | 暴露的问题 |
|---|---|---|
| OpenStax《Química 2e》（西班牙文，1,223 页） | 文字版 PDF，有书签 | 自动生成的"引言"重复；西班牙文的答案和目录标题 |
| 《动手学深度学习》（中文，797 页） | 文字版 PDF，含数学 | 数学页被误判为乱码；"即使"被当成定义 |
| 日本文部科学省《情報I》教师用教材（日文） | 文字版 PDF | 正文使用粗体字体；从句和动词被当成关键术语；"図表"图注 |
| bpb《Demokratie》小册子（德文） | 文字版 PDF，双栏 | 软连字符；"19. Jahrhundert" 把句子拆开；前置内容被当成学习章节 |
| 《Elementary Household Chemistry》（1914 年，英文） | 扫描件，没有页码标签 | OCR 误读罗马数字章号；标题为普通大写字母；页边的书眉 |
| 一本中文传播学教科书（292 页，由用户提供） | 扫描件，书签无用 | 只识别了第 1 章的页面时，第 1 章一直延续到全书末尾；"第二章"被误读为"第一章"；OCR 用时估计严重偏低 |

## 安装技能

- **Claude Code：** 把 `exam-scribe/` 复制到 `~/.claude/skills/exam-scribe/`（所有项目可用）或 `<项目>/.claude/skills/exam-scribe/`（单个项目）。
- **Claude 应用：** 上传打包好的 `exam-scribe.skill` 文件（即 `exam-scribe/` 文件夹的 zip 压缩包）。
- **其他支持 Agent Skills 的智能体**（技能是一个包含 `SKILL.md` 的文件夹）：把文件夹放到该智能体加载技能的位置。任何能运行 Python 的智能体也可以直接按照 `SKILL.md` 操作。

然后这样提问即可：*"这是我的化学课本，12 月 15 日考试，帮我做第 2 到第 4 章的学习笔记。"*

## 工作原理

```
init（快速检查文件）-> ingest（提取）-> inventory（清单）-> intake（考试信息：日期、题型、范围）
  -> 对考试范围内的扫描页做 OCR（如有）-> plan（附理由的优先级）
  每一章：
     编写每一节（骨架为每个清单条目留一个块；带引文的陈述、计算行、题目）
  -> 编写章级内容（概览、必须掌握的要点并与课本小结对照、概念图、对比）
  -> 核实陈述（全新上下文的核对者 + 金丝雀）-> 核实公式 -> 盲解 -> 对账（reconcile）
  -> 修正被驳回的内容（轮数有限）-> 生成并分享本章
完成 -> 课程首页、练习题组、模拟考试、速查表、记忆卡组、日历、核实报告
```

模型只运行 `next`（打印一张任务卡）和 `check`（通过则显示下一张任务卡，不通过则列出要改的地方）。所有状态都保存在工作区文件夹中，因此任何会话、任何模型都可以接着做。

## 没有教科书也能试用

```
python tools/dev_setup.py ./demo-ws        # 生成示例教材，完成考试信息问答，打印第一个任务
```

## 局限

- 提取质量决定一切。OCR 识别文字很准，但在数字、符号和公式上容易出错，所以 OCR 页面上带数字的陈述一律标记为待核对；公式很多的书最好先用支持数学公式的工具转换（见 `exam-scribe/references/ingest.md`）。可疑页面会被标记，而不会被直接信任。
- OCR 引擎只在 Windows 上测试过（英文用 Windows OCR；法、德、俄、西班牙、中、印地和阿拉伯文用 Tesseract；中文用 RapidOCR）。在 macOS 和 Linux 上只有 Tesseract 和 RapidOCR 可用，代码相同，但还没有在这两个系统上运行过。Tesseract 有时会漏掉特大号的标题字，这时用章节标签（如"Глава 1"）代替标题，由用户确认章节列表。从右向左书写的文字（阿拉伯文、希伯来文）提取的可靠性低于其他文字。
- 核对者也是模型。金丝雀能衡量它是否认真，但模型有可能识破金丝雀，却仍漏掉真实的错误：由 Claude Haiku 同时担任编写者和核对者时，人工抽查的 20 条已核实陈述中有 2 条带有课本没有的小补充（多加的限定、扩大的范围）。条件允许时，请用较强的模型执行核对任务。
- 小模型的上下文大约在五张任务卡后就会用满；它会在某张任务卡通过后停下，由新会话用 `next` 继续（一个 16 页的章节用了六个 Haiku 会话）。
- 核实很彻底，所以在 strict 级别下处理整本教科书意味着大量小任务。请把 `scope.chapters` 限定在考试范围内。

## 文档语言

本说明和评估指南提供中英文两个版本（`README.md` / `README.zh-CN.md`，`docs/EVALUATION.md` / `docs/EVALUATION.zh-CN.md`）。`exam-scribe/` 中给模型阅读的 `SKILL.md` 和 `references/` 保持英文：模型执行英文指令最可靠，而笔记和学习页面本来就会使用学生的语言。

## 许可证

MIT，见 [LICENSE](LICENSE)。
