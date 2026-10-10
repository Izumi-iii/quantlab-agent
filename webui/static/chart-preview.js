/* Interactive preview of persisted analysis artifacts. */
class QuantLabChartPreview {
  constructor() {
    this.container = document.querySelector("#chartContainer");
    this.meta = document.querySelector("#chartMeta");
    this.picker = document.querySelector("#chartPicker");
    this.style = document.querySelector("#chartStyle");
    this.axis = document.querySelector("#chartAxis");
    this.zero = document.querySelector("#chartZero");
    this.chart = null;
    this.runId = null;
    this.entries = [];
    this.runOrder = [];
    this.requestVersion = 0;
    this.payload = null;
    this.selection = {};
    this.start = 0;
    this.end = 100;
    this.picker.addEventListener("change", () => this.loadChart());
    for (const control of [this.style, this.axis, this.zero]) {
      control.addEventListener("change", () => this.render());
    }
    document.querySelector("#chartZoomIn").addEventListener("click", () => this.zoom(.5));
    document.querySelector("#chartZoomOut").addEventListener("click", () => this.zoom(2));
    document.querySelector("#chartReset").addEventListener("click", () => {
      this.start = 0;
      this.end = 100;
      this.selection = {};
      this.render();
    });
    document.querySelector("#chartDownload").addEventListener("click", () => {
      if (!this.chart) return;
      const link = document.createElement("a");
      link.download = `${this.kind}-${this.picker.value}.png`;
      link.href = this.chart.getDataURL({type: "png", pixelRatio: 2, backgroundColor: "#fff"});
      link.click();
    });
    new ResizeObserver(() => this.resize()).observe(this.container);
  }

  label(kind, window) {
    const name = {normalized_prices: "归一化价格走势", drawdown: "历史回撤",
      rolling_volatility: "滚动年化波动率", rolling_return: "滚动收益", rolling_drawdown: "窗口最大回撤"}[kind] || "分析图表";
    return window ? `${window} 日${name}` : name;
  }

  enableControls(enabled) {
    for (const control of document.querySelectorAll(".chart-toolbar button, .chart-toolbar input, .chart-toolbar select")) {
      control.disabled = !enabled;
    }
    this.picker.disabled = !this.entries.length;
  }

  clear() {
    this.requestVersion++;
    if (this.chart) this.chart.dispose();
    this.chart = null;
    this.payload = null;
    this.runId = null;
    this.entries = [];
    this.runOrder = [];
    this.picker.replaceChildren();
    this.meta.textContent = "";
    this.container.innerHTML = '<div class="empty-state">尚无图表。</div>';
    this.enableControls(false);
  }

  setRun(run, toolCalls) {
    if (!run.chart_ids?.length) return;
    const call = toolCalls.find(t => t.tool_name === "create_charts" && t.ok && t.data);
    const kinds = call?.data?.kinds || [];
    const windows = call?.data?.windows || [];
    if (!this.runOrder.includes(run.run_id)) this.runOrder.push(run.run_id);
    run.chart_ids.forEach((id, index) => {
      if (!this.entries.some(entry => entry.id === id)) {
        this.entries.push({id, runId: run.run_id, kind: kinds[index], window: windows[index]});
      }
    });
    this.picker.replaceChildren();
    this.entries.forEach((entry, index) => {
      const runNumber = this.runOrder.indexOf(entry.runId) + 1;
      this.picker.add(new Option(`${index + 1}. ${this.label(entry.kind, entry.window)} · 第 ${runNumber} 次分析`, entry.id));
    });
    this.picker.value = run.chart_ids[0];
    if (this.entries.length) this.loadChart();
  }

  async loadChart() {
    const version = ++this.requestVersion;
    const chartId = this.picker.value;
    const entry = this.entries.find(item => item.id === chartId);
    if (!entry) return;
    const runId = entry.runId;
    this.runId = runId;
    if (this.chart) this.chart.dispose();
    this.chart = null;
    this.payload = null;
    this.enableControls(false);
    this.meta.textContent = "正在加载图表…";
    this.container.innerHTML = '<div class="empty-state">正在加载…</div>';
    try {
      const response = await fetch(`/api/runs/${runId}/chart/${chartId}.json`);
      if (!response.ok) throw new Error("图表数据读取失败");
      const artifact = await response.json();
      if (version !== this.requestVersion) return;
      if (!artifact.data?.series?.length || !window.echarts) throw new Error("图表暂不可用");
      this.payload = artifact.data;
      this.kind = artifact.kind;
      this.window = artifact.window || this.payload.window;
      entry.kind = this.kind;
      entry.window = this.window;
      this.picker.selectedOptions[0].textContent = `${this.picker.selectedIndex + 1}. ${this.label(this.kind, this.window)} · 第 ${this.runOrder.indexOf(runId) + 1} 次分析`;
      document.querySelector("#previewTitle").firstChild.textContent = `分析结果 ${runId.slice(0, 8)}…`;
      this.start = 0;
      this.end = 100;
      this.selection = {};
      this.style.value = this.kind === "drawdown" ? "area" : "line";
      this.axis.value = "time";
      this.zero.checked = this.kind === "drawdown";
      this.container.replaceChildren();
      this.chart = echarts.init(this.container, null, {width: this.container.clientWidth || 480, height: 420});
      this.chart.on("datazoom", () => {
        const zoom = this.chart.getOption().dataZoom[0];
        this.start = zoom.start;
        this.end = zoom.end;
      });
      this.chart.on("legendselectchanged", event => { this.selection = event.selected; });
      this.enableControls(true);
      this.render();
      this.resize();
    } catch (error) {
      if (version !== this.requestVersion) return;
      this.meta.textContent = "交互图加载失败，显示原始图表。";
      this.container.replaceChildren();
      const image = document.createElement("img");
      image.src = `/api/runs/${runId}/chart/${chartId}.png`;
      image.alt = "原始分析图表";
      this.container.append(image);
      const link = document.createElement("a");
      link.href = image.src;
      link.download = `${chartId}.png`;
      link.textContent = "下载原始图表";
      this.container.append(link);
    }
  }

  render() {
    if (!this.chart || !this.payload) return;
    const temporal = this.axis.value === "time";
    const drawdown = this.kind === "drawdown";
    const percentage = drawdown || this.kind.startsWith("rolling_");
    const formatValue = value => value === null || value === undefined ? "数据不足" : percentage ? `${(value * 100).toFixed(2)}%` : Number(value).toFixed(2);
    const series = this.payload.series;
    const dates = series[0].x;
    this.meta.textContent = `${this.label(this.kind, this.window)} · ${dates[0]} 至 ${dates[dates.length - 1]} · ${dates.length.toLocaleString("zh-CN")} 条观测`;
    if (this.window) this.meta.textContent += ` · 窗口按观测条数${this.kind === "rolling_volatility" ? `，按 ${this.payload.annualization_factor} 年化` : ""}`;
    if (series.every(item => item.y.every(value => value === null))) this.meta.textContent += this.window ? " · 数据不足，尚无完整窗口" : " · 数据不足，暂无可绘制数值";
    this.chart.setOption({
      animation: false,
      useUTC: true,
      color: ["#1677c8", "#df7941", "#359b70", "#b95273"],
      textStyle: {fontFamily: "Arial, Microsoft YaHei, sans-serif", fontSize: 12},
      legend: {type: "scroll", top: 0, left: 0, right: 0, selected: this.selection},
      grid: {left: 12, right: 20, top: 52, bottom: 92, containLabel: true},
      tooltip: {
        trigger: "axis", confine: true, renderMode: "richText",
        formatter: params => {
          if (!params.length) return "";
          const date = series[params[0].seriesIndex].x[params[0].dataIndex];
          return [date, ...params.map(p => `${p.seriesName}: ${formatValue(Array.isArray(p.value) ? p.value[1] : p.value)}`)].join("\n");
        },
      },
      xAxis: {
        type: temporal ? "time" : "category",
        data: temporal ? undefined : dates,
        name: temporal ? "日期" : "交易序号", nameLocation: "middle", nameGap: 28,
        boundaryGap: false,
        axisLabel: temporal ? {formatter: value => new Date(value).toISOString().slice(0, 10), hideOverlap: true}
          : {formatter: (value, index) => String(index + 1), hideOverlap: true},
      },
      yAxis: {
        type: "value", scale: !this.zero.checked,
        name: percentage ? this.label(this.kind, this.window) : "价格指数（起点=100）", nameGap: 16,
        nameTextStyle: {align: "left"},
        axisLabel: {formatter: value => percentage ? `${(value * 100).toFixed(1)}%` : value},
        splitLine: {lineStyle: {color: "#edf0f3"}},
      },
      dataZoom: [
        {type: "inside", start: this.start, end: this.end, filterMode: "none"},
        {type: "slider", start: this.start, end: this.end, bottom: 12, height: 24, showDetail: false, filterMode: "none"},
      ],
      series: series.map(item => ({
        name: item.asset_id, type: "line", showSymbol: false, smooth: false,
        step: this.style.value === "step" ? "end" : false,
        areaStyle: this.style.value === "area" ? {opacity: .15} : undefined,
        lineStyle: {width: 1.5},
        data: temporal ? item.x.map((date, index) => [Date.parse(`${date}T00:00:00Z`), item.y[index]]) : item.y,
      })),
    }, {notMerge: true});
  }

  zoom(factor) {
    if (!this.chart) return;
    const center = (this.start + this.end) / 2;
    const width = Math.min(100, Math.max(.01, (this.end - this.start) * factor));
    this.start = Math.max(0, Math.min(100 - width, center - width / 2));
    this.end = this.start + width;
    this.chart.dispatchAction({type: "dataZoom", start: this.start, end: this.end});
  }

  resize() {
    if (this.chart && this.container.clientWidth) {
      this.chart.resize({width: this.container.clientWidth, height: this.container.clientHeight});
    }
  }
}
