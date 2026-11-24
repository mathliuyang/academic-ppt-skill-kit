# 整页生图设计记录与结构核验

新稿和整套重设计默认采用逐页 ImageGen 设计。该流程先确定准确内容，真实调用 `image_gen.imagegen` 并审阅预览，再重建可编辑 PPT。`report.json` 继续使用原 `schema_version: 1`；预览与重建信息另存 `design-record.json`。仅在实际采用此模式时使用相应严格参数。

所选参考从[参考库](template-library.json)解析。`artifact-template.json` 保留默认参考入口，补充案例属于可选视觉依据；引用某个案例不代表沿用其研究事实、身份、页数或讲述时间。当前认可的PPT及最终渲染与原始生图分别记录，后续修订不改写历史生成记录。

## 数据约定

顶层保存 `schema_version: 1`、`producer: "image_gen.imagegen"`、`report_json_sha256` 和 `slides`。报告哈希是准确输入 JSON 文件的完整字节 SHA-256，不是重新序列化后的哈希；报告改变后，应复核设计是否仍匹配，再更新记录。`slides` 按实际 PPT 页序连续编号 1 至 N，封面、目录和结束页同样各保存一条。

以下是单页条目的示意，实际记录必须覆盖全部页面。路径示例、哈希和日期须替换为本次真实值。

```json
{
  "schema_version": 1,
  "producer": "image_gen.imagegen",
  "report_json_sha256": "完整report.json文件的SHA-256",
  "slides": [{
    "slide": 1,
    "purpose": "建立研究问题并交代汇报来源",
    "selected_preview": "design_previews/slide-01.png",
    "generation": {
      "tool": "image_gen.imagegen",
      "prompt": "保存本页实际提交的完整生图提示，包括准确文案和视觉要求",
      "reference_images": ["references/template-cover.png", "references/logo.png"],
      "artifact_file": "实际工具返回的本地文件路径",
      "generated_at_utc": "2026-10-14T08:00:00Z",
      "sha256": "选用预览文件的SHA-256"
    },
    "review": {"status": "accepted", "observations": "记录布局优点及待在重建时修正的生成文字或图形问题"},
    "reconstruction": {
      "status": "complete", "final_slide": 1,
      "regions": [
        {"id": "title", "kind": "native_text", "bbox": [0.08, 0.16, 0.8, 0.2], "canonical_source": "/slides/0/title"},
        {"id": "logo", "kind": "original_image", "bbox": [0.08, 0.05, 0.08, 0.08], "canonical_source": "品牌档案原始校徽", "asset_path": "references/logo.png", "asset_sha256": "原始图像SHA-256"}
      ],
      "comparison_observations": "记录与预览的布局对照、原始素材替换和已修复的事实偏差"
    }
  }]
}
```

- `selected_preview` 必须相对于记录文件目录；其他本地素材和工具返回文件可为绝对路径，或相对于同一目录。`artifact_file` 保留实际工具返回路径；选用预览是它的原始字节副本，不能把 PPT 渲染图填成返回文件。若路径可能被清理，应在清理前持久保存原始工具产物，并同时保留真实返回路径、复制过程及工具调用证据；审核期间 `artifact_file` 指向可核验的原始字节文件。生成后编辑了预览时，新选用版本应对应最后一次真正的 imagegen 输出。
- 选用目录仅放 N 幅选用整页图片，文件名按页序命名。现有自动校验器要求至少 1280×720 且接近 16:9（绝对误差不超过 0.015）；若用户确认其他比例，应按实际比例另行视觉和尺寸核查并如实报告该自动校验限制；草稿、联系表、最终 PPT 渲染图另存。不得用相同路径或相同图片字节代替不同页面。
- `generation` 保存实际工具名、完整提示、非空参考图路径列表、返回文件路径、ISO8601 UTC 时间（例如 `2026-10-14T08:00:00Z`）和 SHA-256。时钟输出可规范化格式，但不得改变实际时间。每次真正调用的提示及工具返回信息同时保留在任务证据中；JSON 的 `producer` 字段本身不构成生图来源证明。失败页面明确记录失败，不得填写 accepted/complete 来通过审核；全部完成后才使用严格完成核验。
- `review.status: "accepted"` 表示布局选定，`observations` 明确写实际检查发现。生图错字、数值和科学图失真可作为重建待修事项，始终以准确逐页数据和论文原图为准。中间版可保留其他状态，但完成核验会拒绝它们。
- `reconstruction.regions` 记录主要可编辑文字、表格、图表和独立图片。`kind` 仅支持 `native_text`、`native_table`、`native_chart`、`original_image`、`auxiliary_image`；框线、箭头等原生装饰可在重建说明中记录，无需为了登记而改为图片。`bbox` 是整页归一化的 `[x,y,width,height]`，区域须在页面内并有正面积；`id` 在本页唯一。
- 原生对象的 `canonical_source` 是指向本页 `report.json` 内容的 JSON Pointer。文字只能指向 `/slides/0/title`、`/slides/0/screen_text` 或 `/slides/0/screen_text/0` 等标题或屏幕文案，禁止读取生图 OCR 或口述段落充当准确屏幕文本。数组索引从 0 开始。表格和图表可指向同页真实保存的数据或来源对象；结构检查不认证图表数值是否准确。
- 两类图片都必须保存 `asset_path`、`asset_sha256` 和非空 `canonical_source`。科学图和品牌选 `original_image`，解释用生成插图选 `auxiliary_image`；前者来源由论文记录或品牌档案逐一核对。独立透明示意 PNG 的区域填 `transparent_background: true`。该布尔值只用于 `auxiliary_image`；核验器检查 PNG 格式、全透明背景像素及非零 alpha 的可见像素。`false` 或省略沿用旧记录检查。生成整页预览自身不能作为重建中的图片资产。辅助插图需从原始辅助素材文件独立放置；裁剪或重绘区域必须如实记录来源，不能冒充论文原图。
- 品牌透明原图的原生调色不会改变嵌入 PNG 字节，仍记录为 `original_image`。区域可附 `display_effect` 或原生裁剪说明，并查看实际渲染。
- `reconstruction.status` 完成为 `complete`，`final_slide` 与本页一致；`comparison_observations` 写实际渲染对照结果。每页至少一个原生文本区域。可选 `screen_text_sha256` 使用 UTF-8 的紧凑 JSON `{"title":...,"screen_text":[...]}`，`ensure_ascii=False,separators=(',', ':')`，键顺序如示例；报告文件总哈希已经必需，该字段仅便于逐页复核。

## 可选的视觉标定与修订记录

以下字段只用于补充人工和实际渲染核对，保持 `schema_version: 1` 及现有必需字段不变，不要求历史报告补填。现有核验器不会因这些字段存在就认证字体还原、公共样式或图层正确，也不会代替逐页查看。

- 顶层可保存 `reference_set_id`，对应参考库中的已选项；`common_style` 可保存该报告选定的公共组件及其适用页型、字体方案、边界与位置。涉及坐标时显式写明画布尺寸和单位，不能把案例中的像素值直接用于另一种页面尺寸。正文、总结和讨论页默认共享公共底部规范；封面、结束或备份页的另行选定页型分别标明，不把生成图偶发差异登记成新规范。
- 区域可补充 `typography`，记录 `font_family`、`font_size_px`、`font_weight`、`color`、对齐及内边距；这些是本轮选定的重建参数，不能从截图字形猜测后写成已核实字体。混合字重或颜色在实际对象运行级样式中保留，并在核对说明中记录。
- 图片区域可补充 `visible_image_bbox`，使用与 `bbox` 相同的归一化坐标，说明等比放置后实际可见图像的边界；`bbox` 仍是原组件边界。原生裁剪、显示效果和去除外部白边等操作另作显示记录，原始素材哈希不变。检查容器和可见图像的尺寸差异，避免以宽框掩盖过小原图。
- 新稿在 `reconstruction.final_png_sha256` 记录逐页最终渲染文件的完整 SHA-256，并使用 `slide-01.png` 等以页号结尾的文件名。字段对旧记录可选。提供 `--png-dir` 时，核验器按文件名结尾数字定位对应页，要求该页文件唯一并匹配小写十六进制哈希。可另存 `revision_notes`。局部修订时记录修改对象、原因、受影响页及所用核对证据；只有确认未改页最终文件或渲染与已审版本对应时，才沿用其原视觉记录。哈希相同可证明文件未变，不能替代该文件之前从未完成的视觉检查。

当用户后续修改公共页脚或某一页型时，以当前要求更新重建参数和最终渲染，不重新填写 `generation.generated_at_utc` 或篡改原提示。`selected_preview` 仍指向真实历史生图，`comparison_observations` 说明当前认可成品与它的必要差异。过时预览可保留为内部追溯依据，不作为更新版成品或加入其ZIP；当前PNG也不能被填入 `generation` 冒充新生图。

## 完成核验

使用当前 `load_workspace_dependencies` 返回的 Python；下面的目录名仅示意。

```powershell
& $runtimePython "$skillRoot/scripts/verify_report.py" "$taskDir/report.json" --pptx "$taskDir/output/汇报.pptx" --require-pure-speech-notes --docx "$taskDir/output/逐页讲稿.docx" --pdf "$taskDir/output/逐页讲稿.pdf" --png-dir "$taskDir/output/逐页PNG" --design-record "$taskDir/design-record.json" --design-preview-dir "$taskDir/design_previews" --require-design-previews --template "$selectedReferencePptx" --brand-profile "$selectedBrandProfile" --require-every-slide-brand --report-json "$taskDir/qa/structural-checks.json"
```

上例 `$selectedReferencePptx` 从参考库解析为本次实际导入保留母版/布局的PPTX；只有实际复用其母版或版式时才传 `--template`。`$selectedBrandProfile` 从当次已选身份和实际品牌文件解析，不自动使用其他汇报人的档案。新报告传 `--require-pure-speech-notes`；有明确逐页品牌要求时再传 `--brand-profile --require-every-slide-brand`，分别检查真实品牌覆盖和整页备注只有canonical讲稿。品牌严格参数缺少PPT或档案时失败，纯备注严格参数缺少PPT时失败。`--require-design-previews` 缺少记录、选用目录或完成页面时失败；不传这些参数的旧版回读行为不能作为新交付严格验收。只传 `--design-record` 也检查记录，但不会认证缺席的 PPT 和最终 PNG；输出用 `ppt_reconstruction_checked` 和 `final_png_substitution_checked` 标明实际覆盖范围。

核验包括：预览页数及页序、实际文件和哈希、返回文件与选用文件同字节、原始参考路径、接受状态、重建页映射、区域边界和准确文案引用。传入 PPT 时，按真实 presentation 关系读取页序，检查原生文字内容与对应对象数量，核对图片原始字节确实属于本页：除本页图片外，允许通过实际 slide→layout→master 关系继承的非占位符品牌和装饰图片；遵循 slide/layout 的 `showMasterSp` 及图片或父组的 `cNvPr@hidden`，不接受别页、无关版式或全局媒体中的同名资产。背景图片只检查最近实际生效的 slide/layout/master 背景，不纳入被近层背景覆盖的远层背景。原生正文、表格和图表仍只计算本页对象，不能用继承文字替代本页可编辑正文。原生表格、图表只检查存在和对应数量，不能代替数值审查。已有 PNG 检查负责最终页数与尺寸，预览检查拒绝将同字节预览作为最终 PNG。核验收据不能覆盖报告、设计记录、选用预览、工具产物、参考资产或最终图片。

结构核验只能证明记录和本地文件对应，不能证明模型确实调用了生图工具、审阅描述真实、整页图片内部不是联系表，也不能判断构图还原程度。继承图片仅检查静态显示标记，不能证明无遮挡、透明度适当或动画后可见；模板图片占位符和主题背景引用的复杂解析不在自动核验范围，可改用在本页独立放置的原始图像并如实记录。执行 agent 必须核对实际工具调用、逐页查看预览与最终渲染、检查主要对象编辑性及生成图与原始科学图的来源。不能把脚本通过称为生图来源认证或视觉验收。
