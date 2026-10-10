---
name: lawpre
description: >
  Build a Chinese legal-course presentation (PRE / 课堂汇报) package: validated
  research inputs (sources registry, analysis units, slide plan with Chinese
  speaker notes), then a native PPTX produced by the ppt-master skill, then
  acceptance checks. Use when the user asks for a 法律课程汇报, PRE, 课堂展示,
  legal case/doctrine presentation, or LawPRE. Works with any general-purpose
  coding agent that can read files and run shell commands.
metadata:
  version: "0.1.0"
---

# LawPRE：法律课程汇报生成

这份 skill 是给任何通用 agent 读取的操作手册。它不依赖某个特定的 agent CLI。
确定性的部分（校验、渲染、验收）由仓库中的 Python 工具完成；判断性的部分（选题、法律分析、讲稿写作）由你完成，并且必须遵守下面的硬性规则。

## 0. 前置条件

- LawPRE 仓库根目录记为 `LAWPRE_HOME`（即包含 `lawpre/` 与 `skills/lawpre/` 的目录）。
- Python 环境中已安装 `jsonschema`：`pip install -r requirements.txt`。
- ppt-master 已固定到验证版本：`scripts/setup_ppt_master.sh`，默认目录 `~/tools/ppt-master`，可用环境变量 `PPT_MASTER_DIR` 指定。
- 执行 `python3 -m lawpre doctor`，全部为 OK 再继续。缺哪一项，就先补哪一项。

所有 `python3 -m lawpre ...` 命令都在 `LAWPRE_HOME` 下执行。

## 1. 硬性规则（不得违反）

1. **不得编造**法条、条号、案例、数字、学术观点或作者信息。缺少依据时，把该内容登记为“待核验”或删除，不得为了让 PPT 更完整而补充。
2. 每一页讲稿中的每个法律判断，都必须能在 `sources.json` 中找到对应来源（`source_ids`）。非封面页没有来源会被校验拒绝。
3. 来源状态只能如实填写：
   - “已核验”：已对照官方原文或权威文本核对条文、日期与定位；
   - “部分核验”：只核对了一部分（如文本已核对，但现行效力未复核）；
   - “待核验”：尚未核对；
   - “存在问题”：核对后发现引用错误或与原文不符。不得作为依据，必须修正或删除；
   - “不适用”：不得作为依据。
4. 只要引用的来源未达到“已核验”，产物就是**草稿**。不得在任何文件或回复中声称“已审核完成”。
5. 规则与适用要分开写：`analysis.json` 中的 `rules`、`application`、`counterargument`、`conclusion` 各自独立，不能把学说或个人评价写成既定规则。
6. 讲稿是口语正文：不得使用列表、标题、括号标记；汉字占比须在 80% 以上。
7. 讲稿经过 `build` 之后，如需修改，必须回到 `deck.json` 修改，再重新 `check` 和 `build`。不要直接改 `out/` 下的文件。

## 2. 工作流

### 第一步：建立输入目录

```bash
python3 -m lawpre init <slug>      # 生成 inputs/<slug>/ 的四个模板文件（占位内容，必须替换）
```

`<slug>` 使用小写字母、数字和连字符，例如 `algorithm-recommendation-pipa`。

### 第二步：确定题目与分析主线（需要用户确认）

与用户确认以下内容，并写入 `brief.json`：课程名、题目、汇报人、时长（分钟，5–30）、老师要求。
只支持 `template_type: "doctrine_analysis"`（法律制度与理论分析）。

题目范围过大时，先缩小到一个明确的法律问题，再继续。题目范围必须在这一步得到用户确认。

### 第三步：登记来源（sources.json）

- 每条法律依据记录：`id`（S001 起）、名称、类型、发布主体、公布与施行日期、原文定位、原文摘录（`excerpt`）、官方链接和 `status`。
- 法律规范必须写 `excerpt`。摘录必须逐字来自原文。无法获取原文时，状态写“待核验”。
- `status_note` 说明已核对的部分与未核对的部分。
- 可以用网络检索找到官方来源。检索结果只能作为候选，必须对照原文后再标记状态。

### 第四步：法律分析（analysis.json）

每个争点一个分析单元：`issue`、`rules`（引用已登记来源）、`application`（有利与不利因素分开列）、`counterargument`（最有力的反方观点）、`conclusion`（目前只能支持的结论）、`uncertainties`（仍不确定的问题）。

### 第五步：逐页内容与讲稿（deck.json）

- 第 1 页为封面（`kind: "cover"`），最后一页通常为结论或边界。
- 每页包含：`title`、`key_message`、`body`（最多 5 条）、`source_ids`、`issue_id`（如适用）、`notes_zh`（中文口播正文）、`duration_seconds`。
- 逐页 `duration_seconds` 合计应接近目标时长（误差 10% 以内）。
- 讲稿节奏：约 260 字/分钟，用于估算。`check` 会给出估算偏差警告，据此调整讲稿或时长。

### 第六步：校验（循环直到通过）

```bash
python3 -m lawpre check inputs/<slug>
```

错误必须全部修正。警告要逐条判断：要么修正，要么在 QA 报告中说明保留的理由。

### 第七步：生成内容包

```bash
python3 -m lawpre build inputs/<slug>
```

输出目录为 `out/<slug>/`，包括：`source/content.md`、`source/references.md`、`notes/total.md`、`SCRIPT_zh.md`、`QA_REPORT.md`、`AGENT_TASK.md`。

### 第八步：制作 PPTX（ppt-master，Quick 路线）

1. 阅读 `AGENT_TASK.md`。它给出了 ppt-master 的 `SKILL.md` 路径、Quick 路线要求、页数、讲稿路径和导出路径。
2. 按 ppt-master 的 `SKILL.md` 执行 **Quick（无交互）路线**：`quick-generate.md`。
   - 页数严格等于 `content.md` 中的页数，不新增或合并页面；
   - 讲稿 `notes/total.md` 已定稿，只校验，不改写；
   - 封面底部标注草稿提示（如适用）；
   - 导出到 `out/<slug>/deck.pptx`，使用 `--with-notes`。
3. 把执行报告写入 `out/<slug>/AGENT_REPORT.md`。

如果运行环境支持无人值守的 agent 命令，也可以设置 `LAWPRE_AGENT_CMD` 后运行 `python3 -m lawpre run inputs/<slug>`。这只是可选方式，不是必需的。

### 第九步：验收

```bash
python3 -m lawpre verify inputs/<slug>
```

验收会检查页数和每页讲稿。未通过时，回到第八步修正，不要绕过验收。

### 第十步：交付

向用户报告：

- `out/<slug>/deck.pptx`、`SCRIPT_zh.md`、`source/references.md`、`QA_REPORT.md` 的路径；
- 草稿状态，以及未核验的来源编号；
- 人工确认清单（见 `QA_REPORT.md`）：逐条核对现行效力、核对引文是否支持结论、排练计时；
- 未完成的事项与理由。

## 3. 需要停下来问用户的情况

- 题目或论证范围过大，需要收窄；
- 课程要求与本流程冲突（如要求其他模板）；
- 需要用户提供的材料（原文、案例文书、人员信息）缺失，又无法自行获取；
- 发现来源之间互相矛盾，且无法判断哪个有效。

其他情况请直接完成，并在报告中列明假设。

## 4. 参考

- 示例输入：`inputs/algorithm-recommendation-pipa/`
- 输入校验规则：`lawpre/inputs.py`，JSON Schema 位于 `lawpre/schemas/`
- ppt-master 技能入口：`$PPT_MASTER_DIR/skills/ppt-master/SKILL.md`（路由以其为准）
