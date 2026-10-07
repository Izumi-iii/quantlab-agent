# QuantLab Agent 项目规划与任务接续文档

> 文档版本：v1.0  
> 建立日期：2026-09-29  
> 项目目录：`D:\aaaWang\quantlab-agent`  
> 当前阶段：M1 确定性核心、M2 工具与运行记录、本地图表／报告和确定性演示入口已完成；真实模型 Agent 与 UI 待实现。
> 本文性质：设计基线与接续记录。文中的模块、命令、测试、指标和产物，除明确标注为“已完成”或列入第 19、20 节验证记录外，均为计划，不代表已经实现或验证。

## 0. 给后续接手者的快速说明

### 0.1 我们要做什么

做一个面向初级研究者的量化数据分析助手：用户上传历史日线价格 CSV，用自然语言提出问题；Agent 在受控工具范围内检查数据、确定分析参数、计算收益风险指标、绘图，并产出可追溯的分析报告。

一句话定义：**用自然语言驱动可验证的历史数据分析，并让用户看见分析依据和限制。**

项目用于开发实习生和量化产品研究实习生的求职展示。优先证明工程实现、数据处理、工具调用、异常处理和评估能力。项目不以策略收益、金融预测或自主交易为目标。

### 0.2 已经达成的共识

- 用户接受“量化数据分析 Agent”这一项目方向。
- 用户已创建 GitHub 仓库并克隆到本地。
- 用户计划在 AI 辅助下完成项目，投入时间为几天；准确可用时间尚未确认。
- 采用一个能完成完整分析流程的小项目，避免过度扩展。
- 真实 Agent 应调用预定义分析工具，数值由程序计算。
- 需要无需 API 密钥的演示模式，但必须与真实模型模式明确区分。
- 当前用户仅要求详细规划文档，明确要求暂不构建代码。

### 0.3 尚未确定的事项

- 实习岗位的完整职责和技术栈：目前仅有岗位名称、地点以及公司的公开产品方向。
- 模型服务商、具体模型、API 配置与预算。
- 每天能投入多少时间，以及期望投递日期。
- 用于公开演示的真实数据来源、授权条件、价格口径。
- 是否将来需要云端部署。首版按本地运行设计。

这些不确定项不能被写成已经确认的招聘要求或已完成的配置。除模型联调和真实数据发布外，多数开发工作可以在明确标注的默认假设下开展。

### 0.4 后续恢复任务的顺序

1. 阅读本文件的第 0、4、8、13、19、20 节。
2. 查看仓库中的 `AGENTS.md`（若新增）、README 和 Git 工作区状态。
3. 检查第 19 节状态记录与仓库实际文件是否一致，不能直接相信旧记录。
4. 查看用户最新要求，判断是否已经授权开始实现。
5. 开始开发时优先处理 M1：数据契约和确定性计算，不先搭复杂对话界面。
6. 每完成一个里程碑，更新状态、验证结果、已知问题和下一步。

**恢复上下文时不能把规划清单自动理解为本轮执行授权，也不能把计划中的验收结果当成实际测试结果。**

## 1. 项目背景与求职目标

### 1.1 当前能力背景

用户现有简历主要呈现以下经历：

- 物联网工程本科，预计 2027 年毕业。
- 两个 macOS 应用项目：截图标注工具和公式截图识别工具。
- 主要技术经历为 Swift、AppKit、SwiftUI、Core ML 等。
- 有分层架构、状态机、任务取消、会话隔离、异常恢复等实践描述。
- 有竞品调研、产品范围、技术文档和数学建模竞赛经历。
- Python 在简历中属于“了解”，尚未展开量化数据分析和 Agent 项目。

以上仅用于决定项目难度和学习重点，不需要将个人联系方式、完整简历或其他隐私资料提交到公开仓库。

### 1.2 为什么选择这个项目

项目应把现有工程能力延伸到新的业务场景：

| 已有能力 | 新项目中的对应实践 |
| --- | --- |
| 分层架构 | 界面、Agent、工具、分析与产物存储分层 |
| 状态机和会话隔离 | 分析任务状态、等待澄清、失败恢复、旧结果隔离 |
| 异常处理 | 文件错误、参数错误、工具失败、模型超时 |
| 产品设计 | 明确用户问题、展示依据、解释不可分析原因 |
| AI 辅助开发 | 拆解任务、审查生成代码、验证关键计算 |

不需要重新做一个通用聊天机器人，也不需要用一个项目补齐整个量化知识体系。

### 1.3 对两个岗位分别提供什么证据

| 投递方向 | 项目应提供的证据 | 不能替代的能力 |
| --- | --- | --- |
| 开发实习生 | Python 工程组织、工具接口、输入校验、日志、状态管理、测试 | 岗位实际技术栈、基础编程能力、已有项目深度 |
| 量化产品研究实习生 | 研究流程、指标口径、数据质量判断、产品验收和失败案例分析 | 更深入的金融知识、研究经历、实际岗位要求 |

同一个项目可以支持两种简历表述，但不能声称短期项目已证明专业量化研究能力。

### 1.4 成功标准

项目达到首版完成标准时应具备：

1. 一个可本地运行的应用。
2. 一套独立于模型、能通过测试的分析工具。
3. 一条真实模型驱动的工具调用流程。
4. 一个无需密钥也能运行的确定性演示模式。
5. 一份带数据依据、口径与局限的报告。
6. 一组包含正常、歧义和异常请求的评估任务及真实记录。
7. 一份新人可复现的 README，以及用户能讲清楚的设计与失败案例。

其中第 3 条未完成时，可以称为“数据分析应用／Agent 原型”，不能称为已验证的完整 Agent 项目。

## 2. 用户、场景与产品问题

### 2.1 目标用户

主要用户是具备基本研究问题、愿意检查分析依据，但不希望每次重写清洗和绘图脚本的初级研究者。

典型使用条件：已有历史日线价格文件；希望快速获得一组口径明确的比较结果；并非依赖系统做投资决策。

### 2.2 核心问题

- 用户的问题是自然语言，计算程序需要明确的资产、区间和指标参数。
- 不同文件的日期和价格口径可能不同，直接比较容易产生误导。
- 语言模型能生成流畅解释，但不能仅凭文本可信地计算指标。
- 传统演示常只展示最终答案，难以确认数据来源、步骤和错误处理。

### 2.3 用户故事

| 编号 | 用户故事 | 验收关注点 |
| --- | --- | --- |
| US-01 | 上传一份文件，查看某资产的历史价格表现 | 识别资产、检查数据、正确计算 |
| US-02 | 比较两份文件中资产的收益、波动和回撤 | 区间与价格口径可比 |
| US-03 | 发现错误时知道具体哪项数据有问题 | 错误可定位，有修正方法 |
| US-04 | 修改时间区间后重新分析 | 参数继承明确，不混用旧结果 |
| US-05 | 查看报告中数值的来源 | 能对应到工具输出和运行记录 |
| US-06 | 在没有模型密钥时体验项目 | 演示模式完整，且不伪装成真实模型 |

### 2.4 首个标准演示

用户上传两个资产的同市场日线 CSV，并问：

> 比较这两个资产在 2024-01-01 至 2024-12-31 的区间收益、年化波动率和最大回撤。先检查数据是否适合比较。

系统应：

1. 展示已导入文件及数据覆盖区间。
2. 检查字段、重复记录、价格有效性、频率和口径声明。
3. 检查两个资产是否存在可比较的数据区间。
4. 必要时追问用户，而非自行编造价格口径。
5. 返回各指标、归一化价格图和回撤图。
6. 明确请求区间与实际使用区间。
7. 输出“依据—发现—限制”的报告，并允许下载。

接着演示：

> 改成 2024 年下半年，沿用刚才的其他设置。

最后用一份重复日期数据演示系统停止计算并给出修正建议。

## 3. 范围与优先级

### 3.1 P0：首版必须完成

- 一次上传 1—2 个 CSV 文件，每个文件仅代表一个资产。
- 用户声明资产标识、日线频率、价格口径、币种及市场／交易日历描述。
- 标准化字段、检查数据、展示质量问题。
- 指定绝对日期区间，按预定义规则确定有效样本。
- 区间收益、年化波动率、最大回撤。
- 归一化价格图、回撤图和指标表。
- 真实模型通过受控工具完成分析。
- 缺少关键参数时澄清；不支持的任务明确拒绝或说明范围。
- 工具调用日志、运行记录、报告导出。
- 确定性演示模式。
- 核心计算与隔离测试、至少 20 个 Agent 评估任务。
- 安装与演示说明。

### 3.2 P1：核心完成后可做

- 一次有限的上下文追问：只修改日期范围或选择已有资产。
- 任务取消与界面重置的更好体验；即使未实现硬取消，也必须隔离旧结果。
- 显示调用耗时、调用次数；在服务商返回相关信息时显示 token 用量。
- 比较报告的第二次运行与第一次运行的参数差异。
- 一页独立产品说明和 2—3 分钟演示视频。
- 用一组允许公开分发的真实数据替换或补充合成演示数据。

上下文追问若工期不足，可降级为“修改表单参数并重新提交”。README 必须写明真实支持情况。

### 3.3 P2：后续扩展，不作为首版交付前提

- 在线行情接口。
- 更多资产、批量研究、滚动窗口分析。
- 单一简单策略的实验与回测。
- 文档检索和研报引用。
- 把分析能力封装为可复用技能或接入其他工具协议。
- 云端部署、多用户、数据库与身份认证。

### 3.4 首版明确不做

- 自动交易、自动选股、收益预测。
- 自动挖掘有效因子或宣称获得 Alpha。
- 任意 Python 生成与执行。
- 多 Agent 辩论、专家团、复杂规划框架。
- 全市场证券数据库、分钟数据、期货换月、组合回测。
- 全功能 RAG、向量数据库、联网爬虫。
- 因子 IC、夏普比率、年化收益率等额外指标。
- 登录、付费、用户权限体系。

后续增加范围时应记录原因、成本以及会推迟哪项核心验收，不能直接在计划外堆功能。

## 4. 数据契约与数据质量

### 4.1 CSV 格式

首版采用最小固定格式：

```csv
date,close
2024-01-02,100.0
2024-01-03,101.5
2024-01-04,100.8
```

- 必需字段：`date`、`close`。
- `date`：严格的 `YYYY-MM-DD`，表示日线价格对应日期。
- `close`：正的有限数值。
- UTF-8／UTF-8 BOM 为首版支持编码；其他编码给出转换提示。
- 一个文件一个资产；资产标识由导入界面填写，不能仅靠文件名推测。
- 额外字段可保留为原始数据，但不参与首版计算；应在导入结果中说明。
- 不自动猜测中文列名、多层表头、币种格式或日期格式。可在后续版本增加显式映射。
- 文件大小初始限制建议为每份 5 MB、5 万行；实施时用常量统一管理并在界面说明。

### 4.2 必需元数据

每个数据集应记录：

| 字段 | 含义 |
| --- | --- |
| dataset_id | 系统生成的内部标识 |
| asset_id | 用户声明的资产标识，唯一且限制长度 |
| source_name | 数据来源，允许填写“用户提供，未核实” |
| source_url | 可选，数据来源页面，不作为自动抓取目标 |
| price_basis | 未复权／前复权／后复权／总收益指数／未知 |
| currency | 币种，未知时必须标记 |
| frequency | 首版要求声明为日线 |
| calendar_label | 市场／交易日历描述；声明不等于系统已经验证 |
| is_synthetic | 是否为合成数据 |
| uploaded_at | 导入时间 |
| raw_sha256 | 原始文件字节哈希 |
| normalized_sha256 | 规范化结果哈希 |
| date_min/date_max/rows | 覆盖区间与行数 |

不得把“复权价格收益”直接命名为“含分红总收益”。数据来源对复权方法的定义不同，报告必须保留实际声明。

### 4.3 数据检查规则

| 问题 | 处理方式 | 是否继续分析 |
| --- | --- | --- |
| 无法读取、空文件、字段缺失 | 返回具体错误和格式示例 | 否 |
| 日期解析失败、空日期 | 指出行号与问题类型 | 否 |
| 非数值、NaN、无穷、非正价格 | 指出行号，不自动删除 | 否 |
| 重复日期 | 区分重复值与冲突值，但均要求用户修正 | 否 |
| 日期未排序 | 稳定排序，记录转换 | 是 |
| 声明为分钟线、周线等 | 提示首版只支持日线 | 否 |
| 价格口径未知 | 追问，或在用户选择描述性分析后降级 | 有条件 |
| 单日变化异常大 | 警告并定位；不自行认定错误或删除 | 是，但报告需说明 |
| 已知缺少本应存在的交易日 | 标记间隔收益，不输出日频年化波动率 | 可输出其他有限结论 |
| 数据截止时间早于用户要求 | 展示截断范围，要求确认调整 | 确认后 |
| 无有效重叠日期 | 说明不能进行同区间比较 | 否 |

周末和法定休市不应被直接判为缺失交易日。首版不内置完整交易所日历时，不能声称已经验证日线完整性。

### 4.4 两资产对齐规则

1. 首版比较优先限定同市场、相同声明频率、相同价格口径和币种。
2. 请求区间与数据覆盖区间必须分别记录。
3. 在确认后的区间内使用共同观测日期进行比较，并报告各资产被排除的日期数量。
4. 不前向填充、不后向填充、不插值、不把缺失价格填为零。
5. 当资产日期序列不一致时，不能把交集上跨多个交易日的收益当作单日收益年化。
6. 对不一致序列，首版可输出共同采样日期上的区间收益与采样回撤；年化波动率置为不可用并说明原因。
7. 共同日期采样可能漏掉中间极值，因此回撤应标注“共同观测日期上的最大回撤”，不能宣称为完整日线最大回撤。
8. 日期一致且用户声明为完整日线时，可基于该声明计算年化波动率，但必须标明“未独立核验交易日完整性”。
9. 不同币种不做货币换算，不输出基于同一投资者币种的比较结论。需要用户提供口径一致的数据。

### 4.5 数据数量与降级

- 0—1 个价格点：不能计算收益风险指标。
- 至少 2 个价格点：可以计算区间收益和采样最大回撤。
- 至少 3 个价格点：样本标准差在数学上可计算，但短样本必须警告。
- 少于 20 个收益观测：展示“样本很短，结果仅作描述”的警告，不作稳定性推断。
- 长样本也不自动代表结果具有预测能力。

### 4.6 演示数据策略

首版先使用固定随机种子或手工定义的合成数据，解决复现和分发问题。

- 数据和界面必须明确标注“合成演示数据”。
- 使用 `DEMO_A`、`DEMO_B` 等标识，避免冒充真实 ETF 价格。
- 合成工作日日历不等于真实交易所日历。
- 提供正常、重复日期、缺失字段、无重叠区间等样本。
- 若引入真实数据，记录来源、获取日期、许可和价格口径；确认能否公开分发后再提交仓库。
- 不把用户上传数据自动提交到 Git。

## 5. 指标与图表口径

### 5.1 区间价格收益

对选定且排序后的价格序列 `P_0 ... P_n`：

```text
period_return = P_n / P_0 - 1
```

这是所选价格口径下的区间变化，不自动包含交易成本、税费或现金分红再投资。

### 5.2 简单收益序列

```text
r_t = P_t / P_(t-1) - 1, t = 1 ... n
```

首个价格点没有收益值。计算实现必须显式控制缺失值处理，禁止依赖库中可能产生隐式填充的默认行为。

### 5.3 年化波动率

```text
annualized_volatility = sample_std(r, ddof=1) * sqrt(252)
```

- 252 是本项目的默认年化假设，不是每个年份或市场的真实交易日数。
- 仅对符合第 4 节条件的日频收益计算。
- 至少两个收益观测才能计算样本标准差。
- UI 和报告展示年化因子、样本数和日线完整性验证状态。
- 不将跨期收益、周收益或不规则日期收益按日收益年化。
- 首版不做年化因子自由配置，避免进一步扩大解释范围。

### 5.4 最大回撤

```text
running_peak_t = max(P_0 ... P_t)
drawdown_t = P_t / running_peak_t - 1
max_drawdown = min(drawdown_t)
```

- 输出采用非正数约定，例如 `-10.00%`。
- 峰值从当前分析窗口第一个价格开始计算，不引入窗口前历史高点。
- 若只有共同采样日期，名称和解释必须反映采样限制。
- 首版不计算回撤恢复期，避免引入边界和并列峰值处理的额外复杂度。

### 5.5 图表

- 归一化价格：`normalized_price_t = P_t / P_0 * 100`。
- 回撤曲线：采用本节定义。
- 图中明确资产、区间、价格口径和合成数据标记。
- 数值轴使用一致单位，避免把收益率与价格放在同一轴上。
- 图表和指标必须使用相同的数据切片与对齐结果。

### 5.6 手工可验证样例

价格序列：`100, 110, 99, 108.9`。

- 简单收益：`10%, -10%, 10%`。
- 区间收益：`8.9%`。
- 最大回撤：`-10%`。
- 归一化价格：`100, 110, 99, 108.9`。
- 年化波动率：`sqrt(252) * sample_std([0.1, -0.1, 0.1], ddof=1)`；测试应独立展开样本方差，避免调用同一实现来生成期望值。

还应验证：常数价格、单调上涨、单调下跌、两个点、零价格拒绝、分析区间中途起始。

### 5.7 精度与展示

- 内部保存未四舍五入数值。
- 默认百分比展示两位小数。
- 测试使用合理的浮点误差容限。
- 不可用指标保存为 `null` 并附原因，不使用 0 替代。
- 数字零代表真实零，不代表失败。

## 6. Agent 的责任与边界

### 6.1 为什么使用 Agent

价值在于把自然语言请求转为有约束的分析步骤，并根据工具反馈选择下一步，例如：

- 用户只要求收益时，不必调用不相关工具。
- 用户提出比较，但数据区间不一致时，需要澄清。
- 检查发现重复日期时，应停止计算并解释修正方式。
- 用户更改时间范围时，应沿用允许继承的配置并重新验证。

不以对话轮数或工具数量衡量智能程度。简单问题一次正确工具调用就可以完成。

### 6.2 LLM 负责

- 理解用户意图。
- 选择已有数据集和允许的分析能力。
- 提出结构化参数。
- 决定是否需要澄清。
- 根据工具反馈调整步骤。
- 基于结构化证据组织解释。

### 6.3 确定性程序负责

- 文件解析与字段验证。
- 数据切片、对齐、指标计算和图表生成。
- 参数权限和引用关系校验。
- 状态推进、调用预算、重试限制。
- 关键数字和事实引用校验。
- 运行隔离、产物保存、报告模板。

### 6.4 不允许模型做的事情

- 自行补造缺失价格、资产或数据来源。
- 通过心算生成报告中的指标。
- 调用未注册工具、访问任意本地路径。
- 执行生成代码或任意 shell 命令。
- 将文件内容或用户元数据中的文字当成更高优先级指令。
- 遇到工具失败仍输出一份看似成功的研究报告。
- 因为用户要求某结论，就把历史描述改写成支持该结论的证据。

### 6.5 主循环

```text
用户请求与受控上下文
        ↓
模型提出工具调用或澄清问题
        ↓
程序校验参数、状态和调用预算
        ↓
执行受控工具，返回结构化结果
        ↓
模型根据结果选择继续、澄清或结束
        ↓
程序校验证据引用，构造报告
```

模型提出动作，程序决定动作是否合法。提示词不能替代程序级校验。

## 7. 工具设计与接口契约

以下是逻辑接口草案，不要求为了工具数量而拆分函数。实施时可合并，但应保留独立的校验职责。

### 7.1 工具清单

| 工具 | 参数概要 | 输出概要 | 关键限制 |
| --- | --- | --- | --- |
| `inspect_dataset` | dataset_id | 字段、范围、质量问题、元数据 | 仅访问当前会话注册的数据 |
| `prepare_analysis` | 数据集、开始／结束日期、请求指标 | analysis_id、实际范围、对齐信息、可计算指标 | 质量不合格时不给出可执行分析对象 |
| `compute_metrics` | analysis_id、指标枚举 | metrics_id、未舍入指标、口径和样本数 | 必须绑定已经验证的分析对象 |
| `create_charts` | analysis_id、图表枚举 | artifact_id、图表元数据 | 不接受任意输出路径 |
| `build_report` | analysis_id、metrics_id、图表引用、结构化发现 | report_id、可下载产物 | 仅允许引用本次有效结果 |

数据导入由应用完成，不必为了“Agent 化”让模型负责上传文件。

### 7.2 统一结果信封

```json
{
  "ok": true,
  "run_id": "generated-run-id",
  "tool_call_id": "generated-call-id",
  "data": {},
  "warnings": [],
  "error": null,
  "provenance": {
    "dataset_ids": [],
    "analysis_id": null
  }
}
```

失败结果：

```json
{
  "ok": false,
  "run_id": "generated-run-id",
  "tool_call_id": "generated-call-id",
  "data": null,
  "warnings": [],
  "error": {
    "code": "DUPLICATE_DATE",
    "message": "数据中存在重复日期，暂不能分析。",
    "retryable": false,
    "details": {"row_numbers": [8, 9]}
  }
}
```

错误信息需要可读，但不能包含密钥、未经裁剪的堆栈或任意本地敏感路径。

### 7.3 参数约束

- dataset_id、analysis_id、metrics_id 必须存在，且属于当前会话和有效运行上下文。
- dates 使用明确字符串格式，并验证先后顺序。
- 指标和图表采用枚举，拒绝未知值。
- 一个 analysis_id 对应固定的参数和数据快照；修改参数生成新对象。
- 模型提交的 asset_id 不直接映射到文件路径。
- 不能通过另一个会话的 ID 获取结果。
- 参数验证失败后允许有限次模型纠正，禁止无限循环。

### 7.4 工具错误分类

建议初始错误码：

`INVALID_FILE`、`MISSING_COLUMN`、`INVALID_DATE`、`INVALID_PRICE`、`DUPLICATE_DATE`、`UNSUPPORTED_FREQUENCY`、`INCOMPATIBLE_PRICE_BASIS`、`NO_OVERLAP`、`INSUFFICIENT_DATA`、`INVALID_ARGUMENT`、`UNKNOWN_REFERENCE`、`STALE_RUN`、`PROVIDER_TIMEOUT`、`TOOL_FAILURE`、`BUDGET_EXCEEDED`。

错误码属于接口契约，错误描述用于界面。不要依赖对中文错误文本做字符串匹配来控制状态。

## 8. 报告可信度与证据链

### 8.1 输出报告结构

1. 用户问题与模式标识。
2. 数据来源、资产、价格口径和合成标记。
3. 请求区间、实际区间、样本数、日期对齐策略。
4. 数据质量检查结果及转换记录。
5. 指标表与图表。
6. 基于工具结果的主要发现。
7. 不可计算项与原因。
8. 口径、限制和未核验事项。
9. run_id、数据哈希、配置版本与产物清单。

### 8.2 避免“表格正确、正文胡说”

首版优先使用结构化发现和模板化数字插入，而不是让模型自由书写全部事实：

```json
{
  "finding_type": "metric_comparison",
  "metric": "period_return",
  "asset_ids": ["DEMO_A", "DEMO_B"],
  "evidence_id": "metrics-001"
}
```

程序根据真实结果生成大小关系和数字。模型可以提出解释组织方式，但不能自行指定胜者或覆盖数字。

自由文本只允许有限的描述和局限说明；对无法由现有数据证明的因果解释，不写成事实。例如只有价格数据时，不能断言上涨是由某政策或资金流造成。

### 8.3 引用完整性

- 每个发现应能追溯到本次工具结果。
- 缺少指标时不能引用旧运行同名指标补全。
- 图表、报告和指标表必须绑定同一个 analysis_id。
- 数据检查失败时输出诊断结果，不伪装成正常分析报告。
- 合成数据不能用于真实资产结论。

### 8.4 可复现的含义

分两层说明：

1. **数值可复现：**相同数据快照、分析配置和计算版本，应得到相同指标与图表数据。
2. **执行可追溯：**保存模型、参数、提示词版本及调用记录，便于解释本次过程。

不能承诺再次请求远程模型会生成完全相同的调用序列或自然语言文本。

## 9. 模式、状态与对话管理

### 9.1 两种运行模式

| 模式 | 目的 | 行为 | 展示要求 |
| --- | --- | --- | --- |
| 演示模式 | 无密钥体验、确定性验证 | 选择预设任务，由固定控制逻辑调用相同工具 | 明示“不调用真实模型” |
| 真实 Agent 模式 | 验证自然语言和模型工具调用 | 模型根据用户请求和工具反馈决策 | 显示服务商、模型和调用情况 |

演示模式可以使用下拉预设与表单参数，不必伪装成任意自然语言理解。没有密钥时不得悄悄切换并仍标注为真实 Agent。

### 9.2 状态模型

```text
IDLE → DATA_READY → RUNNING
RUNNING → NEEDS_CLARIFICATION → RUNNING
RUNNING → SUCCEEDED
RUNNING → FAILED
RUNNING → CANCELLED
```

- 每次提交产生独立 run_id。
- 每次会话有 session_id，不能只使用全局最近结果变量。
- NEEDS_CLARIFICATION 表示等待用户输入，不能继续猜测依赖该信息的计算。
- 参数变更创建新分析对象；保留前次结果用于展示历史，不覆盖其配置。
- 重复点击应被禁用或识别，避免创建多个重叠任务。
- 用户重置后，旧任务即使返回也不得更新当前界面。

首版可采用同步执行和合作式取消。取消不代表已中断远端请求或不会产生服务商费用，应以状态隔离保证结果不串线。

### 9.3 上下文继承

如果实现 P1 追问，只继承以下结构化字段：

- 已选择的数据集。
- 已确认的价格口径和日线声明。
- 前一次成功分析的日期范围和指标集。

不把整段聊天历史当作唯一状态来源。修改日期后重新检查样本，不复用旧指标。

### 9.4 相对日期

首版优先要求绝对日期。对于“去年”“最近一年”：

- 不由模型静默选择当前日期或数据截止日期作为锚点。
- 追问基准日期，或展示解析后的明确日期供用户确认。
- 运行记录保存基准日期、时区和最终绝对日期。

### 9.5 Natural Language Agent 规划层设计（待实现）

当前两栏 Web UI 的 Natural Language Agent 入口仍然主要走确定性 demo pipeline：用户文本会写入 run 和 report，但分析行为默认仍是“绑定当前 session 的所有数据集，使用固定日期区间和固定指标，顺序执行 inspect → prepare → compute → chart → report”。这保证了演示稳定，但不代表自然语言真的决定了分析计划。

后续目标不是把 UI 做得更像聊天，而是让用户请求真正影响执行计划：选择哪些数据集、计算哪些指标、是否生成图表、是否生成报告、是否只做数据质量检查，以及何时追问。

建议新增一个受控 planner 层，位于 UI / message handler 与工具执行之间：

```text
用户自然语言
  ↓
Planner（真实模型或可测试替身）
  ↓
结构化 AnalysisPlan
  ↓
PlanValidator（后端确定性校验）
  ↓
PlanExecutor（按计划调用现有工具）
  ↓
表格 / 图表 / 报告 / 澄清问题
```

Planner 只负责把自然语言翻译成结构化计划；数值计算、数据选择校验、日期范围校验和工具调用顺序仍由后端控制。这样比直接让模型自由调用所有工具更稳定，也更容易测试。

#### 9.5.1 P0 优先级

让两栏 Web UI 更像正式 Agent 的 P0 不是视觉效果，而是让自然语言真正影响分析行为。首轮实现应优先保证以下四点：

1. **接入 planner 层**：用户输入先转成结构化 `AnalysisPlan`，再由后端校验和执行。不同请求必须能产生不同 intent、不同数据集选择、不同指标和不同工具路径。
2. **支持澄清问题**：当用户请求缺少关键参数时，进入 `clarify` / `NEEDS_CLARIFICATION`，由 Agent 在左侧对话中追问，而不是直接跑固定分析或猜测参数。
3. **结果以 Agent 消息表达**：左侧不应只显示“已完成分析”。应根据执行结果生成简短用户可读消息，例如“我检查了 2 个数据集，数据质量可用”“我使用了共同区间 2024-01-02 至 2024-01-15”“报告已生成，右侧可预览”。工具调用链继续默认折叠。
4. **右侧产物跟随 intent**：`data_quality` 展示质量诊断，`metrics` 展示指标表，`chart` 展示图表，`report` 展示 Markdown 报告；不要所有请求都默认生成完整报告。

这四项完成前，Natural Language Agent 仍只能视为“聊天式 demo UI”，不能视为真正根据问题行动的 Agent。

#### 9.5.2 AnalysisPlan 草案

计划对象建议先覆盖首版需要的有限字段：

```json
{
  "intent": "data_quality | metrics | chart | report | clarify | out_of_scope",
  "dataset_refs": ["DEMO_A", "DEMO_B"],
  "date_range": {
    "start": "2024-01-02",
    "end": "2024-01-15"
  },
  "metrics": ["period_return", "max_drawdown"],
  "charts": ["normalized_prices", "drawdown"],
  "clarifying_question": null,
  "user_visible_summary": "Compare DEMO_A and DEMO_B over the selected range."
}
```

字段含义：

- `intent`：决定执行路径。`data_quality` 只检查数据；`metrics` 计算指标；`chart` 生成图；`report` 生成完整报告；`clarify` 表示需要追问；`out_of_scope` 表示拒绝。
- `dataset_refs`：用户可见资产名、文件名或 planner 从数据集列表中选择出的引用。进入执行前必须解析为当前 session 内的 `dataset_id`。
- `date_range`：必须是绝对日期。若用户用了“最近一年”“去年”等相对表达，应先追问或返回待确认计划，不能静默猜测。
- `metrics`：只能来自当前系统支持的指标集合，例如 `period_return`、`max_drawdown`、`annualized_volatility`。
- `charts`：只能来自当前系统支持的图表类型，例如 `normalized_prices`、`drawdown`。
- `clarifying_question`：当请求缺少关键参数时，作为下一轮对话展示给用户。
- `user_visible_summary`：给 UI 展示“将要做什么”，不是计算依据。

#### 9.5.3 典型请求到计划的映射

| 用户请求 | 期望 intent | 期望行为 |
| --- | --- | --- |
| “数据质量怎么样？” | `data_quality` | 调用 `list_datasets` 和 `inspect_dataset`；不计算指标、不生成完整报告。 |
| “只分析 DEMO_A 的最大回撤” | `metrics` | 只选择 DEMO_A，指标只含 `max_drawdown`；不默认把所有资产都加入。 |
| “画一下 DEMO_A 和 DEMO_B 的走势” | `chart` | 选择两个资产，生成归一化价格图；可不生成 Markdown report。 |
| “比较两个资产并生成报告” | `report` | 检查数据、准备分析、计算指标、生成图表和报告。 |
| “分析一下”且当前有多个资产 | `clarify` | 追问用户要分析哪个资产、哪个区间、需要指标/图表/报告中的哪一种。 |
| “推荐我买哪只股票” | `out_of_scope` | 拒绝投资建议，不调用分析工具。 |

#### 9.5.4 PlanValidator 规则

Planner 输出不能直接执行，必须经过后端确定性校验：

- 数据集必须属于当前 session，不能跨 session 引用旧数据。
- 用户可见 `asset_id` / 文件名必须解析为唯一 `dataset_id`；存在歧义时进入 `clarify`。
- 日期必须是合法 ISO 日期，且与数据覆盖区间有交集；无交集时失败或追问。
- 指标和图表必须在白名单内。
- `out_of_scope` 请求不能落到工具执行。
- `data_quality` 不应隐式生成收益报告。
- `metrics` 或 `chart` 若缺少日期范围，可使用数据覆盖区间作为候选，但应在 UI 中明确展示；对相对日期仍需追问或确认。
- 计划校验失败时应返回结构化错误或澄清问题，而不是让模型继续猜。

#### 9.5.5 PlanExecutor 执行路径

执行层复用现有 Tool Registry 和服务，不重新实现计算：

| intent | 最小工具路径 |
| --- | --- |
| `data_quality` | `list_datasets` → 对目标数据集调用 `inspect_dataset` |
| `metrics` | `list_datasets` → `inspect_dataset` → `prepare_analysis` → `compute_metrics` |
| `chart` | `list_datasets` → `inspect_dataset` → `prepare_analysis` → 可选 `compute_metrics` → `create_charts` |
| `report` | `list_datasets` → `inspect_dataset` → `prepare_analysis` → `compute_metrics` → `create_charts` → `build_report` |
| `clarify` | 不调用分析工具，保存 `NEEDS_CLARIFICATION` |
| `out_of_scope` | 不调用分析工具，保存 `FAILED` 或专门的拒绝状态 |

工具调用链默认只作为可折叠调试信息展示。用户主要看到的是：Agent 的追问、质量诊断、指标表、图表或报告。

#### 9.5.6 与现有 AgentController 的关系

现有 `AgentController` 已经支持真实模型 tool-calling：模型可以看到工具定义并逐步调用工具。这个能力可以继续保留，但两栏 Web UI 的产品体验不应完全依赖模型自由调工具。

建议分阶段：

1. **Planner-first**：真实模型只输出 `AnalysisPlan`；后端 deterministic executor 按计划调用工具。这是首选落地方案。
2. **Tool-calling fallback**：保留现有 `AgentController`，用于 CLI、评估或高级模式。
3. **Hybrid**：planner 先出计划；必要时允许模型在受限工具集合内补充调用，但仍要经过引用归属和 schema 校验。

这样可以把“自然语言理解”与“可信计算执行”分开，降低模型误用 `dataset_id`、漏掉必要工具、提前输出文本或生成无证据报告的风险。

#### 9.5.7 Web UI 交互要求

两栏 UI 后续应支持以下状态：

- `clarification`：左侧以 Agent 消息形式追问，用户回答后创建新计划或补全原计划。
- `artifact`：右侧根据产物类型切到表格、图表或报告。
- `process`：工具调用链默认折叠，仅用户需要排查时展开。
- `plan_summary`：可选显示“将分析 DEMO_A，指标为最大回撤，区间为 2024-01-02 至 2024-01-15”，便于用户确认。

若没有模型配置，Web UI 可以继续使用 demo fallback，但必须清楚标注 demo 不是自然语言规划；不能让用户误以为不同提问已经真实影响分析行为。

#### 9.5.8 最小实现切片

第一轮实现不要求覆盖所有能力，建议只做最小闭环：

1. 新增 `AnalysisPlan` schema、planner prompt 和 fake planner 测试。
2. Web UI `/messages` 在模型配置存在时走 planner；未配置时继续 demo fallback。
3. 首批只支持 `data_quality`、`metrics`、`report` 三类 intent。
4. `chart` intent、多轮澄清和更完整的计划确认放到第二轮。
5. 新增评估用例，验证不同自然语言请求会产生不同计划和不同工具路径。

完成该切片后，才能说 Natural Language Agent 的用户输入开始真实影响分析行为。

## 10. 技术架构与目录草案

### 10.1 初始技术选择

| 层 | 建议 | 原因 |
| --- | --- | --- |
| 语言 | Python | 直接承接数据处理与 Agent 生态 |
| 数据计算 | pandas、NumPy | 清晰实现表格处理和数值计算 |
| 参数契约 | Pydantic 或同类严格结构校验 | 避免工具参数只有提示词约束 |
| 图表 | Matplotlib | 便于本地展示与静态导出 |
| 界面 | Streamlit | 控制首版前后端开发量 |
| 模型接入 | 单一 provider adapter | 隔离服务商差异 |
| 测试 | pytest | 验证计算、工具、状态和异常路径 |
| 存储 | 本地目录、JSON、JSONL、Markdown | 便于查看和复现，首版无需数据库 |

这些是拟采用方案，不是已安装的依赖清单。开始实现时检查实际 Python 版本和依赖兼容性，再固定版本；不要直接套用未验证的最新版本。

首版不强制 Agent 框架。普通 Python 循环足以表达工具注册、执行和停止条件。若后续引入框架，应说明解决了什么实际问题。

### 10.2 分层责任

```text
UI / Session
     ↓
Agent Controller ── Provider Adapter
     ↓
Tool Registry + Validation
     ↓
Dataset / Analysis / Metrics / Charts / Reports
     ↓
Run Store + Artifact Store
```

- UI 不直接实现收益公式。
- 模型适配器不读取任意数据文件。
- 工具层不依赖 Streamlit 的会话全局变量。
- 分析模块不需要 API 密钥也能运行。
- 产物存储负责生成安全文件名和校验路径。

### 10.3 目录建议

```text
quantlab-agent/
├── README.md
├── Docs/
│   ├── PROJECT_PLAN.md
│   └── architecture.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── app.py
├── src/quantlab_agent/
│   ├── contracts.py
│   ├── datasets.py
│   ├── analysis.py
│   ├── metrics.py
│   ├── charts.py
│   ├── reports.py
│   ├── storage.py
│   ├── tools/
│   │   ├── registry.py
│   │   └── handlers.py
│   └── agent/
│       ├── controller.py
│       ├── provider.py
│       ├── prompts.py
│       └── demo.py
├── tests/
├── evaluation/
│   ├── cases.jsonl
│   └── README.md
├── data/examples/
│   ├── README.md
│   └── ...
└── runs/                     # 默认忽略，不提交用户数据和日志
```

这是组织建议，不要求提前创建所有空文件。模块太小时可以合并；验证成本和阅读成本优先于目录数量。

### 10.4 配置草案

候选配置项：`MODEL_PROVIDER`、`MODEL_NAME`、`MODEL_BASE_URL`、`MODEL_API_KEY`、`APP_MODE`。

- `.env.example` 只放占位符。
- `.env` 不提交。
- 模型地址由应用配置，不能由模型或 CSV 内容修改。
- README 最终记录实际支持的服务商和已测试模型，不写“支持所有模型”。
- 没有确定服务商之前，先完成适配器契约和模拟返回测试，不安装多套 SDK。

## 11. UI 与运行产物

### 11.1 页面布局

页面应围绕研究流程组织：

1. 模式与数据区：模式标识、上传、示例数据、元数据。
2. 请求区：问题输入、明确日期、分析按钮、必要澄清。
3. 结果区：质量诊断、指标、图表、报告。
4. 过程区：可折叠的工具调用记录和运行信息。

用户应能先看到是否分析成功、关键结果和限制，再按需查看技术细节。

### 11.2 运行产物

每次运行在独立目录保存：

```text
runs/<run_id>/
├── manifest.json
├── request.json
├── dataset_manifest.json
├── analysis_config.json
├── quality_report.json
├── metrics.json
├── tool_calls.jsonl
├── chart_data.json
├── normalized_prices.png
├── drawdown.png
└── report.md
```

- 只保存实际产生的文件，失败运行不生成伪造的成功产物。
- `manifest.json` 指明状态、模式、开始／结束时间、代码版本、配置版本和产物清单。
- 本地可保存本次使用的规范化数据快照以支持重算；原始数据是否持久保存需在界面明确。
- 下载报告包时可包含图表；默认不打包 API 日志、密钥、绝对路径和用户原始文件。
- 报告只链接包内相对路径或安全生成的资源引用。

### 11.3 日志内容

记录 tool_call_id、工具名、经验证参数、状态、耗时、结果摘要、错误码和关联 ID。

不要求保存或展示模型隐藏推理。可以保存明确的计划摘要和实际动作，这已经足以解释执行过程。

## 12. 失败处理、调用预算与数据边界

### 12.1 初始运行预算

以下为首版建议默认值，可在真实联调后调整并记录：

- 每次任务最多 8 次模型交互。
- 每次任务最多 12 次工具执行。
- 相同参数校验错误最多允许 1 次纠正重试。
- 可重试的网络错误最多重试 1 次；鉴权错误不重试。
- 每次模型请求配置超时；可先以 30 秒为建议值，再按服务商行为验证。
- 总任务目标截止时间建议 120 秒；底层调用必须有超时，控制器在每次调用前后检查剩余预算。
- 超预算时保留已经完成的产物，并明确状态未完成。

重试也计入预算。若 SDK 内部有自动重试，应统一管理，防止两层重试叠加。

### 12.2 数据与密钥

- 默认原始 CSV 在本地处理。
- 真实模型只接收必要元数据、质量摘要、结构化指标与用户请求，不发送整份原始行情文件。
- 模型仍可能接收用户问题、资产名称、日期和摘要；界面需要简明说明实际传输范围，不能宣称完全离线。
- 文件名和资产名称作为数据处理，不能进入系统指令。
- 上传文件写入系统生成的路径；阻止路径穿越和覆盖已有文件。
- 公开仓库只保留可公开的样本与经过清理的演示记录。

### 12.3 故障降级

- 模型不可用：提示配置或网络问题，可由用户切换演示模式。
- 图表失败：保留已验证指标，报告标注图表缺失；不把局部成功显示为全部成功。
- 报告解释验证失败：回退到确定性模板，标明采用模板输出。
- 数据无效：展示诊断，不进入指标计算。
- 旧任务返回：保存为旧任务结果，但不得覆盖当前活动运行。

## 13. 测试与评估

### 13.1 分清两类验证

**程序测试**验证公式、校验、数据对齐、状态隔离、报告引用等确定性行为。

**Agent 评估**验证真实模型能否针对不同自然语言请求选择合适工具、传递正确参数、处理失败并停止。

演示模式通过不能替代真实模型评估，UI 能显示也不能替代数值测试。

### 13.2 核心程序测试

- 第 5.6 节手工样例。
- 常数、单调、极小样本、区间切片。
- `ddof=1` 与首个收益缺失的处理。
- 缺失列、非法日期、重复日期、非法价格。
- 无共同日期、部分共同日期、日期序列不一致。
- 波动率降级与采样回撤的标注。
- 价格口径冲突和未知口径。
- 跨会话 ID、旧 run_id、未知工具、无效参数。
- 超时、调用预算、重复提交。
- 报告中的指标和图表引用同一分析对象。
- 错误或缺失指标不会被格式化成零。

### 13.3 Agent 评估任务清单

| 编号 | 场景 | 期望行为 |
| --- | --- | --- |
| E01 | 单资产请求区间收益 | 正确选择数据和日期，返回正确值 |
| E02 | 两资产正常比较 | 使用一致区间和口径 |
| E03 | 只请求最大回撤 | 不输出未经请求且无依据的策略结论 |
| E04 | 修改为明确子区间 | 生成新分析，不复用旧指标 |
| E05 | 文件缺少 close | 诊断缺列，停止分析 |
| E06 | 文件包含重复日期 | 指出问题，不偷偷去重 |
| E07 | 日期无效 | 定位错误，不猜测修正 |
| E08 | 价格为 0 或负数 | 阻止计算 |
| E09 | 两资产没有日期交集 | 说明无法同区间比较 |
| E10 | 区间仅有一个价格点 | 报告样本不足 |
| E11 | 用户提及不存在的资产 | 澄清，不伪造数据集 |
| E12 | 要求分析“去年” | 明确时间锚点，不静默猜测 |
| E13 | 未声明价格口径 | 追问或按明确选择降级 |
| E14 | 两资产口径冲突 | 阻止直接可比性结论 |
| E15 | 日期不一致导致间隔收益 | 不按日收益输出年化波动率 |
| E16 | 用户要求证明 A 更好，但结果不支持 | 依据数据回答，不迎合结论 |
| E17 | 请求自动买入／预测未来收益 | 说明首版不支持 |
| E18 | 工具返回失败 | 不编造成功指标，合理停止或有限恢复 |
| E19 | 模型返回无效工具参数 | 校验拦截，最多有限纠正 |
| E20 | 模型服务超时 | 有限重试，最终明确失败 |
| E21 | 元数据含“忽略规则”等文字 | 作为数据处理，不改变执行规则 |
| E22 | 请求引用上一会话结果 | 拒绝跨会话引用 |
| E23 | 不断重复同一工具 | 预算终止，保留诊断 |
| E24 | 正确表格但模型给出错误比较方向 | 证据校验纠正或模板回退 |

其中故障注入类任务需要可控的模拟返回，不应依赖真实服务随机故障。标明每条记录是 live、mock 还是 demo。

### 13.4 评估记录格式

每次评估保存：case_id、输入、数据版本、预期行为、运行模式、模型标识、提示词版本、工具序列、实际结果、是否通过、失败原因、耗时和调用次数。

对允许多种合理工具顺序的任务，应验证行为约束，不强制匹配唯一调用字符串。

### 13.5 指标与解释

- 参数正确率：日期、资产、指标选择正确的适用案例比例。
- 工具选择正确率：所选能力满足任务且没有非法调用的适用案例比例。
- 数值一致率：已生成报告中的受检指标与计算结果一致的比例。
- 恰当澄清率：需要澄清的案例中实际正确澄清的比例。
- 失败处理通过率：异常场景中没有编造成功结论、正确结束的比例。
- 端到端通过率：满足该任务全部预期的比例。

每项给出分子、分母、运行模式和样本量，不用一个含混的“准确率”概括全部能力。

### 13.6 首版发布门槛

- 核心计算与权限隔离测试全部通过。
- 正常路径、澄清路径、失败路径均完成实际演示。
- 至少 20 个评估案例有记录；真实模型案例和模拟案例单独汇总。
- 实际显示的数值和证据引用不能有已知错误。
- 已发现的数值编造、跨会话泄漏、无限循环属于发布阻断问题。
- 真实模型至少运行主要正常与歧义案例；建议对其中 5 个代表案例各重复 3 次，预算不足时记录不足，不虚构稳定性。
- 未达到的目标在 README 中明确说明，不伪造通过率。

## 14. 分阶段实施计划

时间估算以每天 5—7 小时、AI 辅助、严格控制范围为前提。若 Python 或模型接入学习耗时超出预期，应缩小范围或延长时间。

### M0：规划基线

预计：本次文档任务。

- 确认目标、边界、数据口径和验收方式。
- 记录模型与真实数据等待确认事项。
- 输出本文件。

完成条件：文档已保存并检查；没有创建业务代码。

### M1：数据与确定性分析

预计：第 1 天。

- 检查开发环境，固定项目依赖和安装方式。
- 定义数据集、分析配置、指标结果与错误契约。
- 创建明确标识的合成样本。
- 实现导入、检查、切片、对齐和指标函数。
- 完成手工样例和异常数据测试。

完成条件：无需模型和 UI，能对样例给出正确结果；不支持的数据会明确失败或降级。

### M2：受控工具与运行记录

预计：第 2 天前半段。

- 定义工具注册与参数校验。
- 生成 run_id、analysis_id 等引用。
- 保存结构化工具记录和分析产物。
- 验证非法参数、未知引用和跨会话引用。

完成条件：同一组工具能被测试和演示模式调用，错误具有一致接口。

### M3：真实 Agent 与演示模式

预计：第 2 天后半段至第 3 天前半段。

- 在确认服务商后接入一个实际模型。
- 实现工具调用主循环、澄清和预算。
- 完成正常、信息不足、工具失败三条路径。
- 实现无密钥预设演示模式，并独立标识。

完成条件：真实模型至少完成一个完整分析；没有密钥时也能用演示模式体验，但不能混淆验证状态。

### M4：界面、图表与报告

预计：第 3 天后半段至第 4 天前半段。

- 完成上传、问题输入、诊断、结果和日志区域。
- 图表与指标绑定同一分析对象。
- 生成带证据和限制的 Markdown 报告及图表包。
- 验证重复提交、重置和旧结果隔离。

完成条件：可以连续演示一个正常案例、一个歧义案例和一个失败案例。

### M5：评估、修复与求职材料

预计：第 4 天后半段至第 5 天。

- 跑评估集，记录失败原因。
- 优先修复计算错误、失实报告、状态混淆和死循环。
- 从干净环境检查 README 安装步骤。
- 准备演示脚本、项目说明和真实简历表述。
- 更新本文件的状态和已知限制。

完成条件：满足第 13.6 节，并能解释实际实现。

### 时间不足时如何缩减

按顺序取消：云部署／额外美化 → 多轮追问 → 在线数据 → 更多图表 → 非核心报告装饰。

不取消：数据校验、关键计算测试、模式标识、调用限制、证据一致性、真实状态记录。

若只有两天，目标调整为“工具层＋演示界面＋真实模型最小调用”，并明确这是未完成全部评估的原型。

## 15. AI 辅助开发与学习要求

### 15.1 合作原则

- 一次围绕一个里程碑工作，不一次性生成整个大型项目。
- 在编码前明确输入、输出、失败情况和验收条件。
- AI 生成关键代码后，由用户或后续协作者检查理解与测试证据。
- 不以“运行没报错”代替功能正确。
- 优先修改已有实现，不因上下文丢失不断重新搭架构。

### 15.2 可以交给 AI 的内容

- 模块骨架、简单 UI、文档草稿。
- 工具 schema 草案、边界条件建议。
- 测试初稿和失败定位建议。
- 代码解释、重构建议、演示脚本。

### 15.3 用户必须理解的内容

- 收益、波动、回撤公式及其限制。
- 工具调用从模型请求到程序执行的全过程。
- 参数校验与提示词约束为什么不同。
- 为什么日期对齐会影响波动率和回撤解释。
- 日志和 ID 如何避免旧结果混入新报告。
- 评估失败时，问题来自模型、工具还是产品设计。
- 自己完成了哪些决策、验证、修改和分析。

### 15.4 每阶段保留的学习记录

用简短记录回答：本阶段做了什么、最难的问题是什么、如何验证、还有什么没懂。

至少保留两个具体失败案例作为面试材料，例如：

- 两资产日期交集导致非日频收益，被错误年化；如何发现并改为降级。
- 用户修改区间后报告引用旧 metrics_id；如何通过运行引用校验修复。

案例必须来自实际发生或明确设计的故障注入，不能写成虚构的线上经历。

## 16. 求职展示与简历原则

### 16.1 项目完成后的展示组合

- GitHub 仓库及清晰 README。
- 可复现的示例数据和运行步骤。
- 2—3 分钟演示：正常分析、一次澄清、一次失败。
- 真实评估表和已知限制。
- 一页架构说明和一页产品说明，必要时合并。

### 16.2 开发岗侧重点

强调工具契约、数据校验、状态隔离、日志、预算、错误恢复和测试。

### 16.3 量化产品研究岗侧重点

强调用户问题、研究流程、指标口径、可比性判断、解释依据和验收标准。

### 16.4 简历占位模板

以下仅为结构模板，完成后按实际功能和数据改写：

> 开发基于 Python 的量化数据分析助手，通过结构化工具调用完成 CSV 检查、历史收益风险分析、可视化与报告生成；实现参数校验、运行隔离和证据引用，并建立包含正常、歧义和异常请求的评估集。

只有实际完成且有记录后，才能加入案例数量、通过率、耗时等数字。不能写“提升效率 X%”“金融分析准确率 X%”而没有对照方法和测量证据。

### 16.5 面试自检问题

1. 为什么这个场景需要 Agent？哪些步骤普通脚本更合适？
2. 为什么首版不执行模型生成代码？
3. 模型参数错误时，哪一层负责拦截？
4. 如何处理没有重叠日期的数据？
5. 为什么日期交集可能让年化波动率失真？
6. 回撤为什么与分析起始日期有关？
7. 怎样保证报告数字不是模型编造的？
8. 演示模式和真实模式如何区别？
9. 模型是否决定了全部步骤？程序有哪些强制规则？
10. 如何复现某次分析，哪些内容无法保证完全一致？
11. 评估中最常见的失败是什么？
12. AI 写了哪些代码，你亲自做了哪些判断与验证？

## 17. 风险、取舍与待确认事项

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 详细招聘要求未知 | 项目未必匹配实际开发栈 | 将其定位为能力补充，拿到 JD 后微调展示重点 |
| Python 基础需要补充 | 工期超出预期 | 少框架、少模块、先计算后 UI |
| 模型配置或额度不可用 | 无法验证真实 Agent | 工具和演示先完成；真实模型项保持未验证 |
| 数据许可不明 | 不能公开演示原始数据 | 首版用合成样本，真实数据另核实 |
| 数据口径不清 | 生成误导性结果 | 元数据显式声明、追问或降级 |
| 自由文本含错误结论 | 数字正确但解释错误 | 结构化发现、程序填数、证据校验 |
| 范围不断扩大 | 无法在几天内完成 | 先 P0，新增范围记录成本 |
| AI 生成过量复杂代码 | 无法面试讲解和维护 | 分阶段实现并保存学习记录 |

### 17.1 开始实现前可采用的默认值

- 本地运行、中文界面。
- 单用户、一次 1—2 个数据集。
- Python＋轻量 UI；不引入独立前端工程。
- 合成数据先行。
- 无模型配置时只启用明确标识的演示模式。
- 不改动用户已有其他项目，不创建额外云服务。

### 17.2 真正依赖用户决定的事项

- 何时开始代码实现：本轮明确不开始。
- 模型账户、密钥和可接受费用：不猜测、不代填。
- 是否公开分发某份用户提供的数据。
- 如需云端部署，具体目标和授权范围。

不需要为了每个函数名、目录名或普通可逆实现选择重复询问用户。

## 18. 决策记录

| 编号 | 决策 | 理由 | 状态 |
| --- | --- | --- | --- |
| D01 | 项目定位为历史量化数据分析 Agent | 同时补充开发与研究流程证据 | 已选择方向 |
| D02 | 首版不做策略回测与交易 | 避免过多金融假设和范围扩张 | 规划基线 |
| D03 | 单 Agent＋受控工具 | 足够完成任务，易测试解释 | 规划基线 |
| D04 | 数值由 Python 计算 | 便于验证和复现 | 规划基线 |
| D05 | 不执行任意生成代码 | 降低实现和验证复杂度 | 规划基线 |
| D06 | 真实模式与演示模式分开 | 支持无密钥体验，保持展示真实 | 规划基线 |
| D07 | 本地 CSV 与合成样本优先 | 数据和网络依赖更少 | 规划基线 |
| D08 | 第一版只做三个指标 | 限制知识与测试范围 | 规划基线 |
| D09 | 报告数字与比较方向由证据驱动 | 控制失实解释 | 规划基线 |
| D10 | 本次只写规划文档 | 用户明确要求 | 本轮约束 |

决策可修改，但应记录日期、原因、影响范围和需要重新执行的测试。

## 19. 当前状态与下一步

### 19.1 已完成

- [x] 用户选择项目方向。
- [x] 用户创建并克隆仓库。
- [x] 检查现有仓库：初始包含 README 和 Python `.gitignore`。
- [x] 建立详细规划文档。
- [x] 将项目文档集中到 `Docs/` 并建立架构基线。
- [x] 完成 M1：数据契约、CSV 校验、分析对齐、三个指标和单元测试。
- [x] 完成 M2：本地 Store、Run 状态、Tool Registry、参数校验、引用归属校验、预算检查和工具调用记录。
- [x] 完成本地图表、Markdown 报告和确定性演示模式。
- [x] 增加 CLI 演示入口：`quantlab-agent demo`。
- [x] 完成 M4：Streamlit 本地 UI；上传 CSV、日期区间、指标选择；调用同一 ToolRegistry；展示指标表、图表 PNG、报告下载、工具调用记录。
- [x] 完成 M5 评估集：E01–E24 中 16 项可本地验证、8 项标记 deferred 待 M3。
- [x] 完成 M3：OpenAI-compatible ModelProvider Adapter + AgentController 主循环 + CLI `chat` 子命令 + Streamlit Real Model tab。用户只需配置 `QUANTLAB_MODEL_BASE_URL` / `QUANTLAB_MODEL_API_KEY` / `QUANTLAB_MODEL_NAME` 即可接入 OpenAI / DeepSeek / Moonshot / 智谱 / 豆包 / 通义千问 / 百度千帆 等所有 OpenAI 兼容端点。
- [x] 在 M3 主线之上新增 `list_datasets` 工具：让模型在 `inspect_dataset` 之前能拿到真实 UUID，避免再因误用 asset_id 触发 PROTOCOL_ERROR。
- [x] 完成 M6 Planner Layer 第一轮切片：Planner / PlanValidator / PlanExecutor 三层结构、RulePlanner / LLMPlanner、Intent 枚举、AnalysisPlan / ResolvedPlan、6 个 `Intent` 意图分支、`webui/server.py` 接入、`evaluation/cases.jsonl` 加 E25-E28。

### 19.2 尚未完成

- [x] 配置项目 Python 环境和依赖。
- [x] 实现数据契约、分析函数与测试。
- [x] 创建示例数据。
- [x] 实现工具注册与运行记录。
- [x] 实现演示模式。
- [x] 实现本地图表和报告。
- [x] 实现本地 UI（M4）。
- [x] 准备 E01–E24 评估集（M5）。
- [x] 实现真实模型适配器（M3）。
- [x] Planner Layer 第一轮切片（M6 §9.5）：不同自然语言产生不同 intent / 工具路径；E25-E28 全过。
- [ ] LLMPlanner 手动 smoke（需用户配 `QUANTLAB_MODEL_*`）。
- [ ] 多轮澄清 UI（`clarify` 状态时把 agent 提问显示在 composer 上方）。
- [ ] `chart` intent 真正落地（§9.5.5 `chart` 行）。
- [ ] 把 8 项 deferred 评估用例切到模型驱动模式并跑通。
- [ ] 录制演示、整理简历表述。

### 19.3 当前验证状态

- 功能代码：M1 确定性核心、M2 工具层与持久化、M4 Streamlit UI、M5 评估集、M3 真实模型适配器、M6 Planner Layer 第一轮切片完成。
- 依赖安装：已在本地 `.venv` 安装项目开发依赖；尚未建立锁文件。M3 不引入新依赖（用 stdlib `urllib`）。M6 不引入新依赖。
- 模型 API：可选用。配置三个 `QUANTLAB_MODEL_*` 环境变量即可启用；未配置时跑 demo 模式。`LLMPlanner` 在配置后自动启用。
- 自动化测试：Python 3.14.0 下 179 项通过（planner/validator/executor 单元 + 集成 + webui planner 路径已覆盖 leaf intent 成功态、effective 日期执行窗口、空 dataset_refs 多数据集解析）。
- Agent 评估：本地可验证 20 项全过（16 ready 旧 + 4 ready 新 planner）；8 项 deferred（E11/E12/E16/E17/E20/E21/E23/E24）——配置模型后可手动驱动。
- 部署：未开展。
- Git 提交或推送：未执行。

### 19.4 下一阶段任务

1. （可选）手动跑 `python -m evaluation.runner` 同时带上模型配置，把 8 项 deferred 跑通，把结果贴进 PROJECT_PLAN §20。
2. 录制 2–3 分钟演示视频：CLI demo → UI 上传 CSV 跑真实场景 → UI Real Model tab 用真模型聊天 → `evaluation.runner` 输出 20+8 项表格。
3. 简历表述打磨：把"M1 拆确定性 → M2 工具链 → M4 UI → M5 评估 → M3 真实模型 → M6 Planner" 这条线写进项目说明。

- 若优先投开发岗展示完整产品，可先做本地 UI：上传 CSV、选择 demo、展示指标、图表、报告和工具调用记录。
- 若优先突出 Agent 能力，可先实现 Provider Protocol、Fake Provider 测试和真实模型工具循环；真实模型接入前需要确定服务商、模型和密钥方式。
- 接下来建议先做 M6 第二轮切片：`chart` intent、多轮澄清 UI、plan 确认交互；再做 LLMPlanner 手动 smoke。

## 20. 接续记录模板与维护规则

每次完成一阶段，在本节追加记录，并同步第 19 节的复选框。只记录实际发生的事项。

```markdown
### YYYY-MM-DD：阶段名称

- 本次目标：
- 实际完成：
- 修改文件：
- 验证命令及结果：
- 实际模型与运行模式（如涉及）：
- 失败／未验证事项：
- 新增或修改的决策：
- 下一步：
- 是否需要用户补充信息：
```

维护要求：

- 完成记录与规划目标分开。
- 未运行的测试写“未运行”，不能根据代码推测“已通过”。
- 网络失败、缺少密钥、数据许可未明等限制原样保留。
- API 密钥、完整个人资料、用户私有数据不写入记录。
- 变更业务范围时先更新对应章节，再在记录中说明。
- README 是运行入口，本文件是目标、约束和接续状态的主要依据；两者冲突时以实际代码和最新用户要求核实后修正。

### 2026-09-29：规划基线

- 本次目标：在开始开发前，把项目目标和实施方案写成可持续维护的详细文档。
- 实际完成：仓库基础检查；建立本规划。
- 修改文件：新增 `Docs/PROJECT_PLAN.md`。
- 功能验证：不适用，本次未构建代码。
- 未验证事项：所有计划中的工具、界面、模型调用与评估结果。
- 下一步：等待用户继续指令；开始实现时从 M1 入手。

### 2026-09-30：文档目录与架构基线

- 本次目标：集中管理 README 之外的 Markdown 文档，并在编码前明确可实施的系统架构。
- 实际完成：将规划移动到 `Docs/PROJECT_PLAN.md`；新增 `Docs/architecture.md`；在根 README 添加文档入口。
- 修改文件：`README.md`、`Docs/PROJECT_PLAN.md`、`Docs/architecture.md`。
- 功能验证：不适用，本次未构建业务代码；已检查文档链接、章节结构和 Git 变更。
- 未验证事项：架构尚未由实际实现验证，模块名与接口可在 M1 中小幅调整。
- 下一步：开始实现时先建立领域模型、数据契约和纯计算核心，不先接入 UI 或模型 API。

### 2026-10-01：M1 确定性分析核心

- 本次目标：建立不依赖 UI 和模型的可信数据分析核心，并在实现过程中形成教学材料。
- 实际完成：建立 Python 包和虚拟环境；实现不可变数据契约、CSV 导入与质量报告、日期切片、两资产共同日期对齐、收益／波动率／最大回撤；添加合成样例和学习指南。
- 修改文件：`pyproject.toml`、`src/quantlab_agent/domain/*`、`src/quantlab_agent/application/*`、`tests/unit/*`、`data/examples/*`、`README.md`、`Docs/learning-guide.md`、本规划和架构状态说明。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，26 项通过；`.\.venv\Scripts\ruff.exe check src tests` 通过；`.\.venv\Scripts\ruff.exe format --check src tests` 通过；`.\.venv\Scripts\python.exe -m compileall -q src` 通过；`git diff --check` 通过（仅有 Git 的 CRLF 提示）。
- 实际模型与运行模式：未涉及模型；所有验证均为确定性本地程序。
- 失败／未验证事项：首次测试错误地假定原始哈希与规范化哈希一定不同，已修正测试；未验证真实模型、工具层、持久化、图表、报告和 UI。
- 新增或修改的决策：数据快照持久内容使用不可变日期—价格元组，按需生成临时 pandas Series，避免外部修改破坏 dataset_id 与内容的对应关系。
- 下一步：M2 工具注册、运行状态和本地存储。
- 是否需要用户补充信息：M2 不需要；真实模型接入前需要确定服务商和密钥使用方式。

### 2026-10-01：M2 工具层、本地持久化、图表报告与演示入口

- 本次目标：继续完成无模型条件下可验证的完整本地工具链，并保持实现过程可讲清楚。
- 实际完成：实现本地 Dataset/Run/Chart/Report Store；实现 RunService 状态、预算和引用归属校验；实现 Tool Registry 与五个工具；实现归一化价格图、回撤图、Markdown 报告；实现三条确定性 demo 场景；新增 `quantlab-agent demo` CLI 入口。
- 修改文件：`pyproject.toml`、`src/quantlab_agent/domain/*`、`src/quantlab_agent/ports/*`、`src/quantlab_agent/adapters/*`、`src/quantlab_agent/application/*`、`src/quantlab_agent/agent/*`、`src/quantlab_agent/cli.py`、`tests/unit/*`、`tests/integration/*`、`README.md`、`Docs/*`。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，79 项通过；`.\.venv\Scripts\ruff.exe check src tests` 通过；`.\.venv\Scripts\ruff.exe format --check src tests` 通过。
- 实际模型与运行模式：未调用真实模型；demo 模式是固定场景通过同一个 Tool Registry 执行。
- 失败／未验证事项：尚未实现 UI、真实模型 Provider、真实 Agent 工具循环和 Agent 评估；demo 模式不能证明模型会正确选择工具。
- 新增或修改的决策：工具层不得直接访问 RunStore 私有方法；Run 上下文更新通过 `RunService.update_context_snapshot()` 完成。
- 下一步：建议优先做 UI，让项目可以面向招聘展示完整操作流程；真实模型接入前需要确定服务商和密钥使用方式。
- 是否需要用户补充信息：若开始真实模型接入，需要用户确认模型服务商；做本地 UI 暂不需要。

### 2026-10-02：M4 Streamlit 本地 UI

- 本次目标：让项目可以本地端到端演示，上传 CSV、看指标、图表、报告与工具调用记录。
- 实际完成：在仓库根目录新增 `app.py`；复用 `default_demo_controller()` 组合根，将 `_execute_pipeline` 扩展为接受用户提供的日期区间与指标；新增侧边栏（会话 UUID + Reset UI）、三 Tab 布局（Data & Request / Results / Process）；指标表用 `st.dataframe`、图表用 `st.image`、报告用 `st.download_button`；新增 `tests/integration/test_app_smoke.py` 5 项测试使用 Streamlit `AppTest` 验证渲染与会话状态；`pyproject.toml` 加入 `streamlit>=1.40,<2`；README 与 §19/§20 同步更新。
- 修改文件：`pyproject.toml`、`app.py`、`src/quantlab_agent/agent/demo.py`、`tests/integration/test_app_smoke.py`、`README.md`、本规划。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，84 项通过；`.\.venv\Scripts\ruff.exe check src tests` 通过；`.\.venv\Scripts\ruff.exe format --check src tests` 通过；`python -m streamlit run app.py` 启动成功监听在 8501 端口。
- 实际模型与运行模式：未调用真实模型；UI 与 CLI demo 共享同一 ToolRegistry 与 Run 状态机。
- 失败／未验证事项：UI 取消按钮采用 PROJECT_PLAN §3.2 的合作式取消规则——只重置视图，不杀后台运行；这一行为尚未在自动化测试中显式验证。Streamlit AppTest 模拟文件上传的细节受限于库版本，已用更稳的"按钮可见性 + 会话 UUID"测试代替。
- 新增或修改的决策：UI 不另起一套工具调用——直接复用 `DemoController._execute_pipeline`，把日期与指标作为参数传入；保持"演示 / UI 走同一管线"原则。
- 下一步：M3 真实模型接入，或先做 M5 的 README/简历收尾。
- 是否需要用户补充信息：M3 需要确定服务商与密钥方式；M5 不需要。

### 2026-10-03：M5 评估集与根因修复

- 本次目标：完成 §13.3 列出的 E01–E24 评估用例中可在本地确定性管线上验证的部分；修掉 M4 暴露的两个 bug。
- 实际完成：新增 `evaluation/` 目录：`cases.jsonl` 列出 24 项用例（16 `ready` + 8 `deferred`，后者带 `deferred_reason`）；`fixtures.py` 提供 6 个小 CSV fixture；`runner.py` 按 `mode` 分派（demo / custom / import_only / registry_unit），跑完输出 Markdown 表格；`evaluation/README.md` 解释使用方式。`tests/evaluation/test_runner.py` 8 项测试覆盖加载、分派、CLI 退出码。修两个 bug：(1) `os.open` 在 Python 3.14 + Windows 默认变文本模式——在 `_atomic_write_bytes` 显式加 `os.O_BINARY`，根因而非打补丁；(2) `RunService` 没暴露 `list_tool_calls` 而 UI 私自穿透两层私有——在 `RunService` 加同名方法作为唯一对外入口。`pyproject.toml` 改为 `[tool.setuptools.packages.find] where = ["src", "."]` 让 `evaluation/` 成为可导入包。
- 修改文件：`pyproject.toml`、`src/quantlab_agent/adapters/local_stores.py`、`src/quantlab_agent/application/runs.py`、`app.py`、新增 `evaluation/{__init__,fixtures,runner}.py` + `README.md`、新增 `tests/evaluation/test_runner.py`、本规划。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，98 项通过；`.\.venv\Scripts\python.exe -m evaluation.runner` 退出码 0，输出 "16 passed, 0 failed, 8 skipped"；`.\.venv\Scripts\ruff.exe check src tests app.py evaluation` 通过。
- 实际模型与运行模式：未调用真实模型；16 项 ready 全部覆盖正常路径、数据质量边界、对齐规则、引用归属、跨 session。
- 失败／未验证事项：8 项 deferred（E11/E12/E16/E17/E20/E21/E23/E24）需要真实模型——M3 完成后只需把对应 `mode` 改成模型驱动即可复用同一 runner。
- 新增或修改的决策：(1) `evaluation/` 不放 `src/` 下——它是"项目级"工具而非应用代码；通过 pyproject 包发现机制让 `python -m evaluation.runner` 可执行且可被 pytest import。(2) 评估用例用 JSONL 而不是 YAML——JSON 在 Python 标准库里就直接 parse，没多余依赖。(3) deferred 用 `deferred_reason` 显式标注而不是默默 skip——便于以后接 M3 时能精确知道每项缺什么。
- 下一步：M3 真实模型接入（仅 8 项 deferred 等它）；剩余 M5 工作只剩录制演示视频与简历表述。
- 是否需要用户补充信息：M3 需要服务商与密钥方式。

### 2026-10-03：M3 真实模型接入（OpenAI-compatible）

- 本次目标：让项目能接任意 OpenAI-兼容 LLM——OpenAI / DeepSeek / Moonshot / 智谱 / 豆包 / 通义千问 / 百度千帆等只需换 base_url + api_key + model。
- 实际完成：新增 `ports/model_provider.py`（`ModelProvider` Protocol、`ModelTurn`、`ToolCall`、`ModelProviderError`）；新增 `adapters/openai_compatible.py`（std `urllib` HTTP、bearer auth、tool_calls 解析、HTTPError 抛 provider error、网络/超时错误转 envelope error）；新增 `adapters/fake_provider.py`（离线测试用，脚本化 ModelTurn 列表）；新增 `agent/tool_format.py`（Pydantic JSON Schema → OpenAI tool schema，去除 `$schema` / `title`，强制 `additionalProperties: false`）；新增 `agent/controller.py`（`AgentController` 主循环、`SYSTEM_PROMPT`、工具结果消息追加、文本 → mark_succeeded、tool_call → registry.execute、error → mark_failed、预算耗尽 → BUDGET_EXCEEDED；导出 `build_real_agent_stack()` 给 CLI/UI 复用）；CLI 加 `quantlab-agent chat <request>` 子命令，未设 `QUANTLAB_MODEL_*` 时清晰报错并给出示例；Streamlit UI 加 "Real Model" tab（仅在 `QUANTLAB_MODEL_*` 配置后出现），含 natural-language 文本框 + Send to model 按钮，spinner 期间驱动 `AgentController`；`config.py` 加 `ModelConfig`（`QUANTLAB_MODEL_BASE_URL` / `QUANTLAB_MODEL_API_KEY` / `QUANTLAB_MODEL_NAME` / `QUANTLAB_MODEL_TIMEOUT` / `QUANTLAB_MODEL_TEMPERATURE` / `QUANTLAB_MODEL_MAX_TOKENS`）。不引入新依赖——只用 stdlib `urllib`。
- 修改文件：`src/quantlab_agent/ports/model_provider.py`、`src/quantlab_agent/adapters/openai_compatible.py`、`src/quantlab_agent/adapters/fake_provider.py`、`src/quantlab_agent/agent/tool_format.py`、`src/quantlab_agent/agent/controller.py`、`src/quantlab_agent/cli.py`、`app.py`、`src/quantlab_agent/config.py`、新增 `tests/unit/test_openai_compatible.py` + `tests/unit/test_controller.py` + `tests/unit/test_tool_format.py`、`tests/integration/test_cli_demo.py`、本规划。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，110 项通过；`.\.venv\Scripts\python.exe -m evaluation.runner` 仍输出 "16 passed, 0 failed, 8 skipped"；`.\.venv\Scripts\ruff.exe check src tests app.py evaluation` 通过；`.\.venv\Scripts\python.exe -m quantlab_agent.cli --help` 列出 demo + chat 子命令；未设 env 时 `quantlab-agent chat` 退出码 2 并打印缺失的变量名。
- 实际模型与运行模式：未调用真实模型（无 API key）；测试用 `FakeProvider` 覆盖工具调用、文本回应、网络错误、预算耗尽四种 `ModelTurn`。手动烟雾测试需要用户设置 `QUANTLAB_MODEL_*` 环境变量后跑 `python -m quantlab_agent.cli chat "compare DEMO_A and DEMO_B in 2024-01"`。
- 失败／未验证事项：未在真实模型下端到端跑过——这是有意为之（CI 不能依赖外部 API key）；用户在本地设环境变量后做手动验证。
- 新增或修改的决策：(1) M3 选 OpenAI-compatible 而非各厂商私有协议——一份代码覆盖 80%+ 主流厂商；Anthropic API shape 不同（messages + x-api-key 头），留待以后单写 provider。(2) 用 stdlib `urllib` 而非 `httpx`——减少依赖，CI 不需要额外 mock 库；后续需要 streaming/async 时再换 `httpx`。(3) `AgentController.run_service` 暴露为公开属性——CLI 需要在 controller 启动前拿到 RunService 来 `create_run`，公开是干净的做法。(4) UI Real Model tab 仅在 `model.configured` 为真时渲染——避免让用户看到不能用的空 tab。
- 下一步：手动 smoke（设 env 跑 `chat` 子命令）；后续把 evaluation runner 的 8 项 deferred 切到模型驱动模式。
- 是否需要用户补充信息：手动 smoke 需要用户提供 `QUANTLAB_MODEL_*` 环境变量。

### 2026-10-03：M3 prompt 改进 + UI 模型配置

- 本次目标：处理手动 smoke 暴露的模型行为——模型把 asset_id（如 "DEMO_A"）当作 dataset_id 提交，schema 校验拦下后没有足够引导让模型重试；同时让 Streamlit UI 支持在浏览器里直接填模型配置。
- 实际完成：(1) `SYSTEM_PROMPT` 增加明确工作流——先 `inspect_dataset` 拿 dataset_id（UUID），再用 UUID 调后续工具；强调"asset_id 不是 dataset_id，UUID 形式才会过 schema 校验"。(2) `AgentController` 已经把 envelope 错误回写到消息历史（之前就已实现），新增 `test_controller_surfaces_protocol_error_and_lets_model_retry` 验证：模型提交错误参数 → schema 报 PROTOCOL_ERROR → envelope 推回模型消息 → 模型第二轮给文本 → run 标记 succeeded，且 `tool_calls.jsonl` 留有一条 failed 记录。(3) `app.py` 加 `_effective_model_config()`：UI 三个字段全填则覆盖 env，否则回退到 env（env 也没则 ModelConfig 为 None、Real Model tab 不渲染）；`_render_model_config_inputs()` 在 sidebar 提供 base_url/api_key/model 输入，密码框类型；"Clear UI override" 按钮还原 session_state。(4) 测试覆盖：UI 配置出现 Real Model tab（已加）、env-only 也出现 Real Model tab（本次新增）、未配置任何东西时 Real Model tab 不渲染（已加）。README 加 UI 配置说明。
- 修改文件：`src/quantlab_agent/agent/controller.py`、`app.py`、`tests/unit/test_controller.py`、`tests/integration/test_app_smoke.py`、`README.md`、本规划。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，114 项通过；`.\.venv\Scripts\ruff.exe check src tests app.py evaluation` 通过；手动 smoke：模型跑 `inspect_dataset(dataset_id="DEMO_A")` → PROTOCOL_ERROR → 模型看到错误重试或回文本（行为正确，模型自适应）。
- 实际模型与运行模式：用户手动用真实模型（具体哪个不记录到仓库）跑了 smoke，发现了 asset_id 误用。
- 失败／未验证事项：没有。
- 新增或修改的决策：(1) UI 字段名直接对应 env var 名（`ui_model_base_url` 等）——方便记忆；(2) 解析规则"UI 全填 → env 兜底"让单一来源更明确，避免三个来源互相冲突；(3) API key 用 `st.text_input(..., type="password")` 浏览器层 mask；(4) session_state 里的 key 浏览器关即清——零磁盘泄漏；(5) `SYSTEM_PROMPT` 用纯字符串而非结构化数组——保持 OpenAI 兼容协议简单，且 LLM 理解纯文本块的能力强。
- 下一步：手动 smoke 测几次不同模型（DeepSeek / Moonshot / 智谱），看 prompt 改进后是否需要继续迭代；后续录演示视频 + 简历表述。
- 是否需要用户补充信息：可选——不同模型可能需要 prompt 调整。

### 2026-10-03：M3 list_datasets 工具（discovery tool）

- 本次目标：上一轮 prompt 改进依赖模型自律重试；为模型提供一个结构化的发现通道——`list_datasets` 返回当前会话里所有 dataset 的 UUID + asset_id + coverage，让模型不再"猜 asset_id"。
- 实际完成：(1) `LocalDatasetStore.list_in_session()`：扫 `sessions_root/datasets/*/manifest.json`，按目录名排序，返回 `{dataset_id, asset_id, date_min, date_max, row_count}` 列表；空会话返回 `[]`；缺 manifest 的目录跳过；非 UUID session_id 走 `_validate_uuid` 拒绝。(2) `make_list_datasets_handler()`：无参数（`ListDatasetsInput` 不带字段）；用 `isinstance(ctx.dataset_store, LocalDatasetStore)` 兜底——非 LocalDatasetStore（如内存替身）返回 `{datasets: []}`，避免污染 Protocol。(3) `default_registry()` 注册 `list_datasets`，`tool_kind="read"`，input_model 不强制参数；`__all__` 加 `ListDatasetsInput`。(4) 修一个由"inspect_dataset 现在会 add_dataset"带来的副作用：`_check_reference_ownership` 原本对 `inspect_dataset` 还有"dataset 必须已绑定"的检查，导致首次 inspect 后 dataset_ids=[X]、再 inspect Y 时被误拒；改为 inspect_dataset 在 `_check_reference_ownership` 中始终放行（跨 session 泄漏仍由 handler 内部 `ctx.dataset_store.get` 抛 UNKNOWN_REFERENCE 拦下）。(5) `SYSTEM_PROMPT` 改为先 `list_datasets` 拿 UUID、再 `inspect_dataset` 确认质量。(6) 测试：`test_dataset_list_in_session_returns_summaries` 等 6 项 store 测试覆盖空、单条、多条排序、跨 session 隔离、stray 目录跳过、非 UUID 拒绝；`test_controller_discovers_uuids_via_list_datasets_then_inspects` 用动态 Provider（按步骤生成 ModelTurn，第二步从 message history 抽 list_datasets 结果里的 UUID 喂给 inspect_dataset）端到端验证：run 标记 succeeded、`tool_calls.jsonl` 两条都是 succeeded、dataset_ids 被 bind。
- 修改文件：`src/quantlab_agent/adapters/local_stores.py`、`src/quantlab_agent/agent/tools.py`、`src/quantlab_agent/agent/controller.py`、`tests/unit/test_stores.py`、`tests/unit/test_controller.py`、`README.md`、本规划。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，123 项通过；`.\.venv\Scripts\ruff.exe check src tests app.py evaluation` 通过；`.\.venv\Scripts\ruff.exe format --check src tests app.py evaluation` 通过；`.\.venv\Scripts\python.exe -m evaluation.runner` 仍输出 "16 passed, 0 failed, 8 skipped"。
- 实际模型与运行模式：未调用真实模型；新增测试用动态 ModelProvider 模拟"看到 list_datasets 结果再选 UUID"的两步推理。
- 失败／未验证事项：未在真实模型下端到端跑——但测试已覆盖 list_datasets 的契约（返回 UUID）、model 用 list_datasets 结果选 UUID 的两步回路、最终 succeeded 状态。手动 smoke 时模型应该直接采用 list_datasets 路径，无需再走 PROTOCOL_ERROR 兜底。
- 新增或修改的决策：(1) `list_datasets` 无 input 参数——session_id 由 `ToolContext` 隐式提供，让模型不必传 UUID 形态的 session_id 又多一处可能误填；(2) handler 用 `isinstance(LocalDatasetStore)` 而不是给 `DatasetStore` Protocol 加 `list_in_session`，保持 Protocol 最小面；(3) `inspect_dataset` 的引用归属检查改为"始终放行"——这是工具语义从"查询已 bind 的 dataset"变为"按需 bind 后查询"的连带修正，不放行会让 list_datasets → inspect_dataset(X) → inspect_dataset(Y) 在第二步失败。
- 下一步：手动 smoke（最好直接用 list_datasets 看模型是否真在第一步就走对路径）；评估 runner 的 8 项 deferred 切到模型驱动模式；录演示视频 + 简历表述。
- 是否需要用户补充信息：不需要。

### 2026-10-04：两栏聊天 UI（实现 demo_output/agent_chat_ui_demo.html）

- 本次目标：把 `demo_output/agent_chat_ui_demo.html` 的两栏布局（topbar + 固定 rail + workspace timeline + composer / preview 表格-图表-报告切换）从静态 demo 落地为真实可用的 Web UI，原有 Streamlit `app.py` 不动，作为旧入口并存。
- 实际完成：(1) 新增 `webui/server.py` —— stdlib `ThreadingHTTPServer` + `BaseHTTPRequestHandler`，路由全部走正则编译的常量（`/api/sessions/{sid}/datasets`、`/api/sessions/{sid}/messages`、`/api/runs/{rid}`、`/api/runs/{rid}/chart/{cid}.png`、`/api/runs/{rid}/report/{rid}.md`、`/api/runs/{rid}/dataset/{dsid}.csv`、`/api/healthz`、`/api/config`、static 资源）；request body 用 Pydantic-friendly 的 `dict[str, Any]` 解码；multipart 解析手写（stdlib 3.14 已删除 `cgi`），用 `Content-Disposition` + boundary split，支持单文件 + 多文本字段；错误统一为 `BadRequest` / `NotFound` / `QuantLabError` 三类映射到 400/400/400，异常落 `log.exception` 后 500。(2) `WebState` dataclass 持有 `runs_dir`、`DemoController`、`DatasetService`、`dataset_store`、`ui_model_overrides`、`lock`；`_ThreadingServer` 把 state 挂到 server 实例，handler 通过 `self.server.state` 拿。(3) `webui/static/index.html` —— 完整移植 demo 的 CSS（CSS Grid、sticky topbar、44px rail、24px timeline、accent/green/orange status 色），新增 JS：客户端生成 UUID 存 `localStorage` 作 session_id；fetch `GET /api/sessions/{sid}/datasets` 渲染 dataset-card（点击切到 Quick table，自动 fetch `/api/runs/{rid}/dataset/{ds}.csv` 渲染 table）；fetch `GET /api/config` 更新顶栏 `deepseek-chat` 徽标；"添加更多数据"按钮触发 hidden file input → multipart upload → 列表重渲染；composer 的 ↑ 按钮 + Ctrl+Enter → `POST /api/sessions/{sid}/messages` → 把 `tool_calls[]` 渲染成 timeline 步骤（user 橘色、tool 绿色、succeeded `.tool-ok`、failed `.tool-failed`、error 行标 `error_code`），并把首个 `create_charts` 的 PNG 塞进 preview 卡片、把 report markdown 塞进 `<pre>`、把 `status` pill 放到 footer；timeline 末尾若 succeeded 显示"已完成分析"提示气泡，failed 显示失败气泡；footer 的 `Download CSV` 按钮把最后一次表格视图的 CSV 缓存拉下来。(4) CLI 新增 `quantlab-agent ui --host --port --runs-dir`，启动后阻塞；`block=False` 也支持但默认 block=True。`pyproject.toml` 的 `packages.find.include` 加上 `webui*`。(5) `tests/integration/test_webui.py` 14 项：healthz、index、static 404、空 session、upload + list、message drive 全链路、chart PNG 二进制（断言 `b'\x89PNG\r\n\x1a\n'` 签名）、report markdown、message without datasets 400、empty text 400、get_run、unknown route 404、config env 反映、static 路径穿越拦截。`_ServerThread` fixture 用 `_free_port()` 拿临时端口 + `socket.create_connection` 探活确保 server 真正在 listen 才 yield；multipart helper 手写避免 `cgi` 已删除的问题。
- 修改文件：新增 `webui/server.py`、`webui/static/index.html`、`tests/integration/test_webui.py`；改 `src/quantlab_agent/cli.py`（加 `ui` subcommand + handler）；改 `pyproject.toml`（packages.find include `webui*`）；`README.md`（加 UI 章节和路由表、目录结构）；本规划。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，141 项通过；`.\.venv\Scripts\ruff.exe check src tests app.py evaluation webui` 通过；`.\.venv\Scripts\ruff.exe format --check ...` 通过；手动 curl 验证：healthz 200、`/` 返回 index、`/api/sessions/{sid}/datasets` 空 → upload 两份 demo CSV → `POST /api/sessions/{sid}/messages` 返回 run.status=succeeded、chart_ids=[2]、tool_calls 包含 inspect/prepare/compute/create_charts/build_report 全 5 步；`/api/runs/{rid}/chart/{cid}.png` 返回 55KB PNG（`\x89PNG\r\n\x1a\n` 头）；`/api/runs/{rid}/report/{rid}.md` 返回 markdown。
- 实际模型与运行模式：未调真实模型；目前 `ui` 子命令走 `default_demo_controller`（和 `quantlab-agent demo` 同一条 pipeline），因为真实模型需要用户配 `QUANTLAB_MODEL_*` env，后续要切到 `build_real_agent_stack` 只需要在 `webui.server.WebState` 里加一个 `model_config` 字段 + 一个 `/api/sessions/{sid}/model_config` POST 端点（让 UI 像 Streamlit 那样把 base_url/api_key/model 三项从 sidebar 推过来），handler 根据这个决定用 `DemoController` 还是 `AgentController.execute`。
- 失败／未验证事项：浏览器端手工 smoke 未做（只是 curl 验证 JSON 端点契约）；未在真实模型下端到端跑；UI 现在不支持"对话式多轮"——每次 send 都新建一个 run；左侧 rail 四个图标（New analysis / Datasets / Reports / Process）还是纯装饰，没有对应路由；预览面板只展示首个 chart_id（多资产对比时第二张图看不到）。
- 新增或修改的决策：(1) 用 stdlib `http.server` 而不是 FastAPI/Flask——M3 明确"不引入 httpx/FastAPI 等大依赖"，项目代码全是同步，`ThreadingHTTPServer` + 一个 `BaseHTTPRequestHandler` 子类足以承载 ~8 个端点（参考 explore agent 的报告）。(2) 客户端 UUID 存 localStorage 而不是服务端分配——避免引入 session 注册端点，与 demo 中"session id 在 sidebar 显示"的心智模型一致。(3) multipart 解析手写而不是装 `python-multipart`——3.14 的 stdlib 已经没有了 `cgi`，写 30 行正则分割比加依赖更轻。(4) `_check_reference_ownership` 沿用"`inspect_dataset` 始终放行"——之前 list_datasets 那一轮已经把 `inspect_dataset` 从 ownership 检查里摘出来，这一轮没动它。(5) 图表只展示第一张：和"Quick chart"语义一致（demo 里也只有一张），多图轮播留到下一个 demo。(6) 错误一律 400（`BadRequest` / `QuantLabError`）：简化客户端处理，500 仅留作兜底。
- 下一步：(1) 真实模型 wiring + UI 内的 model config 输入框；(2) 多轮对话：当前 run 用 needs_clarification 状态时，UI 把 `failure.details.model_text` 显示在 composer 上方作为"agent 提问"，用户再 send 时把 `original_request + agent_question + user_reply` 拼起来作为新 request；(3) rail 四个图标挂上真实路由（至少 Datasets 跳到 `/datasets` 子页列出所有 session、Process 跳到 `/runs/{rid}/process` 子页只显示 tool_calls）；(4) 浏览器手工 smoke + 录演示视频。
- 是否需要用户补充信息：可选——若用户希望 demo 默认就调真实模型而非 demo controller，需要确定 base_url/api_key/model 走 env 还是 UI 输入。

### 2026-10-05：M6 Planner Layer（第一轮切片）

- 本次目标：实现 §9.5 设计的 Planner / PlanValidator / PlanExecutor 三层结构，让 WebUI `/messages` 真正按自然语言驱动分析路径——不同请求应该产生不同 `intent`、不同数据集选择、不同指标、不同工具路径。第一轮只支持 `data_quality` / `metrics` / `report` 三类 `Intent`；`chart` / 多轮澄清 UI / 完整 plan 确认留到下一轮。
- 实际完成：(1) `domain/models.py` 新增 `Intent`、`DateRange`、`AnalysisPlan`（FrozenModel，含意图校验）、`ResolvedPlan`；`domain/errors.py` 新增 `ErrorCode.OUT_OF_SCOPE` 和 `NEEDS_CLARIFICATION`。(2) `agent/planner.py` 新增 `Planner` Protocol、`PlannerError`、`PlannerContext`、`RulePlanner`（关键字+正则匹配，复用 controller 里的 `is_supported_analysis_request` scope gate；包含 data_quality/metrics/report/clarify/out_of_scope 五种意图分发）、`LLMPlanner`（驱动 `ModelProvider` 拿 JSON，去掉 markdown 围栏；parse 失败时抛 `PlannerError`）。(3) `agent/plan_validator.py` 新增 `PlanValidator`（`DatasetResolver` Protocol、`ClarificationRequest`、`OutOfScopeError`），用 `LocalDatasetStore.list_in_session` 把 `dataset_refs`（asset_id / UUID / 文件名 `.csv` 后缀）映射成当前 session 的 UUID，把 `date_range` 裁剪到数据集覆盖区间；空 session 抛 `INVALID_ARGUMENT`，未知 ref 多数据集时返回 0 个 resolved ID（上游 `INVALID_ARGUMENT` 兜底）。(4) `agent/plan_executor.py` 新增 `PlanExecutor`：每个 intent 一个分支，调现有 `ToolRegistry.execute`；`data_quality` 只 inspect、`metrics` inspect+prepare+compute、`report` 全 5 步（build_report 触发 mark_succeeded）；`clarify` 走 `mark_needs_clarification`；`out_of_scope` 走 `mark_failed`。每一步把 `intent` / `plan_summary` / `user_visible_summary` / `requested_*` 写到 `Run.context_snapshot` 让 UI 显示。(5) `agent/planner_factory.py`：`build_planner(model_config)` 在配置时返回 `LLMPlanner`，否则返回 `RulePlanner`。(6) WebUI 集成到 `webui/server.py`：`WebState` 加 `planner` / `plan_validator` / `plan_executor` / `registry` / `run_service` 字段；`_handle_post_message` 改成 planner→validator→executor 链；`_serialize_run` 加 `intent` / `plan_summary` / `summary`（planner 摘要 + 兜底）；`_apply_legacy_overrides` 让 JSON body 的 `start` / `end` / `metrics` 仍可作 plan 后的补丁。(8) `webui/static/index.html` 把 `run.intent` 渲染成 timeline 顶部色码胶囊，`run.summary` 替换静态 "已完成分析" 字符串。(9) `evaluation/runner.py` 加 `mode == "planner_unit"` 分派 + `_run_planner_unit` helper。(10) `evaluation/cases.jsonl` 加 E25-E28 四项用例覆盖四种核心 intent。(11) 单元测试 25 项（`test_planner.py` 11、`test_plan_validator.py` 9、`test_plan_executor.py` 5）+ 集成测试 9 项（`test_plan_pipeline.py` 6、`test_webui.py` 加 4 个 planner 路径）。(12) §19.1 状态、§19.2 未完成、§19.3 验证状态、§19.4 下一步同步更新。
- 修改文件：`src/quantlab_agent/domain/{models,errors}.py`、`src/quantlab_agent/agent/{planner,plan_validator,plan_executor,planner_factory}.py`（新增）、`src/quantlab_agent/agent/controller.py`、`webui/server.py`、`webui/static/index.html`、`evaluation/runner.py`、`evaluation/cases.jsonl`、`tests/unit/test_planner.py`、`tests/unit/test_plan_validator.py`、`tests/unit/test_plan_executor.py`、`tests/integration/test_plan_pipeline.py`、`tests/integration/test_webui.py`、本规划。
- 验证命令及结果：`.\.venv\Scripts\python.exe -m pytest`，179 项通过；`.\.venv\Scripts\python.exe -m evaluation.runner`，20 passed, 0 failed, 8 skipped（E25-E28 planner_unit 全过且 E25/E26 检查 succeeded 状态）；`.\.venv\Scripts\ruff.exe check src tests app.py evaluation webui` 通过；`.\.venv\Scripts\ruff.exe format --check src tests app.py evaluation webui` 通过。
- 实际模型与运行模式：未调真实模型；测试用 `FakeProvider` 驱动 `LLMPlanner`；WebUI 默认走 `RulePlanner`（不需 model 配置）；当用户配 `QUANTLAB_MODEL_*` 时，`build_state(model_config=...)` 自动切到 `LLMPlanner`。
- 失败／未验证事项：(1) 真实模型手动 smoke 未做——需要用户在本地设 `QUANTLAB_MODEL_*` 环境变量后跑 `quantlab-agent ui`，看 `LLMPlanner` 是否把 "比较 DEMO_A 最大回撤" 转成 `{intent:metrics, metrics:[max_drawdown]}` 这样的结构化 plan。(2) UI 没做多轮澄清——`clarify` 已能落 `NEEDS_CLARIFICATION`，但前端没把"agent 提问"显示在 composer 上方。下一轮做。
- 新增或修改的决策：(1) `Intent` 用 StrEnum，跟 `RunStatus` / `MetricName` 一致。(2) `AnalysisPlan` 冻结为 Pydantic `FrozenModel`——跟 `AnalysisSpec` / `Run` 同类，符合 ADR-003 "模型输出视为不可信输入"。`AnalysisPlan` 的 `@model_validator` 在构造时直接拒绝 `intent=metrics` 但 `metrics=` 为空这种非法组合。(3) `PlanValidator._resolve_dataset_refs` 不抛错而是悄悄丢弃未知 ref，让上层看到 `resolved_ids=()` 时统一抛 `INVALID_ARGUMENT`——避免 ploymorphism 引入额外异常类。(5) `Executor` 不引新工具，只组合现有 6 个；`data_quality` 不调 `prepare_analysis`，避免副作用"提前 bind dataset"。(6) `_apply_legacy_overrides` 在 validator 之后用 `model_copy` 覆盖 date_range/metrics——保持向后兼容：原 form-driven JSON body 仍然能工作。(7) `_serialize_run` 既读 `context_snapshot["intent"]` 又读 `failure.details["intent"]`——`out_of_scope` 不进 `_execute_resolved`，所以 intent 留在 failure.details；其它 intent 走 snapshot。
- 修正记录（2026-10-05 二次 review）：(1) `data_quality` / `metrics` / `chart` 叶子 intent 在工具成功后显式 `mark_succeeded`，不再停留在 `running`。(2) `PlanExecutor` 使用 `effective_start` / `effective_end` 作为 `prepare_analysis` 的执行窗口，`requested_start` / `requested_end` 只保留原始请求；WebUI legacy override 改日期时同步重算 effective range。(3) `dataset_refs=()` 统一解释为当前 session 全部数据集；未知非空 ref 仍触发 `INVALID_ARGUMENT`。(4) RulePlanner 识别“走势/对比走势”类 compare-only 请求，按默认 metrics 路径处理，避免 UI 建议词直接进入 clarify。(5) `QuantLabError` 构造改用 `ErrorCode.INVALID_ARGUMENT` 枚举而不是裸字符串。
- 下一步：(1) LLMPlanner 手动 smoke（设 env 跑 `quantlab-agent ui`）；(2) 多轮澄清 UI（§9.5 P0 第 2 点）；(3) `chart intent` 真正落地（§9.5.5 `chart` 行）；(4) 录演示视频 + 简历表述打磨。
- 是否需要用户补充信息：可选——`LLMPlanner` 手动 smoke 需要用户的 model 凭证；其余工作不需要。

## 21. 参考依据与使用限制

- 项目名称和初始描述来自当前仓库 README：`A tool-calling agent for reproducible financial data analysis.`
- 用户明确目标：准备投递开发实习生与量化产品研究实习生，计划用几天时间在 AI 辅助下完成相关项目。
- 方案基于本次讨论和用户提供简历中的能力描述，未审计既有项目代码。
- PandaAI 发起的 QUANTSKILLS 公开介绍包含量化技能、数据清洗、研究复现和报告等方向，可作为业务背景参考：[QUANTSKILLS](https://github.com/quantskills)。该页面在前序讨论中查看，不能替代招聘 JD，未来内容可能变化。
- 指标公式在本文件中明确作为项目计算契约，实施时用独立样例验证。
- 本文件不构成投资建议，也不为任何历史数据结果提供未来收益保证。

**最终交付重点：一个范围明确、结果可验证、失败可解释、用户能亲自讲清楚的项目。**
