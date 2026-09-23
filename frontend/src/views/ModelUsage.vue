<template>
  <div class="usage-page">
    <div class="usage-toolbar">
      <span class="scope-badge"
        ><ShieldCheck :size="15" /> 全系统 · 仅超级管理员</span
      ><span class="muted">北京时间 · 供应商上报用量</span>
      <div class="toolbar-actions">
        <button class="btn" :disabled="loading" @click="refresh">刷新</button
        ><button
          class="btn btn-primary"
          :disabled="loading || exporting || !applied || !!error"
          @click="exportCsv"
        >
          <Download :size="16" /> {{ exporting ? "导出中…" : "导出明细" }}
        </button>
      </div>
    </div>
    <form class="usage-filters panel" @submit.prevent="applyFilters">
      <div class="filter-row">
        <label
          >开始日期<input v-model="filters.start" type="date" required /></label
        ><label
          >结束日期<input v-model="filters.end" type="date" required /></label
        ><label
          >工作空间<select v-model="filters.workspace_id">
            <option value="">全部空间</option>
            <option
              v-for="o in options.workspaces"
              :key="o.value"
              :value="o.value"
            >
              {{ o.label }}
            </option>
          </select></label
        ><label
          >来源<select v-model="filters.source">
            <option value="">全部来源</option>
            <option v-for="(v, k) in options.sources" :key="k" :value="k">
              {{ v }}
            </option>
          </select></label
        ><label
          >模型<select v-model="filters.model">
            <option value="">全部模型</option>
            <option v-for="o in options.models" :key="o.value" :value="o.value">
              {{ o.label }}
            </option>
          </select></label
        >
      </div>
      <div v-if="expanded" class="filter-row extra-filters">
        <label v-for="field in extraFields" :key="field.key"
          >{{ field.label
          }}<select v-model="filters[field.key]" :aria-label="field.label">
            <option value="">全部</option>
            <option v-for="o in field.items" :key="o.value" :value="o.value">
              {{ o.label }}
            </option>
          </select></label
        >
      </div>
      <div class="filter-footer">
        <div class="quick-ranges">
          <button
            v-for="d in [1, 7, 30]"
            :key="d"
            type="button"
            class="range-button"
            @click="range(d)"
          >
            {{ d === 1 ? "今天" : `近 ${d} 天` }}</button
          ><button
            type="button"
            class="range-button"
            @click="expanded = !expanded"
          >
            {{ expanded ? "收起筛选" : "更多筛选" }}</button
          ><button type="button" class="range-button" @click="reset">
            重置
          </button>
        </div>
        <button class="btn btn-primary" :disabled="loading">
          {{ loading ? "查询中…" : "查询" }}
        </button>
      </div>
    </form>
    <p v-if="error" class="usage-notice error" role="alert">{{ error }}</p>
    <p v-if="collectorWarning" class="usage-notice" role="status">
      {{ collectorWarning }}
    </p>
    <nav class="usage-tabs" aria-label="用量分类">
      <button
        v-for="(v, k) in tabs"
        :key="k"
        :class="{ active: tab === k }"
        :aria-current="tab === k ? 'page' : undefined"
        @click="tab = k"
      >
        {{ v }}
      </button>
    </nav>
    <template v-if="summary">
      <div class="metric-grid">
        <article v-for="card in cards" :key="card.label" class="metric panel">
          <span>{{ card.label }}</span
          ><strong>{{ card.value }}</strong
          ><small>{{ card.hint }}</small>
        </article>
      </div>
      <template v-if="tab === 'overview'">
        <section class="panel trend-panel">
          <div class="panel-heading">
            <div>
              <h2>Token 消耗趋势</h2>
              <p>输入与输出分别统计，缺失用量不绘柱；点击时间柱查看明细</p>
            </div>
            <select v-model="grain" aria-label="趋势粒度" @change="refresh">
              <option value="day">按日</option>
              <option value="hour">按小时（最多31天）</option>
            </select>
          </div>
          <div class="chart-legend">
            <span><i class="input-dot"></i>输入</span
            ><span><i class="output-dot"></i>输出</span
            ><span class="muted">峰值 {{ fmtTokens(trendMax) }} Token</span>
          </div>
          <div v-if="hasCalls" class="trend-scroll">
            <div
              class="trend-chart"
              :style="{ minWidth: Math.max(500, trend.length * 28) + 'px' }"
            >
              <button
                v-for="(point, i) in trend"
                :key="point.bucket"
                class="trend-column"
                :aria-label="`${time(point.bucket)} 输入 ${fmtTokens(point.input_tokens)}，输出 ${fmtTokens(point.output_tokens)}`"
                :title="`${time(point.bucket)}\n输入 ${fmtTokens(point.input_tokens)} / 输出 ${fmtTokens(point.output_tokens)}\n${point.calls || 0} 次调用`"
                @click="drillTime(point)"
              >
                <span class="bars"
                  ><span class="bar-stack"
                    ><span class="bar-value">{{
                      tokensLabel(point.input_tokens)
                    }}</span
                    ><span
                      class="input-bar"
                      :style="{ height: height(point.input_tokens) }"
                    ></span></span
                  ><span class="bar-stack"
                    ><span class="bar-value">{{
                      tokensLabel(point.output_tokens)
                    }}</span
                    ><span
                      class="output-bar"
                      :style="{ height: height(point.output_tokens) }"
                    ></span></span
                ></span
                ><span class="axis-label">{{
                  i % Math.max(1, Math.ceil(trend.length / 12)) === 0
                    ? bucketLabel(point.bucket)
                    : "·"
                }}</span>
              </button>
            </div>
          </div>
          <div v-else class="empty-state">
            <BarChart3 :size="32" /><strong>当前范围暂无模型调用</strong
            ><span>从功能上线后开始采集，完成模型调用后点击刷新。</span>
          </div>
        </section>
        <div class="rank-grid">
          <section v-for="rank in ranks" :key="rank.dimension" class="panel">
            <div class="panel-heading">
              <h2>{{ rank.title }}</h2>
              <button
                class="range-button"
                @click="
                  dimension = rank.dimension;
                  tab = 'groups';
                  loadGroups();
                "
              >
                全部统计 →
              </button>
            </div>
            <p v-if="!rank.items.length" class="empty-small">暂无记录</p>
            <button
              v-for="item in rank.items"
              :key="item.key"
              class="rank-row"
              @click="drill(rank.dimension, item)"
            >
              <span class="rank-line"
                ><span>{{ item.label }}</span
                ><strong>{{ fmtTokens(item.total_tokens) }}</strong></span
              ><span class="rank-track"
                ><span
                  :style="{
                    width:
                      percent(item.total_tokens, summary.totals.total_tokens) +
                      '%',
                  }"
                ></span></span
              ><small
                >{{ item.calls }} 次调用 ·
                {{ percent(item.total_tokens, summary.totals.total_tokens) }}%
                已知用量</small
              >
            </button>
          </section>
        </div>
        <p class="insight panel">
          <Info :size="18" /><span>{{ insight }}</span>
        </p>
      </template>
      <section v-if="tab === 'groups'" class="panel">
        <div class="panel-heading">
          <div>
            <h2>分类统计</h2>
            <p>平均消耗以返回总 Token 的调用为分母；点击分组查看调用。</p>
          </div>
          <select
            v-model="dimension"
            aria-label="统计维度"
            @change="
              groupPage = 1;
              loadGroups();
            "
          >
            <option v-for="(v, k) in dimensions" :key="k" :value="k">
              按{{ v }}
            </option>
          </select>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{{ dimensions[dimension] }}</th>
                <th>调用次数</th>
                <th>输入</th>
                <th>输出</th>
                <th>总 Token</th>
                <th>占比</th>
                <th>平均 Token</th>
                <th>完整率</th>
                <th>失败次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in groups.items" :key="row.key">
                <td>
                  <button class="text-link" @click="drill(dimension, row)">
                    {{ groupLabel(row) }}
                  </button>
                </td>
                <td>{{ fmt(row.calls) }}</td>
                <td>{{ fmtTokens(row.input_tokens) }}</td>
                <td>{{ fmtTokens(row.output_tokens) }}</td>
                <td>
                  <strong>{{ fmtTokens(row.total_tokens) }}</strong>
                </td>
                <td>
                  {{ percent(row.total_tokens, summary.totals.total_tokens) }}%
                </td>
                <td>{{ fmtTokens(row.avg_tokens) }}</td>
                <td>{{ rate(row.completeness) }}</td>
                <td>{{ row.failed_calls }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!groups.items.length" class="empty-small">
          当前筛选没有记录。
        </p>
        <div class="pagination">
          <span>共 {{ groups.total }} 组</span
          ><button
            class="btn"
            :disabled="groupPage === 1 || groupLoading"
            @click="
              groupPage--;
              loadGroups();
            "
          >
            上一页</button
          ><span>{{ groupPage }}</span
          ><button
            class="btn"
            :disabled="groupPage * 20 >= groups.total || groupLoading"
            @click="
              groupPage++;
              loadGroups();
            "
          >
            下一页
          </button>
        </div>
      </section>
      <section v-if="tab === 'calls'" class="panel">
        <div class="panel-heading">
          <div>
            <h2>调用审计</h2>
            <p>一次模型请求一条记录；业务操作详情包含该操作所有调用。</p>
          </div>
          <span v-if="callsLoading" class="muted">加载中…</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>来源 / 动作</th>
                <th>用户 / Agent</th>
                <th>供应商 / 模型</th>
                <th>输入</th>
                <th>输出</th>
                <th>总 Token</th>
                <th>状态</th>
                <th>耗时</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in calls.items" :key="row.id">
                <td class="nowrap">{{ time(row.started_at) }}</td>
                <td>
                  {{ label("sources", row.source)
                  }}<small>{{ label("actions", row.action) }}</small>
                </td>
                <td>
                  {{ row.user_name || "系统"
                  }}<small>{{ row.agent_name || "—" }}</small>
                </td>
                <td>
                  {{ row.provider }}<small>{{ row.requested_model }}</small>
                </td>
                <td>{{ fmtTokens(row.input_tokens) }}</td>
                <td>{{ fmtTokens(row.output_tokens) }}</td>
                <td>
                  <strong>{{ fmt(row.total_tokens) }}</strong
                  ><small v-if="row.usage_status !== 'complete'">{{
                    usageNames[row.usage_status]
                  }}</small>
                </td>
                <td>
                  <span :class="['state-pill', row.status]">{{
                    label("statuses", row.status)
                  }}</span>
                </td>
                <td>{{ duration(row.duration_ms) }}</td>
                <td>
                  <button
                    class="text-link"
                    @click="openOperation(row.operation_id)"
                  >
                    操作详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!calls.items.length" class="empty-small">
          当前筛选没有调用记录。
        </p>
        <div class="pagination">
          <span>共 {{ calls.total }} 条</span
          ><button
            class="btn"
            :disabled="callPage === 1 || callsLoading"
            @click="
              callPage--;
              loadCalls();
            "
          >
            上一页</button
          ><span>{{ callPage }}</span
          ><button
            class="btn"
            :disabled="callPage * 25 >= calls.total || callsLoading"
            @click="
              callPage++;
              loadCalls();
            "
          >
            下一页
          </button>
        </div>
      </section>
      <p class="footnote">
        未知用量不计为零；缓存和推理 Token 为输入 /
        输出的细分，不重复相加。统计可能低于实际账单，记录通常在调用结束后数秒入库。底层
        SDK 未公开的重试无法逐次还原。
      </p>
    </template>
    <dialog
      ref="detailDialog"
      class="usage-dialog"
      aria-labelledby="usage-detail-title"
      @click="closeOnBackdrop"
      @close="detail = null"
    >
      <div class="panel-heading">
        <h2 id="usage-detail-title">业务操作详情</h2>
        <button
          class="btn"
          autofocus
          @click="detailDialog.close()"
          aria-label="关闭详情"
        >
          <X :size="18" />
        </button>
      </div>
      <p v-if="detailLoading">加载中…</p>
      <template v-if="detail"
        ><p class="muted">
          {{ label("sources", detail.operation.source) }} ·
          {{ detail.operation.user_name || "系统" }} ·
          {{ time(detail.operation.started_at) }}
        </p>
        <p>
          操作共 <strong>{{ detail.total }}</strong> 次模型调用，已知总用量
          <strong>{{ fmtTokens(detail.total_tokens) }}</strong> Token。
        </p>
        <dl class="operation-meta">
          <dt>操作 ID</dt>
          <dd>{{ detail.operation.id }}</dd>
          <dt>关联对象</dt>
          <dd>
            {{ detail.operation.object_type || "—" }} /
            {{ detail.operation.object_id || "—" }}
          </dd>
        </dl>
        <article
          v-for="(row, index) in detail.items"
          :key="row.id"
          class="call-detail"
        >
          <div class="call-detail-title">
            <strong
              >{{ (detailPage - 1) * 100 + index + 1 }}.
              {{ label("actions", row.action) }}</strong
            ><span class="state-pill">{{ label("statuses", row.status) }}</span
            ><span>{{ fmtTokens(row.total_tokens) }} Token</span>
          </div>
          <p>
            {{ row.agent_name || "系统" }} · {{ row.provider }} /
            {{ row.requested_model }}
            <span v-if="row.actual_model">→ {{ row.actual_model }}</span>
          </p>
          <div class="detail-metrics">
            <span>输入 {{ fmtTokens(row.input_tokens) }}</span
            ><span>输出 {{ fmtTokens(row.output_tokens) }}</span
            ><span>缓存读 {{ fmtTokens(row.cache_read_tokens) }}</span
            ><span>缓存写 {{ fmtTokens(row.cache_creation_tokens) }}</span
            ><span>推理 {{ fmtTokens(row.reasoning_tokens) }}</span>
            ><span>{{ duration(row.duration_ms) }}</span>
          </div>
          <small
            >{{ triggerNames[row.trigger] }} ·
            {{ usageNames[row.usage_status] }} · 可见重试
            {{ row.retry_count }} 次<span v-if="row.error_type">
              · {{ row.error_type }}</span
            ></small
          >
          <details>
            <summary>追踪标识</summary>
            <p>调用：{{ row.id }}</p>
            <p>步骤：{{ row.step_id }}</p>
            <p>父步骤：{{ row.parent_step_id || "根步骤" }}</p>
            <p>供应商请求：{{ row.provider_request_id || "未返回" }}</p>
          </details>
        </article>
        <div class="pagination">
          <button
            class="btn"
            :disabled="detailPage === 1"
            @click="
              detailPage--;
              loadDetail();
            "
          >
            上一页</button
          ><span>{{ detailPage }}</span
          ><button
            class="btn"
            :disabled="detailPage * 100 >= detail.total"
            @click="
              detailPage++;
              loadDetail();
            "
          >
            下一页
          </button>
        </div></template
      >
    </dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onBeforeUnmount } from "vue";
import { ShieldCheck, Download, BarChart3, Info, X } from "lucide-vue-next";
import api from "../api";
const tabs = { overview: "用量总览", groups: "分类统计", calls: "调用审计" },
  dimensions = {
    source: "来源",
    action: "动作",
    model: "模型",
    provider: "供应商",
    user: "用户",
    workspace: "工作空间",
    agent: "Agent",
  };
const usageNames = {
    complete: "用量完整",
    partial: "部分用量",
    unknown: "用量未知",
  },
  triggerNames = {
    user: "用户操作",
    background: "后台处理",
    system: "系统任务",
  };
const options = ref({}),
  filters = ref({}),
  applied = ref(null),
  expanded = ref(false),
  tab = ref("overview"),
  grain = ref("day"),
  dimension = ref("source");
const summary = ref(null),
  groups = ref({ items: [], total: 0 }),
  calls = ref({ items: [], total: 0 }),
  ranks = ref([]),
  callPage = ref(1),
  groupPage = ref(1);
const loading = ref(false),
  callsLoading = ref(false),
  groupLoading = ref(false),
  exporting = ref(false),
  error = ref("");
const detailDialog = ref(null),
  detail = ref(null),
  detailLoading = ref(false),
  detailPage = ref(1);
const drillSnapshot = ref(null);
let operationId = "",
  mainSeq = 0,
  callSeq = 0,
  groupSeq = 0,
  detailSeq = 0;
const fmt = (n) =>
  n === null || n === undefined
    ? "未知"
    : Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
// Token 用量分级显示：≥1000 K、≥100 万 M、≥10 亿 B
const fmtTokens = (n) => {
  if (n === null || n === undefined) return "未知";
  const v = Number(n);
  if (!Number.isFinite(v)) return "未知";
  if (v >= 1e9) return `${(v / 1e9).toFixed(v >= 1e10 ? 0 : 1)} B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)} M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(v >= 1e5 ? 0 : 1)} K`;
  return String(Math.round(v));
};
const rate = (n) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(1)}%`;
const percent = (n, total) =>
  total ? Number((((n || 0) / total) * 100).toFixed(1)) : 0;
const tokensLabel = (n) =>
  n > 0 ? fmtTokens(n) : "";
const time = (s) =>
  s
    ? new Date(s).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—";
const duration = (n) =>
  n === null || n === undefined ? "—" : `${(n / 1000).toFixed(1)}s`;
const label = (key, value) => options.value[key]?.[value] || value;
const entries = (o) =>
  Object.entries(o || {}).map(([value, label]) => ({ value, label }));
const extraFields = computed(() => [
  { key: "action", label: "动作", items: entries(options.value.actions) },
  { key: "user_id", label: "用户", items: options.value.users },
  { key: "agent_id", label: "Agent", items: options.value.agents },
  { key: "provider", label: "供应商", items: options.value.providers },
  { key: "status", label: "执行状态", items: entries(options.value.statuses) },
  { key: "usage_status", label: "用量完整性", items: entries(usageNames) },
  { key: "trigger", label: "触发方式", items: entries(triggerNames) },
]);
const hasCalls = computed(() => summary.value?.totals.calls > 0);
const cards = computed(() => {
  const t = summary.value?.totals || {};
  return [
    {
      label: "已知总 Token",
      value: fmtTokens(t.total_tokens),
      hint: "仅供应商已返回的总量",
    },
    {
      label: "输入 / 输出",
      value: `${fmtTokens(t.input_tokens)} / ${fmtTokens(t.output_tokens)}`,
      hint: "缓存与推理细分不重复累加",
    },
    {
      label: "模型调用 / 业务操作",
      value: `${fmt(t.calls)} / ${fmt(t.operations)}`,
      hint: "同一操作可能调用模型多次",
    },
    {
      label: "用量完整率",
      value: rate(t.completeness),
      hint: `${t.unknown_calls || 0} 次未知 · ${(t.calls || 0) - (t.complete_calls || 0) - (t.unknown_calls || 0)} 次部分上报`,
    },
  ];
});
const collectorWarning = computed(() => {
  const h = summary.value?.health;
  if (!h) return "";
  if (h.last_error || h.write_failures)
    return `用量采集异常：${h.last_error || "曾发生本地写入失败"}。待入库 ${h.pending_records ?? "未知"} 条，本进程写入失败 ${h.write_failures} 次；当前报表可能不完整。`;
  if (h.pending_records)
    return `${h.pending_records} 条记录等待入库，可稍后刷新。`;
  return "";
});
const insight = computed(() => {
  const t = summary.value?.totals || {},
    top = ranks.value.find((r) => r.dimension === "source")?.items[0];
  return `${top ? `本期主要消耗来自${top.label}，占已知总用量 ${percent(top.total_tokens, t.total_tokens)}%。` : "当前范围暂无可比较的用量。"}共有 ${t.failed_calls || 0} 次失败、${t.interrupted_calls || 0} 次取消或中断；${(t.calls || 0) - (t.complete_calls || 0)} 次调用的用量未完整返回。`;
});
const trend = computed(() => {
  if (!summary.value || !applied.value) return [];
  const step = grain.value === "hour" ? 3600000 : 86400000;
  const map = new Map(
    summary.value.trend.map((p) => [new Date(p.bucket).getTime(), p]),
  );
  const result = [];
  for (
    let t = new Date(applied.value.start).getTime();
    t < new Date(applied.value.end).getTime();
    t += step
  ) {
    result.push(
      map.get(t) || {
        bucket: new Date(t).toISOString(),
        input_tokens: 0,
        output_tokens: 0,
        calls: 0,
      },
    );
  }
  return result;
});
const trendMax = computed(() =>
  Math.max(
    1,
    ...trend.value.flatMap((p) => [p.input_tokens || 0, p.output_tokens || 0]),
  ),
);
const height = (n) =>
  `${Math.max(n ? 1 : 0, ((n || 0) / trendMax.value) * 100)}%`;
const bucketLabel = (s) =>
  new Date(s).toLocaleString(
    "zh-CN",
    grain.value === "hour"
      ? { timeZone: "Asia/Shanghai", hour: "2-digit", hour12: false }
      : { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit" },
  );
function dateCN(date) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}
function range(days) {
  const end = new Date();
  filters.value.start = dateCN(new Date(end.getTime() - (days - 1) * 86400000));
  filters.value.end = dateCN(end);
}
function reset() {
  drillSnapshot.value = null;
  filters.value = Object.fromEntries(
    [
      "workspace_id",
      "source",
      "model",
      "action",
      "user_id",
      "agent_id",
      "provider",
      "status",
      "usage_status",
      "trigger",
    ].map((k) => [k, ""]),
  );
  range(7);
}
function params() {
  const p = { ...filters.value };
  p.start = `${p.start}T00:00:00+08:00`;
  p.end = new Date(
    new Date(`${p.end}T00:00:00+08:00`).getTime() + 86400000,
  ).toISOString();
  return Object.fromEntries(
    Object.entries(p).filter(([, v]) => v !== "" && v != null),
  );
}
function message(e) {
  return typeof e.response?.data?.detail === "string"
    ? e.response.data.detail
    : "查询失败，请稍后重试。";
}
async function applyFilters() {
  drillSnapshot.value = null;
  try {
    applied.value = params();
    callPage.value = groupPage.value = 1;
    await refresh();
  } catch (e) {
    error.value = "请选择有效的日期范围。";
  }
}
async function refresh() {
  if (!applied.value) return applyFilters();
  const seq = ++mainSeq;
  loading.value = true;
  error.value = "";
  try {
    const [s, models, sources, o] = await Promise.all([
      api.get("/admin/usage/summary", {
        params: { ...applied.value, grain: grain.value },
      }),
      api.get("/admin/usage/groups", {
        params: { ...applied.value, dimension: "model", page_size: 5 },
      }),
      api.get("/admin/usage/groups", {
        params: { ...applied.value, dimension: "source", page_size: 5 },
      }),
      api.get("/admin/usage/options"),
    ]);
    if (seq !== mainSeq) return;
    summary.value = s.data;
    options.value = o.data;
    ranks.value = [
      { dimension: "model", title: "模型消耗 Top 5", items: models.data.items },
      {
        dimension: "source",
        title: "来源消耗 Top 5",
        items: sources.data.items,
      },
    ];
    await Promise.all([loadGroups(), loadCalls()]);
  } catch (e) {
    if (seq === mainSeq) {
      error.value = message(e);
      summary.value = null;
    }
  } finally {
    if (seq === mainSeq) loading.value = false;
  }
}
async function loadGroups() {
  if (!applied.value) return;
  const seq = ++groupSeq;
  groupLoading.value = true;
  try {
    const { data } = await api.get("/admin/usage/groups", {
      params: {
        ...applied.value,
        dimension: dimension.value,
        page: groupPage.value,
      },
    });
    if (seq === groupSeq) groups.value = data;
  } catch (e) {
    if (seq === groupSeq) error.value = message(e);
  } finally {
    if (seq === groupSeq) groupLoading.value = false;
  }
}
async function loadCalls() {
  if (!applied.value) return;
  const seq = ++callSeq;
  callsLoading.value = true;
  try {
    const { data } = await api.get("/admin/usage/calls", {
      params: { ...applied.value, page: callPage.value },
    });
    if (seq === callSeq) calls.value = data;
  } catch (e) {
    if (seq === callSeq) error.value = message(e);
  } finally {
    if (seq === callSeq) callsLoading.value = false;
  }
}
function groupLabel(row) {
  return dimension.value === "workspace"
    ? options.value.workspaces?.find((w) => w.value === row.key)?.label ||
        row.label
    : row.label;
}
async function drill(dim, row) {
  const key =
    { user: "user_id", workspace: "workspace_id", agent: "agent_id" }[dim] ||
    dim;
  filters.value[key] = row.key ?? "__none__";
  expanded.value = true;
  tab.value = "calls";
  await applyFilters();
}
async function drillTime(point) {
  if (!drillSnapshot.value)
    drillSnapshot.value = {
      applied: { ...applied.value },
      filters: { ...filters.value },
    };
  const start = new Date(point.bucket),
    end = new Date(
      start.getTime() + (grain.value === "hour" ? 3600000 : 86400000),
    );
  applied.value = {
    ...applied.value,
    start: start.toISOString(),
    end: end.toISOString(),
  };
  filters.value.start = filters.value.end = dateCN(start);
  tab.value = "calls";
  callPage.value = 1;
  await refresh();
}
async function exportCsv() {
  exporting.value = true;
  try {
    const { data } = await api.get("/admin/usage/export", {
      params: applied.value,
      responseType: "blob",
    });
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = "模型用量.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    try {
      error.value = JSON.parse(await e.response.data.text()).detail;
    } catch {
      error.value = "导出失败，请缩小范围后重试。";
    }
  } finally {
    exporting.value = false;
  }
}
async function openOperation(id) {
  operationId = id;
  detailPage.value = 1;
  detail.value = null;
  detailDialog.value.showModal();
  await loadDetail();
}
async function loadDetail() {
  const seq = ++detailSeq;
  detailLoading.value = true;
  try {
    const { data } = await api.get(`/admin/usage/operations/${operationId}`, {
      params: { page: detailPage.value },
    });
    if (seq === detailSeq) detail.value = data;
  } catch (e) {
    error.value = message(e);
    detailDialog.value?.close();
  } finally {
    if (seq === detailSeq) detailLoading.value = false;
  }
}
function closeOnBackdrop(e) {
  if (e.target === detailDialog.value) {
    const r = e.target.getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      e.target.close();
  }
}
watch(tab, (v) => {
  if (v === "calls") loadCalls();
  if (v === "groups") loadGroups();
});
watch(tab, async (value) => {
  if (value === "overview" && drillSnapshot.value) {
    applied.value = drillSnapshot.value.applied;
    filters.value = drillSnapshot.value.filters;
    drillSnapshot.value = null;
    await refresh();
  }
});
onMounted(() => {
  reset();
  applyFilters();
});
onBeforeUnmount(() => {
  mainSeq++;
  callSeq++;
  groupSeq++;
  detailSeq++;
  detailDialog.value?.close();
});
</script>

<style scoped>
.usage-page {
  color: var(--text);
  min-width: 0;
}
.usage-toolbar,
.toolbar-actions,
.filter-footer,
.quick-ranges,
.panel-heading,
.pagination,
.chart-legend,
.call-detail-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.usage-toolbar {
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.toolbar-actions {
  margin-left: auto;
}
.scope-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
}
.muted,
.footnote,
small {
  color: var(--text3);
}
.muted {
  font-size: 12px;
}
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg, 14px);
  padding: 22px;
  min-width: 0;
}
.filter-row {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 14px;
}
.extra-filters {
  margin-top: 16px;
}
label {
  font-size: 12px;
  color: var(--text2);
  display: flex;
  flex-direction: column;
  gap: 7px;
}
input,
select {
  background: var(--surface2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 8px);
  padding: 9px 10px;
  min-width: 0;
  max-width: 100%;
  font: inherit;
}
input:focus-visible,
select:focus-visible,
button:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 3px;
}
.filter-footer {
  justify-content: space-between;
  margin-top: 18px;
}
.quick-ranges {
  flex-wrap: wrap;
  gap: 6px;
}
.range-button,
.text-link {
  background: none;
  border: 0;
  color: var(--primary);
  padding: 6px 8px;
  cursor: pointer;
  font-size: 12px;
}
.range-button:hover,
.text-link:hover {
  text-decoration: underline;
}
.usage-tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid var(--border);
  margin: 26px 0 20px;
}
.usage-tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text2);
  padding: 0 2px 13px;
  cursor: pointer;
  font-size: 14px;
}
.usage-tabs button.active {
  border-color: var(--primary);
  color: var(--text);
  font-weight: 650;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}
.metric {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.metric > span {
  color: var(--text2);
  font-size: 12px;
}
.metric strong {
  font-size: clamp(18px, 1.65vw, 28px);
  font-weight: 650;
  letter-spacing: -0.6px;
  overflow-wrap: anywhere;
}
.metric small {
  font-size: 11px;
  line-height: 1.6;
}
.panel-heading {
  justify-content: space-between;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.panel-heading h2 {
  font-size: 15px;
  font-weight: 650;
  margin: 0;
}
.panel-heading p {
  font-size: 12px;
  color: var(--text3);
  margin: 6px 0 0;
}
.chart-legend {
  font-size: 11px;
  margin-bottom: 10px;
}
.chart-legend span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.chart-legend i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
.input-dot,
.input-bar {
  background: var(--primary);
}
.output-dot,
.output-bar {
  background: var(--text3);
  opacity: 0.5;
}
.trend-scroll {
  overflow-x: auto;
}
.trend-chart {
  display: flex;
  height: 236px;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  padding-top: 30px;
}
.trend-column {
  flex: 1;
  min-width: 14px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text3);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.trend-column:hover {
  background: var(--surface2);
}
.bars {
  height: 180px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 3px;
  width: 75%;
}
.bar-stack {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  width: 50%;
  max-width: 28px;
  height: 100%;
}
.bar-stack > span {
  width: 100%;
  border-radius: 3px 3px 0 0;
}
.bar-value {
  font-size: 9px;
  line-height: 1.1;
  color: var(--text2);
  white-space: nowrap;
  padding-bottom: 2px;
  border-radius: 0;
  align-self: flex-end;
  transform: translateX(7px) rotate(-40deg);
  transform-origin: left bottom;
}
.bar-value:empty {
  display: none;
}
.trend-scroll {
  overflow-x: auto;
  scrollbar-width: none;
}
.trend-scroll::-webkit-scrollbar {
  display: none;
}
.axis-label {
  font-size: 10px;
  white-space: nowrap;
  padding-top: 9px;
}
.rank-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-top: 20px;
}
.rank-row {
  display: block;
  text-align: left;
  width: 100%;
  background: none;
  border: 0;
  color: var(--text);
  padding: 10px 0;
  cursor: pointer;
}
.rank-row:hover .rank-line {
  text-decoration: underline;
}
.rank-line {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  font-size: 13px;
}
.rank-line > span {
  overflow-wrap: anywhere;
}
.rank-track {
  height: 5px;
  background: var(--surface2);
  border-radius: 4px;
  display: block;
  margin: 9px 0 6px;
}
.rank-track > span {
  background: var(--primary);
  display: block;
  height: 5px;
  border-radius: 4px;
  min-width: 1px;
}
.rank-row small {
  font-size: 11px;
}
.insight {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin: 20px 0 0;
  font-size: 13px;
  line-height: 1.8;
}
.insight svg {
  flex-shrink: 0;
  margin-top: 3px;
  color: var(--primary);
}
.table-scroll {
  overflow: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  text-align: left;
}
th {
  color: var(--text3);
  font-weight: 500;
  background: var(--surface2);
  white-space: nowrap;
}
td,
th {
  padding: 13px 11px;
  border-bottom: 1px solid var(--border);
}
td small {
  display: block;
  font-size: 11px;
  margin-top: 5px;
  max-width: 240px;
  overflow-wrap: anywhere;
}
td .text-link {
  padding: 0;
  text-align: left;
}
.nowrap {
  white-space: nowrap;
}
tbody tr:hover {
  background: var(--surface2);
}
.state-pill {
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 8px;
  white-space: nowrap;
  display: inline-block;
}
.failed,
.cancelled,
.interrupted {
  font-weight: 650;
}
.pagination {
  justify-content: flex-end;
  margin-top: 18px;
  font-size: 12px;
}
.pagination > span:first-child {
  margin-right: auto;
}
.footnote {
  font-size: 11px;
  line-height: 1.9;
  margin: 20px 0;
}
.empty-state {
  min-height: 214px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text3);
  font-size: 12px;
}
.empty-state strong {
  color: var(--text2);
  font-size: 14px;
}
.empty-small {
  text-align: center;
  color: var(--text3);
  padding: 24px;
  font-size: 13px;
}
.usage-notice {
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--primary);
  background: var(--surface2);
  font-size: 13px;
  border-radius: 8px;
}
.usage-dialog {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 16px;
  width: min(820px, 90vw);
  max-height: 85dvh;
  overflow: auto;
  padding: 26px;
}
.usage-dialog::backdrop {
  background: var(--overlay, rgba(0, 0, 0, 0.45));
}
.usage-dialog p {
  font-size: 13px;
  line-height: 1.7;
}
.operation-meta {
  display: grid;
  grid-template-columns: 80px 1fr;
  font-size: 12px;
  gap: 10px;
  color: var(--text2);
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.call-detail {
  border-top: 1px solid var(--border);
  padding: 18px 0;
}
.call-detail-title {
  font-size: 13px;
  flex-wrap: wrap;
}
.call-detail-title > span:last-child {
  margin-left: auto;
}
.detail-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  margin-bottom: 10px;
}
.call-detail small {
  font-size: 11px;
}
.call-detail details {
  font-size: 11px;
  margin-top: 12px;
  color: var(--text3);
  overflow-wrap: anywhere;
}
.call-detail details p {
  font-size: 11px;
}
.call-detail summary {
  cursor: pointer;
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  white-space: nowrap;
}
button:disabled {
  opacity: 0.5;
  cursor: wait;
}
@media (max-width: 1100px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .filter-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 700px) {
  .filter-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .rank-grid {
    grid-template-columns: 1fr;
  }
  .panel {
    padding: 16px;
  }
  .metric-grid {
    gap: 10px;
  }
  .toolbar-actions {
    margin-left: 0;
  }
  .usage-toolbar > .muted {
    display: none;
  }
  .filter-footer {
    align-items: flex-end;
  }
  .panel-heading p {
    line-height: 1.6;
  }
  .pagination {
    gap: 8px;
  }
  .usage-dialog {
    padding: 18px;
  }
}
</style>
