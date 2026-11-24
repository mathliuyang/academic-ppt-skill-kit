# 同步讲稿数据与核验

`report.json` 是 PPT 备注、Word 逐字稿和纯讲稿 PDF 的共同正文源。任何口述修改先修改此文件，再重新生成全部对应输出。屏幕文案、口述正文和操作提示分别保存，避免把提示混入朗读稿。仅调整可见版式且口述、页序及讲稿显示信息不变时，不重新生成讲稿；按 `qa.md` 复核修改页面和受影响输出。

PPT每页备注只保存本页 `paragraphs` 的完整口述，按原段落顺序直接呈现。不要附加页标题、计划用时、提示、图源、书目、URL、文件路径、JSON、内部检查，或“【口述正文】／【提示】／【资料来源】”等标签；也不把它们挪到同页的额外备注文本框。上述信息分别保留在 `duration_seconds`、`cues`、`sources`、`metadata` 和工作记录。Word与大字稿沿用各自已选格式，不因清理PPT备注而重建未变正文。

新稿的逐页 ImageGen 设计来源、版本与区域映射另存 `design-record.json`，见 `preview-data.md`。仅修订讲稿沿用原设计。现有 `schema_version: 1` 与讲稿CLI不变，不从生图/OCR覆盖文案或数据。

## 规范数据

文件采用 UTF-8 JSON。必需字段如下；`presenter` 和 `institution` 未知时可省略或留空，讲稿不显示缺失的身份信息。时长为秒，允许有限小数，必须大于零。`reserved_seconds` 默认 10，可以为零；逐页用时已经包含本页视频播放，只在报告层加一次预留时间。时间检查针对计划用时，实际用时仍需演练。

```json
{
  "schema_version": 1,
  "report_title": "论文中文汇报标题",
  "presenter": "示例汇报人",
  "institution": "示例单位",
  "audience": "本专业研究生",
  "scenario": "组会文献分享",
  "target_seconds": 300,
  "reserved_seconds": 10,
  "brand_profile_id": "example-brand",
  "brand_asset_revision": 2,
  "metadata": {"paper_title": "Original paper title", "doi": "填写已核验 DOI"},
  "slides": [
    {
      "slide": 1,
      "title": "研究问题",
      "screen_text": ["关键科学问题", "实验思路"],
      "duration_seconds": 35,
      "paragraphs": ["大家好，今天分享这项研究。下面先介绍它要解决的问题。"],
      "cues": ["停顿后指向示意图"],
      "emphasis": ["解决的问题"],
      "sources": [
        {"type": "paper", "path": "paper.pdf", "page": 2, "figure": "Fig. 1", "crop": [40, 80, 520, 400], "coordinate_system": "PDF points from top-left"}
      ]
    }
  ]
}
```

- `slides` 非空，`slide` 必须按数组顺序为整数 1 至 N。`title` 非空，`screen_text` 为字符串数组，可为空；`paragraphs` 是非空字符串数组，逐段保存实际口述，不存时间标签或指图提示。
- `cues`、`emphasis` 可省略，默认为空数组。每个强调词必须真实出现在本页口述中；生成器加粗所有命中，不改变文字。重叠词合并处理。
- 每页 `sources` 必须有记录，可为非空字符串或对象。对象至少包含非空 `path`、`file`、`url`、`doi`、`source`、`description`、`title` 中的一个。科学证据图按工作流记录页码、图号、裁剪框及坐标系统；封面等非科学内容可明确记录品牌档案或作者自拟来源。`page` 为从 1 开始的整数，`crop` 为非负 `[x0,y0,x1,y1]` 且面积大于零。核验器只检查记录的存在及形状，不能证明来源真实或结论正确。

- `sources` 是内部溯源数据，不写入PPT备注，也不默认转成每页可见全文书目或口述来源提醒；metadata的未核实状态留在工作数据，从观众文案省略。
- 采用当次已选字体时可在顶层记录 `font_policy: {"families": ["Noto Sans SC Medium", "Noto Sans SC Black"]}`。families须为非空字体名数组，只填写实际采用且可用的字体；未记录时保留旧版Microsoft YaHei核验。
- `metadata` 为可选对象；新论文报告应在其中保存作者中文姓名映射、期刊指标和联网补充材料检索记录，分别可用 `authors`、`journal_metrics`、`supplement_search`。每项记录来源 URL、核验日期和核实状态；期刊指标记录体系、数值、数据/版本年份及学科。它们不改变 `schema_version: 1`，具体要求见 `web-enrichment.md`。`brand_profile_id` 是可选的非空字符串，只在身份已确定时填写。
- `brand_asset_revision` 为可选正整数，用于关联本次已授权且实际使用的素材版本。

## 口述顺序与自然承接

- 与指定参考报告统一文稿风格时，先读取其实际Word样式，再统一正文、标题、行距及提示样式；大字纯讲稿PDF仍服从可读性用途。术语首次出现时按听众需要解释含义和单位，后文使用一致简称。
- 逐字稿保存实际要说的话，每句都能直接朗读。页标题、用时、动作指令和非朗读提示放正文之外，不让汇报人临场删除或改写句子。
- 页面图文顺序用于内部编排，正文用研究对象、观察和因果关系来承接。不要把顺序逐条念成“先看这一页”“再看上一页”“下一页”；连续看图和翻页口令会打断自然讲述。
- 保留PPT的核心术语、样品、数值和必要条件作为内容锚点，可自然说明“这两条曲线”“图中的红色星号”所代表的对象。口语化需要短而完整的句子，不靠密集指向、填充语气词或口头禅。
- 逐对检查相邻PPT页，确保每个边界都有简短、自然、恰当、可直接照读的口述承接。让前页的具体对象、结果或条件延续到后页的问题、比较或验证内容。衔接可融进原有内容句，不要求每个边界另起一条独立过渡句；实际口述保存在 `paragraphs`，同步到PPT备注、Word和PDF，不能只放在提示里或留给汇报人临场补充。
- 过渡可放在前页末尾或后页开头，优先修补真正断裂的位置。避免前页概括一次、后页开头又复述同一判断；也避免用“密切相关”“提供支撑”等泛泛关系替代具体内容的延续。采用当篇论文的对象和事实，直接说明哪项结果引出哪项问题，或哪些测试条件发生变化；不机械给每页加同一句“接下来”，不叙述页码或看图操作。
- 完稿后把前页结尾与后页开头连起来试读，逐个确认衔接句已经写全、读得顺且不重复；不能只凭章节顺序合理或检查连接词出现，就认定讲稿连贯。
- “我们”可用于共同看图、理解与讨论，论文中的实验行动仍由作者承担。研究设想保持讨论语气，不能讲成已经完成的实验。
- 已认可PPT、只改讲稿时，保留全部可见页面与科学素材，仅同步口述正文、强调和备注。将文稿作为真实口述试读，检查呼吸、长句与时长；不能以导航词扫描或用时标签代替自然性判断。书目信息、英文全题、校训和页脚不必逐字朗读。

同事实写法示例：

> 作者把取出的膜清洗、用去离子水平衡以后，再测室温电导。两条电导曲线整体比较平，TP-85变化很小，BP-60在初期略有下降，随后相对稳定。电导能保持下来，还要和化学结构的变化一起看。

这里用实验对象、测量结果和结构解释衔接，句子本身就是实际口述。新报告采用自己的样品、条件和结果，保留这种承接方式，不照搬本例事实。页号和小标题可以帮助查找讲稿，但不进入口述正文。

## 生成 Word 与大字 PDF

先调用 `load_workspace_dependencies`，使用返回的 Python 路径。按照当前 Documents 和 PDF 技能，在本次首次实际制作对应格式前分别运行各自的 `mark_artifact_operation_started.mjs`。不要将旧插件版本路径复制为永久运行依赖。

```powershell
& $runtimePython "$skillRoot/scripts/build_speech_outputs.py" "$taskDir/report.json" --out-dir "$taskDir/output" --stem "逐页讲稿"
```

输出为 `逐页讲稿.docx`、`逐页讲稿.pdf`、`逐页讲稿.receipt.json`。`--no-cues` 可使 Word 不显示独立提示。可用 `--font-regular PATH --font-bold PATH` 指定成对的字体；默认查找 Windows 字体目录中的 `msyh.ttc` 和 `msyhbd.ttc`，均读取 subfont 0，并真正嵌入各自字体。找不到字体时明确失败，不替代为未说明的字体或伪加粗。

在 macOS 上必须先确认一对本机真实的中文常规和粗体字体文件可被 ReportLab 读取（TTC 仅读取第 0 个子字体），再显式传入 `--font-regular` 和 `--font-bold`；不要复制本机商业字体。Word 字体名称独立指定为该字体的实际字体家族名，例如 `--docx-font-family "可用字体家族名"`。字体未安装、字形缺失或 ReportLab 无法解析时应换用经过验证的字体并重新导出；生成后检查中文、科学符号和粗体的实际效果。默认 Word 字体仍为 Microsoft YaHei，以保持已有 Windows 工作流兼容。收据的 `docx_font_family` 字段记录所选名称，不证明该字体在查看设备已安装。

Word 使用 `SpokenText` 段落样式保存完整口述；`SlideTiming` 和 `StageCue` 分开保存用时和提示，附标题、汇报人及页序。PDF 仅输出全部口述、大字正文、左侧小号 `S1` 等 PPT 页号和底部印刷页号；不显示报告题名、页标题、时间和提示。正文默认 21 pt、1.36 倍行距；只有能完整放入两页时才尝试 20.5 或 20 pt。短稿可以一页，长稿以 21 pt 增加页数，单页长讲稿允许跨页，跨页段落在页面两侧各保留至少两行，独立的单行段落保持完整。常规英文单词、数字和科研标识尽量保留在同行，超出整行宽度的极长标识才拆分。收据记录字体、页数、SHA-256 和计划时长，不代表视觉检查通过。

## 核验成品

```powershell
& $runtimePython "$skillRoot/scripts/verify_report.py" "$taskDir/report.json" --pptx "$taskDir/output/汇报.pptx" --require-pure-speech-notes --docx "$taskDir/output/逐页讲稿.docx" --pdf "$taskDir/output/逐页讲稿.pdf" --png-dir "$taskDir/output/逐页PNG" --report-json "$taskDir/qa/structural-checks.json"
```

`--template` 请填写实际留存模板文件路径；上例是路径示意，不能猜测资产名称。各成品参数可单独使用；验收新建报告完整交付时必须全部传入。修改既有讲稿时按本次范围选择参数：若用户要求 PPT 完全不动，仅传本次 Word/PDF；若同步或清理PPT备注，传 `--pptx --require-pure-speech-notes`。此严格参数需要实际PPT，检查整页备注的全部非空文本，不只比对正文区；未传它的历史分区解析仅用于旧文件回读兼容，不能作为新交付的纯备注验收。既有 PPT 的母版、比例、字体和图片式页面不因讲稿修订强制更改；只有传入 `--template` 明确要求本模板风格时，才将这些属性作为硬性验收。`--brand-profile` 只在本次需要核验身份时传入。`--report-json` 仅写单独的核验收据，拒绝覆盖输入文件；不传时输出 JSON 到标准输出。退出码 0 表示所传项目的结构检查通过，1 表示失败或不可检查。

新报告完整验收时再传 `--design-record "$taskDir/design-record.json" --design-preview-dir "$taskDir/design_previews" --require-design-previews`，检查N张选定设计与N页PPT/最终PNG对应。旧报告及仅改讲稿不传这些参数保持兼容；生成真实性仍由实际工具记录核对。

检查包括：

- 数据页序、来源记录和时间预算；Word `SpokenText` 正文与 JSON 逐段逐字一致以及强调词加粗。
- PPT 按 `presentation.xml` 的关系读取真实页序，再经实际 slide→notes 关系读取备注。传 `--require-pure-speech-notes` 时，正文段数和文字须与本页 `paragraphs` 一致，且不允许任何额外非空备注文本；仅排除标准幻灯片编号占位符。工具支持换行分隔的 `a:p` 或 `a:br`，拒绝分区标签、提示、来源以及额外文本框中的杂项。不能只检查“口述正文”分区正确，就忽略同页剩余备注。
- PDF 经坐标识别仅去掉本生成器的左边栏页号及页脚，其余文字去除排版空白后必须与完整口述一致；检查 A4、20 pt 下限及存在真实粗体字体。
- 明确传入 `--template` 时检查 PPT 16:9、可编辑文本、全页图片迹象、显式或继承／主题解析的有效字体（按已记录的 `font_policy`，未记录时沿用旧默认），以及 slide→layout→master 关系、已有页型和母版背景／非文本装饰几何结构。参考模板中实际全幅背景图片或背景填充经真实关系和 SHA-256 识别，复用该背景并保留独立原生正文可以通过；新整页截图或没有原生正文的页面不能以此例外放行。允许清除示例文字、替换字体映射和增添品牌标识，不要求母版 XML 逐字节相同。此结构检查不能证明视觉完全一致。指定品牌时核对姓名、单位、校训及原始校徽、校名图像 SHA-256 是否在 PPT 包中。
- PNG 文件数与页数一致、每幅至少 1280×720；明确传入 `--template` 时再要求 16:9。此目录仅放逐页图片，联系表另存。

结构检查不能替代语义、视觉和播放检查。PPT 用当前 Presentations 流程渲染并逐页查看；Word 先用当前 Documents 的 `render_docx.py`，失败时记录日志和缺失依赖，可用已安装 Microsoft Word 的独立 COM 进程导出 PDF 作备用 QA；PDF 用可用渲染器逐页查看。新报告检查全部页面是否有溢出、缺字、遮挡、图片缺失、错误断行；局部修订按 `qa.md` 检查修改及受影响页面，未改页面的既有核验可在相同内容证据下复用。媒体实际进入放映播放验证；未验证必须在交付说明中明确指出，不能由核验脚本代为认证。

当前 Presentations 的备注 setter 直接接收纯口述段落。写入前清理旧备注中的提示、来源和额外文本对象，避免仅覆盖正文占位符后留下其他杂项；优先使用官方 setter，勿手工修改 notes 关系或凭猜测插入 OOXML。

```javascript
slide.speakerNotes.text = slideData.paragraphs;
```
