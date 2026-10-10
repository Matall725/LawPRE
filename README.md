# LawPRE

法律课程汇报（PRE）的生成流程。第一轮实现的范围是：**校验输入 → 生成中文讲稿与逐页内容 → 调用 agent 按 ppt-master 技能制作 PPTX → 验收导出文件**。

> 当前版本的内容（分析与讲稿）由人工或上游步骤写入输入文件，程序负责校验、一致性检查和流程编排；不会自动检索法律法规。

## 目录

```
lawpre/                 流程代码（校验、渲染、agent 调用、PPTX 验收）
lawpre/schemas/         输入文件的 JSON Schema
inputs/<slug>/          一次任务的输入：brief / sources / analysis / deck
scripts/setup_ppt_master.sh   克隆并固定 ppt-master 到已验证版本（v6.7.0）
tests/                  单元测试
out/<slug>/             输出（已加入 .gitignore）
```

## 输入文件

| 文件 | 内容 |
|---|---|
| `brief.json` | 课程、题目、时长（分钟）、人员、画布（固定 `ppt169`，16:9）、语言（固定 `zh-CN`） |
| `sources.json` | 来源登记表。每条有 `id`（S001…）、`status`（已核验 / 部分核验 / 待核验 / 不适用）、原文定位、摘录 |
| `analysis.json` | 争点分析单元：规则（必须引用已登记来源）、适用、反方、结论、待确认事项 |
| `deck.json` | 逐页内容：类型、标题、要点、来源、中文讲稿、预计时长 |

校验规则要点：

- 所有引用的来源必须已登记；状态为“不适用”的来源不能作为规则依据；
- 非封面页必须有来源；第 1 页必须是封面；
- 逐页时长合计与目标时长相差不超过 10%（硬性，失败则停止）；
- 讲稿必须是中文口播正文，不得含列表或标题标记；
- 讲稿估算时长（按 260 字/分钟）与设定时长偏差超过 25%，或全篇估算偏离目标超过 25%，给出警告；
- 只要引用的来源未达到“已核验”，产物即标注为**草稿**，不得宣称已审核完成。

## 使用

```bash
python3 -m venv ~/.venvs/lawpre && ~/.venvs/lawpre/bin/pip install -r requirements.txt

PY=~/.venvs/lawpre/bin/python
$PY -m lawpre check  inputs/algorithm-recommendation-pipa     # 只校验
$PY -m lawpre build  inputs/algorithm-recommendation-pipa     # 生成内容包与任务书
$PY -m lawpre run    inputs/algorithm-recommendation-pipa     # 生成并调用 agent
$PY -m lawpre verify inputs/algorithm-recommendation-pipa     # 验收已导出的 deck.pptx
$PY -m lawpre doctor                                          # 检查 ppt-master 环境
$PY -m unittest discover -s tests -v                          # 运行测试
```

退出码：`0` 成功；`1` 输入校验未通过；`2` 环境未就绪（缺 ppt-master，或未配置 agent，内容包仍会生成）；`3` agent 失败或超时；`4` PPTX 验收未通过。

### 制作 PPT：ppt-master 与 agent

1. 固定 ppt-master 版本：

   ```bash
   scripts/setup_ppt_master.sh           # 默认 ~/tools/ppt-master，可通过 PPT_MASTER_DIR 指定
   ```

2. 配置 agent 命令。LawPRE 会把任务书路径替换进命令，并在 ppt-master 目录下执行。占位符：`{task_file}`、`{workdir}`、`{out_dir}`。参数以你本机 CLI 为准，例如：

   ```bash
   export LAWPRE_AGENT_CMD='claude -p "请阅读并完成 {task_file} 中的任务" --permission-mode acceptEdits'
   ```

3. 运行 `run`。agent 按任务书读取 ppt-master 的 `SKILL.md`，使用 **Quick（无交互）路线**，把 `notes/total.md` 作为已定稿的中文讲稿，导出 `out/<slug>/deck.pptx`，并写入 `AGENT_REPORT.md`。LawPRE 随后检查页数与每页讲稿，并写入 `result.json`。

如果只想人工执行，可先运行 `build`，然后把 `out/<slug>/AGENT_TASK.md` 交给任意 agent，完成后运行 `verify`。

## 输出（`out/<slug>/`）

| 文件 | 用途 |
|---|---|
| `source/content.md` | ppt-master 的逐页内容 |
| `source/references.md` | 引用资料表（含原文摘录，不进入 PPT 页面） |
| `notes/total.md` | 完整中文讲稿，`# NN_标题` 分页格式 |
| `SCRIPT_zh.md` | 给人阅读的讲稿，附每页时长与依据 |
| `QA_REPORT.md` | 校验结果、草稿状态、人工确认清单 |
| `AGENT_TASK.md` / `AGENT_REPORT.md` | 交给 agent 的任务书与 agent 的执行报告 |
| `deck.pptx` / `result.json` | 导出结果与验收结果 |

## 边界

- 本仓库不包含 ppt-master，也不包含 agent 本身；需要用户自行提供 agent CLI 及其凭据。
- 示例输入（`inputs/algorithm-recommendation-pipa`）引用的条文已对照官方发布页面核对文本，但**现行效力尚未在国家法律法规数据库复核**，因此状态为“部分核验”，产物为草稿。
- 人工法律审查、排练计时仍是必须的步骤，QA 报告中列出了清单。
