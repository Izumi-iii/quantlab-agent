# QuantLab Agent 数据分析能力升级设计

> 文档版本：v0.2  
> 建立日期：2026-10-07  
> 适用项目：`D:\aaaWang\quantlab-agent`  
> 本文性质：功能升级设计与可行性评估。本文记录“可以做什么、为什么做、如何接入现有工具链”，不表示这些功能已经实现。
>
> v0.2 变更（相对 v0.1）：
>
> - 工具命名统一为 `describe_price_series`（v0.1 中 `describe_price_series` / `describe_series` 并存）。
> - 顶层 `Intent` 只新增 `PROFILE`；其余能力（走势描述、异常诊断、风险、滚动、对比）作为 `metrics` intent 的 `extras` 选项，避免 intent 膨胀到难以消歧。
> - `compute_risk_metrics` 不再包含 `max_drawdown`（已归 `compute_metrics`），避免重复指标破坏证据链。
> - 异常阈值默认改为 `k=3.5`（Iglewicz–Hoaglin 准则），并标注参考依据。
> - 年化假设（252）显式作为风险指标的固定前提，不暴露给工具调用方。
> - `compare_assets` 与 `explain_metric_driver` 暂不注册为工具，先实现为 `summary_presenters.py` 中的纯函数。
> - 补回 `chart` intent（M6.5），并把滚动图表合并到 `chart` 路径下。
> - 里程碑 M7/M8/M9/M10 重新排序，把 M6.5（chart intent）插在 M7 之前。

## 1. 背景

当前 QuantLab Agent 已具备一条受控分析链路：

```text
用户自然语言
  -> Planner / PlanValidator / PlanExecutor
  -> ToolRegistry
  -> list_datasets / inspect_dataset / prepare_analysis
  -> compute_metrics / create_charts / build_report
  -> Web UI 蓝色回答气泡、右侧表格/图表/报告预览
```

现有能力已经可以覆盖：

- CSV 导入与基础质量检查。
- 按日期区间切片。
- 单资产或双资产对齐。
- 区间收益、最大回撤、年化波动率。
- 归一化价格图和回撤图。
- Markdown 报告。

但从“数据分析 Agent”的体验看，还存在明显缺口：

- 用户问“这张表大概是什么情况”时，系统还缺少通用表格画像。
- 用户问“有没有异常”时，质量检查偏导入层，缺少收益跳变、极端值、缺口等分析层诊断。
- 用户问“风险怎么样”时，当前只有最大回撤和波动率，风险画像不够完整。
- 用户问“为什么这个结果这样”时，系统还缺少解释型工具，例如最大回撤发生区间、收益主要贡献日。
- 用户问“随时间变化如何”时，系统还缺少滚动指标和滚动图。

## 2. 设计原则

### 2.1 保持产品边界

升级方向仍然是历史 CSV 数据分析，不进入：

- 股票推荐。
- 自动交易。
- 未来价格预测。
- 未经验证的数据源联网抓取。
- 对投资结果作保证。

Agent 可以解释历史数据、指出风险和限制，但不能给出买卖建议。

### 2.2 工具结果必须可验证

所有数值仍然由确定性 Python 工具计算，模型只负责：

- 理解用户问题。
- 选择 intent 和 extras 字段。
- 汇总工具结果为用户可读回答。

蓝色气泡里的自然语言总结必须来自工具结果，不能由模型凭空编造。

### 2.3 先增强“分析深度”，再增强“视觉包装”

优先实现能改变分析结论的能力，例如画像、异常、风险、滚动指标；图表和 UI 作为结果呈现，不应先于分析语义本身。

### 2.4 顶层 Intent 保持克制

不为了新增功能就在 Planner 顶层 `Intent` 加分支。`Intent` 是用户级动作；像“异常”“滚动”这种属于现有动作的修饰词，应该作为 `AnalysisPlan` 上的 `extras` 字段存在，避免 12 个 intent 的关键词消歧困境。

### 2.6 同一指标只能由一个工具产出

`max_drawdown` 已归 `compute_metrics`；风险工具只产出 `compute_metrics` 不产出的指标（Sharpe / Sortino / Calmar / VaR / CVaR / 日收益均值 / 日收益标准差 / 年化收益）。报告引用一致性由这个不变量保证。

## 3. 候选功能可行性评估

| 功能 | 用户问题示例 | 可行性 | 实现复杂度 | 建议里程碑 | 结论 |
| --- | --- | --- | --- | --- | --- |
| `profile_dataset` 表格画像 | “这个 CSV 大概是什么情况？” | 高 | 低 | M7 | 顶层新 `PROFILE` Intent；建议做 |
| `describe_price_series` 价格序列摘要 | “这个资产走势有什么特点？” | 高 | 低 | 低 | `metrics` intent 的 `describe` extra；建议做 |
| 统一 `summary_presenters` 摘要层 | “结果在哪里？” | 高 | 中 | M7 | 不注册为工具；建议做 |
| `detect_anomalies` 异常检测 | “有没有异常值/跳变？” | 高 | 中 | M8 | `data_quality` intent 的 `anomalies` extra；建议做 |
| `compute_risk_metrics` 风险指标 | “风险怎么样？” | 高 | 中 | M8 | `metrics` intent 的 `risk` extra；建议做 |
| `compute_rolling_metrics` 滚动指标 | “滚动波动率如何？” | 高 | 中 | M9 | `chart` intent 的 `rolling` extra；建议做 |
| 滚动图通过 `create_charts` 统一出图 | “生成滚动收益图” | 高 | 中 | M9 | 在 `ChartKind` 中加 `ROLLING_*`；建议做 |
| `summary_presenters` 中的 `compare_summary` | “两个资产谁更稳？” | 高 | 低 | M10 | 不注册为工具；建议做 |
| `summary_presenters` 中的 `explain_metric_driver` | “最大回撤发生在哪里？” | 高 | 低 | M10 | 不注册为工具；建议做 |
| `compute_correlation` 相关性 | “它们相关性如何？” | 中 | 中 | P2 | 多资产能力扩展后做 |
| `create_correlation_heatmap` 相关性热力图 | “画相关性热力图” | 中 | 中 | P2 | 多资产能力扩展后做 |
| `detect_regime_changes` 状态切换 | “波动状态是否变化？” | 中 | 低 | 中 | 在 `summary_presenters` 里用滚动波动率触发一段结论；M9 顺手加 |
| `benchmark_metrics` 基准分析 | “相对基准表现如何？” | 中 | 高 | 高 | 暂缓 |
| `forecast_price` 预测价格 | “下周会涨吗？” | 低 | 高 | — | 超出边界 |
| `recommend_trade` 买卖建议 | “现在能买吗？” | 低 | 高 | — | 超出边界 |

## 4. P0 功能设计

### 4.1 `profile_dataset`

#### 目标

给任意已导入 CSV 生成表格画像，回答“这份数据是什么样的”。

#### 输入

```json
{
  "dataset_id": "uuid"
}
```

#### 输出

```json
{
  "dataset_id": "uuid",
  "asset_id": "DEMO_A",
  "row_count": 10000,
  "columns": [
    {
      "name": "date",
      "semantic_type": "date",
      "missing_count": 0,
      "unique_count": 10000,
      "min": "1985-01-02",
      "max": "2023-05-02"
    },
    {
      "name": "close",
      "semantic_type": "numeric_price",
      "missing_count": 0,
      "unique_count": 9960,
      "min": 12.34,
      "max": 245.67,
      "mean": 84.21,
      "std": 31.42
    }
  ],
  "quality_summary": {
    "error_count": 0,
    "warning_count": 1,
    "top_issues": []
  }
}
```

#### 可行性

高。当前导入流程已经将 CSV 标准化为 `date, close` 序列，也保存了 manifest 和 quality report。第一版可以只画像标准化后的数据，不处理任意宽表。

#### 技术设计

- 新增 `application/profiling.py`。
- 新增 `DatasetProfile`、`ColumnProfile` Pydantic 模型。
- 在 `agent/tools.py` 注册 `profile_dataset`。
- 新增顶层 `Intent.PROFILE`；Planner 增加关键词：
  - “概况”
  - “画像”
  - “这张表”
  - “字段”
  - “describe”
  - “profile”
- Web UI 蓝色气泡直接显示：
  - 行数。
  - 日期范围。
  - 价格范围。
  - 缺失/重复/异常摘要。

#### 工具链

```text
inspect_dataset
  -> profile_dataset
```

不调 `prepare_analysis`——profile 只看标准化后的数据，不依赖日期切片。

#### 验收标准

- 用户输入“看看这个 CSV 的概况”，工具链只运行 `inspect_dataset -> profile_dataset`。
- 蓝色气泡不要求用户展开工具调用链即可看到主要结论。
- `data_quality` intent 的输出保持原有形态；不与 `profile` 混淆。

### 4.2 `describe_price_series`（作为 `metrics` intent 的 extra）

#### 目标

生成价格序列的可读摘要，回答“走势有什么特点”。不新增顶层 Intent，作为 `metrics` intent 的可选 `extras` 之一。

#### 指标

- 起始价格、结束价格。
- 最高价、最低价及日期。
- 总涨跌幅。
- 上涨日数量、下跌日数量、持平日数量。
- 最大单日涨幅、最大单日跌幅。
- 最长连续上涨天数、最长连续下跌天数。
- 最大回撤区间的开始、谷底、恢复情况（来自 `compute_metrics` 的 `max_drawdown`）。

#### 可行性

高。全部可以从已准备好的价格序列和简单收益序列计算，不需要外部数据。

#### 技术设计

- 新增 `PriceSeriesSummary` 模型。
- 单独放入 `application/descriptive.py`（不塞进 `AnalysisService`）。
- 工具输入使用 `analysis_id`，复用 `prepare_analysis` 的日期切片和双资产对齐结果。
- 注册工具 `describe_price_series`。
- `AnalysisPlan` 增加 `extras: tuple[AnalysisExtra, ...]`，其中 `AnalysisExtra` 枚举第一阶段含 `DESCRIBE_PRICE_SERIES`。`metrics` intent 解析到 `extras` 后，executor 在 `compute_metrics` 后插入 `describe_price_series`。

#### 工具链

```text
inspect_dataset
  -> prepare_analysis
  -> compute_metrics
  -> describe_price_series   (only if requested)
```

#### 蓝色气泡示例

```text
走势摘要完成。
有效区间：2021-01-04 至 2024-06-14。
- DEMO_A：累计上涨 95.18%，最高价出现在 2024-06-14。
- 最大单日跌幅为 -8.42%，发生在 2022-03-08。
- 最长连续上涨 7 个观测日，最长连续下跌 5 个观测日。
```

### 4.3 统一 summary_presenters

#### 目标

把工具结果转成稳定、可测试、面向用户的回答文本。它不是模型自由总结，而是确定性摘要器。

#### 可行性

高。当前 Web UI 已经有 `_summarize_metrics`、`_summarize_data_quality`、`_summarize_chart` 这类服务端摘要逻辑，可以逐步收敛成统一摘要层。

#### 技术设计

第一阶段只做后端内部模块，**不注册为外部工具**（与 v0.1 一致；后续如发现模型确实需要主动调用，再考虑注册 `summarize_analysis` 工具）。

```text
webui/server.py
  -> summary_presenters.py
      summarize_profile(...)
      summarize_metrics(...)
      summarize_describe(...)
      summarize_anomalies(...)
      summarize_risk(...)
      summarize_rolling(...)
      summarize_compare(...)
      summarize_explain(...)
```

Web UI 在生成蓝色气泡前，先调用对应的 `summarize_*` 拿到摘要文本，再展示。

#### 设计约束

- 摘要只能使用 `tool_calls` 和 `run.context_snapshot`。
- 摘要要保留“不可用原因”。
- 摘要应控制长度，默认 5 到 10 行。
- 完整细节仍放到右侧表格或报告。

## 5. P1 功能设计

### 5.1 `detect_anomalies`（作为 `data_quality` intent 的 extra）

#### 目标

识别分析层面的异常（区别于 CSV 导入错误）。不新增顶层 Intent，作为 `data_quality` intent 的可选 `extras`。

#### 检测项

- 极端单日收益（基于稳健阈值）。
- 价格跳变。
- 长时间缺口。
- 重复日期已清洗但仍需在摘要中提示。
- 疑似复权断点。
- 非正价格已在导入层拒绝，分析层只展示结果。

#### 可行性

高。第一版使用规则阈值，不引入统计模型。

#### 推荐规则

```text
abs(simple_return - median_return) > k * MAD          # 稳健阈值
abs(simple_return) >= absolute_threshold               # 绝对阈值
date_gap_days >= gap_threshold                        # 缺口阈值
```

参考 Iglewicz–Hoaglin (1993) 对 MAD 倍数的推荐，默认参数：

- `k = 3.5`（Iglewicz–Hoaglin 准则；`k=6` 是常用做"几乎不报"的阈值，对短样本会漏掉真实异常）。
- `absolute_threshold = 0.15`（15% 单日变动，针对单资产价格；多资产时按波动率归一化）。
- `gap_threshold = 10`（连续 10 个日历日无观测）。

后续若要做更精细的检测（季节性、复权断点），需要可配置 `k` 与窗口。

#### 输出

```json
{
  "analysis_id": "uuid",
  "asset_anomalies": [
    {
      "asset_id": "DEMO_A",
      "items": [
        {
          "date": "2022-03-08",
          "kind": "extreme_negative_return",
          "severity": "warning",
          "value": -0.1842,
          "message": "Single-period return is below the robust threshold."
        }
      ]
    }
  ]
}
```

#### 技术接入

- 新增 `application/diagnostics.py`。
- 新增 `AnomalyReport`、`AnomalyItem` 模型。
- 工具名：`detect_anomalies`。
- `AnalysisPlan.extras` 增加 `DETECT_ANOMALIES`。
- `data_quality` intent + 该 extras → 工具链：`inspect_dataset → detect_anomalies`（不调 `prepare_analysis`，避免提前 bind dataset）。

#### 注意

异常不一定代表数据错误，可能是真实市场波动。蓝色气泡必须用“疑似”“需要核查”，不要写成确定错误。

### 5.2 `compute_risk_metrics`（作为 `metrics` intent 的 extra）

#### 目标

补齐风险收益分析，让用户能问“风险怎么样”“稳不稳”。不新增顶层 Intent，作为 `metrics` intent 的可选 `extras`。

#### 指标

第一版（新增，全部不与 `compute_metrics` 重复）：

- 日收益均值。
- 日收益标准差。
- 年化收益（几何年化）。
- 年化波动率（已在 `compute_metrics` 中——**此处不输出**，避免重复）。
- Sharpe ratio。
- Sortino ratio。
- Calmar ratio。
- VaR 95%（历史分位数）。
- CVaR 95%（历史分位数）。

第二版（暂缓）：偏度、峰度、下行捕获、胜率、盈亏比。

#### 可行性

高。基于价格序列即可计算。需要注意无风险利率默认值和样本不足提示。

#### 设计决策

- 年化假设沿用 `AnalysisService.annualization_factor = 252`（来自 `PROJECT_PLAN §5.3`）。**不暴露给工具调用方**，避免引入可调参数扩大解释范围。如果用户对 252 提出异议，引导到 `PROJECT_PLAN §5.3` 的修订讨论，不在工具里改。
- `risk_free_rate` 不在工具签名中暴露；首版固定 0。
- VaR / CVaR 使用历史分位数，不使用正态假设。
- 年化收益第一版用几何年化，样本太短时给出 warning。

#### 工具设计

```text
compute_risk_metrics(analysis_id)
```

`confidence_level` 与 `risk_free_rate` **不作为工具参数**——以避免与 `PROJECT_PLAN §5.3` 的“首版不做年化因子自由配置”冲突。第一版固定 95% / 0%。

#### 工具链

```text
inspect_dataset
  -> prepare_analysis
  -> compute_metrics
  -> compute_risk_metrics   (only if requested)
```

#### Planner 关键开关

- `metrics` intent + `RISK` extra，由 planner 关键词触发：
  - “风险”
  - “稳不稳”
  - “夏普”
  - “VaR”
  - “回撤风险”
  - “risk”
  - “sharpe”
  - “sortino”

### 5.3 `compute_rolling_metrics` 与滚动图（作为 `chart` intent 的 extra）

#### 目标

回答“随时间变化如何”，例如滚动收益、滚动波动率、滚动回撤。

#### 指标

- rolling return。
- rolling volatility。
- rolling drawdown。
- rolling Sharpe。

#### 可行性

高。Pandas rolling 可以直接实现。复杂点在于窗口参数、样本不足和图表输出。

#### 工具设计

```json
{
  "analysis_id": "uuid",
  "windows": [20, 60, 252]
}
```

`windows` 不在工具签名中暴露给模型；由 planner 根据用户文本抽取（"60 日" → `[60]`；否则默认 `[20, 60, 252]`）。模型只控制是否要 extra，平台自己定窗口。

#### 输出

```json
{
  "rolling_id": "uuid",
  "analysis_id": "uuid",
  "series": [
    {
      "asset_id": "DEMO_A",
      "metric": "rolling_volatility",
      "window": 60,
      "points": [
        {"date": "2021-04-01", "value": 0.2134}
      ]
    }
  ]
}
```

#### 产物存储

```text
runs/{session_id}/runs/{run_id}/rolling/{rolling_id}.json
```

单独 `rolling` store 比复用 `chart_data` 结构清晰，便于后续表格视图。

#### 滚动图合并到 `create_charts`

不新增 `create_rolling_charts` 工具——直接在 `ChartKind` 枚举中加 `ROLLING_RETURN` / `ROLLING_VOLATILITY` / `ROLLING_DRAWDOWN`，`create_charts` 工具已经支持任意 `chart_kinds` 列表输入。executor 在 `compute_rolling_metrics` 后调用 `create_charts(analysis_id, kinds=[ROLLING_VOLATILITY, ...])`。

#### 工具链

```text
inspect_dataset
  -> prepare_analysis
  -> compute_metrics     (only if metrics or risk)
  -> compute_risk_metrics (only if risk + extra)
  -> compute_rolling_metrics (only if chart + rolling extra)
  -> create_charts       (with ROLLING_* kinds)
```

#### UI 行为

- 蓝色气泡显示关键结论。
- 右侧自动切到 Chart。
- Footer 显示 `Chart` 可用。
- 后续可支持 `Table` 展示 rolling points。

## 6. M10 / P2 / P3 暂缓功能

### 6.1 `summary_presenters.compare_summary` 与 `explain_summary`

M10 实现，**不注册为外部工具**：

- `compare_summary(analysis)`：两资产累计收益差、年化波动差、最大回撤差、A 跑赢 B 的观测比例——从 `compute_metrics` 输出直接算。
- `explain_summary(analysis, metric="max_drawdown")`：峰值日期、谷底日期、回撤幅度、是否恢复、恢复日期。

只有当跑完发现模型确实需要主动调用（而不是 WebUI 拿到结果后硬调用），再升级为工具。

### 6.2 `compute_correlation` 和 `create_correlation_heatmap`

可行性中。数学上简单，但当前 `AnalysisService.prepare` 限制 1 到 2 个数据集。相关矩阵和热力图对 3 个以上资产更有价值，建议等多资产分析能力扩展后再做。

前置工作：

- `AnalysisService.prepare` 支持 N 个数据集。
- UI dataset selector 支持多选和选择状态更清晰。
- 右侧表格支持矩阵展示。

### 6.3 `detect_regime_changes`

可行。中。可以用 rolling volatility 简单判断，也可以用统计模型。但如果做得过重，会超过项目当前体量。

建议：先不要做正式“状态切换模型”。在 `summary_presenters.rolling_summary` 里加一段"波动状态是否变化"的文字：

```text
最近 60 日波动率显著高于全样本中位数。
```

### 6.4 `benchmark_metrics`

可行中。需要用户明确哪个数据集是 benchmark，并且需要处理基准口径、货币、交易日对齐。

建议等 `compare_summary` 稳定后再做。第一版不要直接叫 alpha/beta，以免产品解释负担过大。

## 7. 不建议实现的功能

### 7.1 `forecast_price`

不建议做。原因：

- 超出“历史数据分析”边界。
- 容易让项目变成预测器，降低可信度。
- 小样本 CSV 下预测质量不可控。
- 需要评估、回测和风险披露，成本高。

### 7.2 `recommend_trade`

不做。原因：

- 涉及投资建议和交易决策。
- 与当前项目“分析助手，不做自动交易/荐股”的定位冲突。
- 不利于求职展示中的可信工程边界。

## 8. 推荐落地路线

### M6.5：`chart` intent 落地（基础）

目标：让用户能直接要"画图"而不强制生成完整报告。`chart` intent 已经在 `Intent` 枚举里，作为占位。

范围：
- 实现 `chart` intent：执行 `inspect_dataset → prepare_analysis → compute_metrics → create_charts`（不调 `build_report`）。
- 现有 `ChartKind`（`NORMALIZED_PRICES` / `DRAWDOWN`）已经支持。
- Web UI 右侧切到 Chart 视图。
- 评价：让 M9 的 `compute_rolling_metrics` 可以挂在 `chart` intent 后面。

### M7：表格画像 + 走势描述 + 统一摘要层

目标：让用户问“这份数据怎么样”和“这个资产走势特点”时，蓝色气泡直接给出有用结论。

范围：
- `profile_dataset` 工具 + 顶层 `PROFILE` Intent。
- `describe_price_series` 工具 + `metrics` intent 的 `DESCRIBE` extra。
- 拆分 `webui/server.py` 的摘要逻辑成 `summary_presenters.py`。
- Web UI 蓝色气泡展示画像和走势摘要。
- 评价用例 E30、E31。

### M8：异常诊断 + 风险指标

目标：让 Agent 能回答“有没有异常”和“风险怎么样”。

范围：
- `detect_anomalies` 工具 + `data_quality` intent 的 `ANOMALIES` extra。
- `compute_risk_metrics` 工具 + `metrics` intent 的 `RISK` extra。
- `summary_presenters.anomalies_summary` 和 `risk_summary`。
- 评价用例 E32、E33。
- 不新增顶层 Intent。

### M9：滚动分析（挂在 `chart` intent 上）

目标：让 Agent 能回答“随时间变化如何”。

范围：
- `compute_rolling_metrics` 工具 + `chart` intent 的 `ROLLING` extra。
- `ChartKind` 加 `ROLLING_RETURN` / `ROLLING_VOLATILITY` / `ROLLING_DRAWDOWN`。
- `create_charts` 工具支持新 ChartKind，不需要新增工具。
- `summary_presenters.rolling_summary`（顺手加 `regime_changes` 一句话）。
- 评价用例 E34。
- 不新增 `create_rolling_charts` 工具。

### M10：双资产对比与指标解释（只做 presenter）

目标：让 Agent 不只是计算两个资产，而是解释差异。

范围：
- `summary_presenters.compare_summary`。
- `summary_presenters.explain_summary`。
- 不注册为外部工具。

## 9. 架构改动清单

### 9.1 Domain 层

仅在顶层 `Intent` 枚举中加一个值：

```python
class Intent(StrEnum):
    DATA_QUALITY = "data_quality"
    METRICS = "metrics"
    CHART = "chart"
    REPORT = "report"
    CLARIFY = "clarify"
    OUT_OF_SCOPE = "out_of_scope"
    PROFILE = "profile"          # 新增
```

新增 `AnalysisExtra` 枚举（用于 `AnalysisPlan.extras`）：

```python
class AnalysisExtra(StrEnum):
    DESCRIBE_PRICE_SERIES = "describe_price_series"
    RISK = "risk"
    ANOMALIES = "anomalies"
    ROLLING = "rolling"
```

新增 `RiskMetricName` 枚举（独立于 `MetricName`，避免 `compute_metrics` 变宽）：

```python
class RiskMetricName(StrEnum):
    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    CALMAR_RATIO = "calmar_ratio"
    VAR_95 = "var_95"
    CVAR_95 = "cvar_95"
    MEAN_DAILY_RETURN = "mean_daily_return"
    STD_DAILY_RETURN = "std_daily_return"
    ANNUALIZED_RETURN = "annualized_return"
```

新增 `ChartKind` 值（M9）：

```python
class ChartKind(StrEnum):
    NORMALIZED_PRICES = "normalized_prices"
    DRAWDOWN = "drawdown"
    ROLLING_RETURN = "rolling_return"
    ROLLING_VOLATILITY = "rolling_volatility"
    ROLLING_DRAWDOWN = "rolling_drawdown"
```

注意：`max_drawdown` 仍在 `MetricName` 中，**不**进入 `RiskMetricName`，避免两个工具产出同一个指标。

### 9.2 Application 层

新增模块：

```text
src/quantlab_agent/application/profiling.py
src/quantlab_agent/application/descriptive.py
src/quantlab_agent/application/diagnostics.py
src/quantlab_agent/application/risk.py
src/quantlab_agent/application/rolling.py
```

不引入 `application/comparison.py`——`summary_presenters.py` 负责。

不要把所有计算继续塞进 `AnalysisService`。`AnalysisService` 应继续负责准备和基础指标，复杂分析拆成独立服务更清晰。

### 9.3 Agent Tools 层

新增工具：

```text
profile_dataset            # M7
describe_price_series     # M7
detect_anomalies         # M8
compute_risk_metrics     # M8
compute_rolling_metrics  # M9
```

不新增 `compare_assets` / `explain_metric_driver` / `create_rolling_charts`——前两种走 `summary_presenters`；最后一种合并到 `create_charts`。

工具命名保持动词开头，输入输出使用 Pydantic model，输出必须可 JSON 序列化。

### 9.4 Planner 层

`Intent.PROFILE` 关键词：

```text
概况、画像、字段、这张表、describe、profile
```

`AnalysisPlan.extras` 关键词（中文）：

| Extra | 中文 | 英文 |
| --- | --- | --- |
| `DESCRIBE_PRICE_SERIES` | 走势特点、表现、发生了什么 | describe, summarize trend |
| `ANOMALIES` | 异常、跳变、缺口 | anomaly, outlier, gap |
| `RISK` | 风险、稳不稳、夏普、VaR | risk, sharpe, var, sortino |
| `ROLLING` | 滚动、窗口、60 日、移动 | rolling, window, moving |

`LLMPlanner` 的 prompt 需要同步扩展 schema。扩展前必须先更新 `RulePlanner` 和测试，保证无模型配置时也能演示。

### 9.5 Web UI 层

新增摘要展示策略：

- `PROFILE`：蓝色气泡显示表格画像，右侧停留 Table。
- `metrics + DESCRIBE`：蓝色气泡显示走势摘要，右侧可停留 Table 或 Chart。
- `data_quality + ANOMALIES`：蓝色气泡显示异常列表，右侧可展示异常表。
- `metrics + RISK`：蓝色气泡显示风险指标，右侧展示指标表。
- `chart + ROLLING`：蓝色气泡显示滚动分析摘要，右侧自动切 Chart。
- `report`：完整 Markdown 报告。

后续需要补一个 `Analysis Table` 视图，避免所有结构化结果都挤进气泡。

### 9.6 `summary_presenters.py`

放在 `webui/server.py` 同目录或 `src/quantlab_agent/webui/`，导入边界：

- 只能依赖 `domain/`, `application/`, 不可依赖 `agent/planner.py`（避免循环）。
- 摘要函数签名：`summarize_*(run: Run, tool_calls: tuple[ToolCallRecord, ...]) -> str`。
- 单元测试：每个 presenter 一个 `tests/webui/test_summary_presenters.py`，传入固定 `Run` 与 `tool_calls`，断言输出。

## 10. 测试策略

每个新工具至少覆盖：

- 单元测试：计算结果、边界样本、样本不足。
- 工具测试：Pydantic 入参校验、ownership 校验、run 绑定。
- Planner 测试：中文/英文关键词映射到正确的 intent 或 extras。
- Executor 测试：intent + extras 对应正确工具链。
- WebUI 集成测试：`POST /messages` 返回正确 `intent`、`summary`、`tool_calls`。
- `summary_presenters` 单元测试：固定 `Run` 输入断言输出。

推荐先为每个里程碑增加 evaluation case：

```text
E30 profile: “这个 CSV 大概是什么情况？” -> intent=profile
E31 describe: “这个资产走势有什么特点？” -> intent=metrics, extras=[describe_price_series]
E32 diagnose: “有没有异常值？” -> intent=data_quality, extras=[anomalies]
E33 risk: “风险怎么样？” -> intent=metrics, extras=[risk]
E34 rolling: “生成 60 日滚动波动率图” -> intent=chart, extras=[rolling]
```

## 11. 近期建议

下一步最值得做的是 M6.5 + M7：

1. M6.5：在 Planner/Executor 上落实 `chart` intent（现有 `ChartKind` 仍然够用），Web UI 切到 Chart 视图。
2. M7：`profile_dataset` + 顶层 `PROFILE` Intent。
3. M7：`describe_price_series` + `metrics` extras。
4. M7：拆分 `summary_presenters.py`，Web UI 蓝色气泡展示画像和走势摘要。

这一步投入不大，但会显著改善“像 Agent 一样回答”的体验，也能为后续风险、异常、滚动分析建立统一模式。