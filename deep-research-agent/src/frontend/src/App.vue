<template>
  <main
    class="app-shell"
    :class="{
      expanded: isExpanded
    }"
  >
    <div class="aurora" aria-hidden="true">
      <span></span>
      <span></span>
      <span></span>
    </div>

    <!-- 初始状态：居中输入卡片 -->
    <div v-if="!isExpanded" class="layout layout-centered">
      <section class="panel panel-form panel-centered">
        <header class="panel-head">
          <div class="logo">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M12 2.5c-.7 0-1.4.2-2 .6L4.6 7C3.6 7.6 3 8.7 3 9.9v4.2c0 1.2.6 2.3 1.6 2.9l5.4 3.9c1.2.8 2.8.8 4 0l5.4-3.9c1-.7 1.6-1.7 1.6-2.9V9.9c0-1.2-.6-2.3-1.6-2.9L14 3.1a3.6 3.6 0 0 0-2-.6Z"
              />
            </svg>
          </div>
          <div>
            <h1>深度研究工作台</h1>
            <p>结合多轮智能检索与总结，实时呈现洞见与引用。</p>
          </div>
        </header>

        <form class="form" @submit.prevent="handleSubmit">
          <label class="field">
            <span>研究主题</span>
            <textarea
              v-model="form.topic"
              placeholder="例如：探索多模态模型在 2025 年的关键突破"
              rows="4"
              maxlength="200"
              required
            ></textarea>
          </label>

          <section class="options">
            <label class="field option">
              <span>搜索后端</span>
              <select v-model="form.searchApi">
                <option value="">沿用后端配置</option>
                <option
                  v-for="option in searchOptions"
                  :key="option"
                  :value="option"
                >
                  {{ option }}
                </option>
              </select>
            </label>
          </section>

          <div class="form-actions">
            <button class="submit" type="submit" :disabled="loading">
              <span class="submit-label">
                <svg
                  v-if="loading"
                  class="spinner"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="12" r="9" stroke-width="3" />
                </svg>
                {{ loading ? "研究进行中..." : "开始研究" }}
              </span>
            </button>
            <button
              v-if="loading"
              type="button"
              class="secondary-btn"
              @click="cancelResearch"
            >
              取消研究
            </button>
          </div>
        </form>

        <p v-if="error" class="error-chip">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path
              d="M10 3.2c-.3 0-.6.2-.8.5L3.4 15c-.4.7.1 1.6.8 1.6h11.6c.7 0 1.2-.9.8-1.6L10.8 3.7c-.2-.3-.5-.5-.8-.5Zm0 4.3c.4 0 .7.3.7.7v4c0 .4-.3.7-.7.7s-.7-.3-.7-.7V8.2c0-.4.3-.7.7-.7Zm0 6.6a1 1 0 1 1 0 2 1 1 0 0 1 0-2Z"
            />
          </svg>
          {{ error }}
        </p>
        <p v-else-if="loading" class="hint muted">
          正在收集线索与证据，实时进展见右侧区域。
        </p>
      </section>
    </div>

    <!-- 全屏状态：按 Figma Results Dashboard 还原 -->
    <div
      v-else
      :class="[
        'layout',
        'layout-fullscreen',
        isReportFirstVersion ? 'report-first-layout' : 'dashboard-layout'
      ]"
    >
      <ReportFirstWorkbench
        v-if="isReportFirstVersion"
        :topic="form.topic"
        :backend="form.searchApi"
        :loading="loading"
        :error="error"
        :tasks="todoTasks"
        :selected-view="reportFirstView"
        :selected-task-id="reportFirstSelectedTaskId"
        :completed-tasks="completedTasks"
        :total-tasks="totalTasks"
        :evaluator-score="artifactEvaluatorScore"
        :hard-error-count="artifactHardErrorCount"
        :quality-passed="readerQualityPassed"
        :quality-metrics="readerQualityMetrics"
        :report-ready="finalReportPreviewReady"
        :report-lines="reportMarkdownLines"
        :report-note-id="reportNoteId"
        :report-note-path="reportNotePath"
        :run-logs="progressLogs"
        :run-events="executionEvents"
        @select-task="selectReportFirstTask"
        @select-report="selectReportFirstReport"
        @select-evidence="selectReportFirstEvidence"
        @select-run-record="selectReportFirstRunRecord"
        @copy-note="copyNotePath"
        @new-research="startNewResearch"
        @back="goBack"
      />

      <section v-else class="dashboard-shell">
        <aside class="dashboard-sidebar">
          <button
            type="button"
            class="dashboard-brand"
            :disabled="loading"
            @click="goBack"
          >
            <span class="dashboard-brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M7 12h10M12 7v10" />
              </svg>
            </span>
            <span>
              <strong>深度研究</strong>
              <small>Deep Research</small>
            </span>
          </button>

          <nav class="dashboard-nav" aria-label="Research dashboard navigation">
            <a class="active" href="#overview">
              <span class="dashboard-nav-icon" aria-hidden="true">⌂</span>
              Overview
            </a>
            <a href="#research-tasks">
              <span class="dashboard-nav-icon" aria-hidden="true">▤</span>
              Research Tasks
            </a>
            <a href="#current-task">
              <span class="dashboard-nav-icon" aria-hidden="true">◎</span>
              Sources
            </a>
            <a href="#evaluator">
              <span class="dashboard-nav-icon" aria-hidden="true">◇</span>
              Evaluator
            </a>
            <a href="#report-preview">
              <span class="dashboard-nav-icon" aria-hidden="true">▱</span>
              Notes
            </a>
          </nav>

          <div class="dashboard-sidebar-spacer"></div>

          <section class="dashboard-baseline">
            <p>Current Baseline</p>
            <strong>{{ completedTasks }} / {{ totalTasks || 0 }}</strong>
            <div class="dashboard-progress-track">
              <span
                :style="{
                  width: `${totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0}%`
                }"
              ></span>
            </div>
            <small>
              {{ readerQualityPassed ? "All finished tasks passed quality checks." : "Research workflow is still collecting evidence." }}
            </small>
            <em>{{ artifactHardErrorCount }} hard citation errors</em>
          </section>

          <button type="button" class="dashboard-new-research" @click="startNewResearch">
            <span aria-hidden="true">＋</span>
            New Research
          </button>
        </aside>

        <section class="dashboard-main">
          <header id="overview" class="dashboard-hero">
            <div>
              <h1 :title="form.topic">{{ readerTopicTitle }}</h1>
              <p class="dashboard-subtitle">
                规划器拆解任务，并发检索多查询来源，报告器生成可追溯报告，质检器输出规则化质量指标。
              </p>
            </div>
            <div class="dashboard-hero-badges">
              <span>{{ form.searchApi || "hybrid" }}</span>
              <span class="success">
                <i></i>
                {{ completedTasks }}/{{ totalTasks || 0 }} 基线
              </span>
            </div>
          </header>

          <section class="dashboard-workspace">
            <article id="research-tasks" class="dashboard-card dashboard-task-list">
              <header class="dashboard-card-head">
                <h2>任务清单</h2>
                <p>规划器输出的可执行研究子任务。</p>
              </header>
              <ul v-if="todoTasks.length">
                <li
                  v-for="(task, index) in todoTasks"
                  :key="task.id"
                  :class="{ active: task.id === activeTaskId }"
                >
                  <button type="button" @click="activeTaskId = task.id">
                    <span class="dashboard-task-index">
                      {{ String(index + 1).padStart(2, "0") }}
                    </span>
                    <span class="dashboard-task-copy">
                      <strong>{{ task.title }}</strong>
                      <small>{{ formatTaskStatus(task.status) }}</small>
                    </span>
                  </button>
                </li>
              </ul>
              <div v-else class="dashboard-empty dashboard-empty-tasks">
                <span class="dashboard-empty-icon">▤</span>
                <strong>规划器正在拆解任务</strong>
                <p>研究任务生成后会依次显示在这里。</p>
              </div>
            </article>

            <article id="current-task" class="dashboard-card dashboard-current-task">
              <header class="dashboard-card-head dashboard-current-head">
                <div>
                  <h2>
                    <template v-if="currentTask">
                      任务 {{ Math.max(todoTasks.findIndex((task) => task.id === currentTask?.id) + 1, 1) }}：
                    </template>
                    {{ currentTaskTitle || "等待研究任务" }}
                  </h2>
                  <p>{{ currentTaskIntent || "围绕研究主题收集、筛选并总结可追溯证据。" }}</p>
                </div>
                <span v-if="currentTask" class="dashboard-task-state">
                  {{ formatTaskStatus(currentTask.status) }}
                </span>
              </header>

              <div v-if="currentTask" class="dashboard-task-insights">
                <span>已检索 {{ currentTaskSources.length }} 个来源</span>
                <span>高质量来源 {{ currentTaskStrongSourceCount }} 个</span>
                <span>引用 {{ currentTaskCitations.length }} 条</span>
                <span v-if="currentTaskNoteId || currentTaskNotePath">笔记已归档</span>
              </div>

              <section class="dashboard-stage-summary">
                <h3>阶段总结</h3>
                <p>
                  {{ currentTaskSummary || "研究进行中。检索器返回来源后，摘要代理会在这里生成本阶段的证据摘要。" }}
                </p>
              </section>
            </article>

            <aside id="evaluator" class="dashboard-card dashboard-evaluator">
              <h2>Evaluator</h2>
              <strong
                :class="['dashboard-score', { 'is-pending': !hasEvaluatorResult }]"
              >
                {{ artifactEvaluatorScore }}
              </strong>
              <p>Overall quality score</p>
              <div class="dashboard-metric-list">
                <div
                  v-for="metric in readerQualityMetrics"
                  :key="metric.key"
                  :class="`tone-${metric.tone}`"
                >
                  <span>{{ metric.label }}</span>
                  <strong>{{ metric.value }}</strong>
                </div>
              </div>
            </aside>
          </section>

          <section id="report-preview" class="dashboard-card dashboard-report-preview">
            <header>
              <h2>最终报告预览</h2>
              <button
                v-if="finalReportPreviewReady && reportNotePath"
                type="button"
                :title="reportNotePath"
                @click="copyNotePath(reportNotePath)"
              >
                {{ reportNoteId || "复制报告路径" }}
              </button>
            </header>

            <div v-if="error" class="dashboard-error">{{ error }}</div>

            <div v-if="finalReportPreviewReady" class="dashboard-report-body">
              <span
                v-for="(line, index) in reportMarkdownLines"
                :key="`${index}-${line.text.slice(0, 24)}`"
                :class="{ heading: line.isHeading }"
              >
                {{ line.text || "\u00a0" }}
              </span>
            </div>
            <div v-else class="dashboard-report-body dashboard-report-placeholder">
              <strong>## 结论摘要</strong>
              <p>
                {{ finalReportPlaceholderText }}
              </p>
              <strong>## 治理建议</strong>
              <p>阶段性证据请查看上方当前任务卡片；这里仅保留最终报告产物。</p>
            </div>
          </section>

        </section>
      </section>
    </div>

    <Transition name="copy-toast">
      <div
        v-if="noteCopyStatus"
        class="copy-toast"
        role="status"
        aria-live="polite"
      >
        {{ noteCopyStatus }}
      </div>
    </Transition>
  </main>
</template>

<script lang="ts" setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

import ReportFirstWorkbench from "./components/ReportFirstWorkbench.vue";
import {
  listBackends,
  startResearchStream,
  type ResearchEvent
} from "./services/api";

interface SourceItem {
  sourceId?: string;
  sourceType?: string;
  score?: string | number;
  scoreLabel?: string;
  domain?: string;
  searchQuery?: string;
  reasons: string[];
  title: string;
  url: string;
  snippet: string;
  raw: string;
}

interface ToolCallLog {
  eventId: number;
  agent: string;
  tool: string;
  businessStage: string;
  parameters: Record<string, unknown>;
  result: string;
  noteId: string | null;
  notePath: string | null;
  timestamp: number;
}

interface TraceSourceView {
  source_id: string;
  title: string;
  url: string;
  source_type: string;
  score: string | number;
  domain: string;
  search_query: string;
  reasons: string[];
}

interface TraceItemView {
  task_index: number;
  title: string;
  query: string;
  stage: string;
  source_count: number;
  backend: string;
  citations: string[];
  notices: string[];
  top_sources: TraceSourceView[];
  summary: string;
}

interface TodoTaskView {
  id: number;
  title: string;
  intent: string;
  query: string;
  status: string;
  summary: string;
  sourcesSummary: string;
  sourceItems: SourceItem[];
  citations: string[];
  notices: string[];
  noteId: string | null;
  notePath: string | null;
  toolCalls: ToolCallLog[];
}

type LogView = "logs" | "trace" | "quality";
type ScoreTone = "good" | "warn" | "danger" | "neutral";

interface EvaluatorScoreView {
  key: string;
  label: string;
  value: string;
  tone: ScoreTone;
  hint?: string;
}

interface EvaluatorScoreGroup {
  title: string;
  description: string;
  items: EvaluatorScoreView[];
}

const form = reactive({
  topic: "",
  searchApi: ""
});

const loading = ref(false);
const error = ref("");
const progressLogs = ref<string[]>([]);
const logsCollapsed = ref(false);
const activeLogView = ref<LogView>("logs");
const executionEvents = ref<ResearchEvent[]>([]);
const isExpanded = ref(false);
const isReportFirstVersion = true;

const todoTasks = ref<TodoTaskView[]>([]);
const activeTaskId = ref<number | null>(null);
const reportFirstView = ref<"task" | "report" | "evidence" | "run">("task");
const reportFirstTaskId = ref<number | null>(null);
const reportMarkdown = ref("");
const reportNoteId = ref("");
const reportNotePath = ref("");
const noteCopyStatus = ref("");
const traceItems = ref<TraceItemView[]>([]);
const evaluatorResult = ref<Record<string, unknown>>({});

const summaryHighlight = ref(false);
const sourcesHighlight = ref(false);
const reportHighlight = ref(false);
const toolHighlight = ref(false);

let stopCurrentStream: (() => void) | null = null;
const streamingLogKeys = new Set<string>();
let connectWatchTimer: number | null = null;
let noteCopyTimer: number | null = null;
let firstStreamEventReceived = false;
let streamErrorLogged = false;

const searchOptions = ref([
  "hybrid",
  "duckduckgo",
  "tavily",
  "serpapi"
]);

const TASK_STATUS_LABEL: Record<string, string> = {
  pending: "待执行",
  in_progress: "进行中",
  searching: "检索中",
  summarizing: "总结中",
  completed: "已完成",
  skipped: "已跳过",
  failed: "失败"
};

function formatTaskStatus(status: string): string {
  return TASK_STATUS_LABEL[status] ?? status;
}

const PERCENT_EVALUATOR_KEYS = new Set([
  "citation_precision",
  "citation_recall",
  "primary_source_ratio",
  "weak_source_ratio",
  "max_domain_concentration"
]);

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

function formatCompactNumber(value: number): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(2).replace(/\.?0+$/, "");
}

function formatPercentValue(value: number): string {
  const percent = value <= 1 ? value * 100 : value;
  const rounded = percent >= 10 ? percent.toFixed(1) : percent.toFixed(2);
  return `${rounded.replace(/\.?0+$/, "")}%`;
}

function formatEvaluatorMetric(key: string, fallback = "—"): string {
  const value = evaluatorResult.value[key];
  const numeric = toFiniteNumber(value);
  if (numeric !== null) {
    return PERCENT_EVALUATOR_KEYS.has(key)
      ? formatPercentValue(numeric)
      : formatCompactNumber(numeric);
  }
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return fallback;
}

function evaluatorTone(key: string, value: unknown): ScoreTone {
  const numeric = toFiniteNumber(value);
  if (numeric === null) {
    return "neutral";
  }

  const ratio = numeric > 1 ? numeric / 100 : numeric;
  if (key === "overall_score") {
    return numeric >= 90 ? "good" : numeric >= 75 ? "warn" : "danger";
  }
  if (key === "hard_error_count") {
    return numeric === 0 ? "good" : "danger";
  }
  if (key === "quality_warning_count" || key === "warning_count") {
    return numeric === 0 ? "good" : "warn";
  }
  if (key === "citation_precision" || key === "citation_recall") {
    return ratio >= 0.99 ? "good" : ratio >= 0.9 ? "warn" : "danger";
  }
  if (key === "primary_source_ratio") {
    return "neutral";
  }
  if (key === "weak_source_ratio") {
    return ratio <= 0.25 ? "good" : ratio <= 0.45 ? "warn" : "danger";
  }
  if (key === "max_domain_concentration") {
    return "neutral";
  }
  return "neutral";
}

function buildEvaluatorScoreItem(
  label: string,
  key: string,
  hint?: string
): EvaluatorScoreView | null {
  const rawValue = evaluatorResult.value[key];
  if (typeof rawValue !== "string" && typeof rawValue !== "number") {
    return null;
  }

  return {
    key,
    label,
    value: formatEvaluatorMetric(key),
    tone: evaluatorTone(key, rawValue),
    hint
  };
}

const totalTasks = computed(() => todoTasks.value.length);
const terminalTaskStatuses = new Set(["completed", "skipped", "failed"]);
const completedTasks = computed(() =>
  todoTasks.value.filter((task) => terminalTaskStatuses.has(task.status)).length
);
const allResearchTasksFinished = computed(() =>
  totalTasks.value > 0 && completedTasks.value >= totalTasks.value
);

const hasEvaluatorResult = computed(() => Object.keys(evaluatorResult.value).length > 0);

const taskNoteCount = computed(() =>
  todoTasks.value.filter((task) => Boolean(task.noteId || task.notePath)).length
);

const hasRunArtifacts = computed(() =>
  taskNoteCount.value > 0 ||
  Boolean(reportNoteId.value || reportNotePath.value) ||
  hasEvaluatorResult.value
);

const artifactEvaluatorScore = computed(() =>
  formatEvaluatorMetric("overall_score", "Pending")
);
const artifactHardErrorCount = computed(() =>
  formatEvaluatorMetric("hard_error_count", "0")
);
const artifactQualityWarningCount = computed(() =>
  formatEvaluatorMetric("quality_warning_count", formatEvaluatorMetric("warning_count", "0"))
);

const currentRunId = computed(() => executionEvents.value[0]?.run_id || "");
const shortRunId = computed(() =>
  currentRunId.value ? currentRunId.value.slice(0, 8) : ""
);

const readerTopicTitle = computed(() => {
  const topic = (form.topic || "研究报告").trim().replace(/\s+/g, " ");
  const characters = Array.from(topic);
  const displayLimit = 48;

  return characters.length > displayLimit
    ? `${characters.slice(0, displayLimit).join("")}…`
    : topic;
});

const reportMarkdownLines = computed(() =>
  reportMarkdown.value.split("\n").map((text) => ({
    text,
    isHeading: /^#{1,6}\s+/.test(text),
    isBlank: !text.trim()
  }))
);
const finalReportPreviewReady = computed(() =>
  allResearchTasksFinished.value && reportMarkdown.value.trim().length > 0
);
const finalReportPlaceholderText = computed(() => {
  if (!totalTasks.value) {
    return "任务规划完成前，最终报告预览保持空白。";
  }
  if (!allResearchTasksFinished.value) {
    return `研究任务进行中（${completedTasks.value}/${totalTasks.value}）。当前任务总结请查看上方中间卡片，最终报告将在全部任务完成后展示。`;
  }
  return "所有研究任务已完成，报告器正在整合最终报告。";
});

const readerStatusText = computed(() => {
  if (loading.value) {
    return "running";
  }
  if (error.value) {
    return "failed";
  }
  if (completedTasks.value > 0 && completedTasks.value >= (totalTasks.value || 1)) {
    return "completed";
  }
  return "ready";
});

const readerQualityPassed = computed(() => {
  if (error.value) {
    return false;
  }

  const hardErrors = toFiniteNumber(evaluatorResult.value.hard_error_count);
  if (hardErrors !== null) {
    return hardErrors === 0;
  }

  return !loading.value && completedTasks.value > 0;
});

const readerQualityStatusText = computed(() => {
  if (loading.value) {
    return "质量检查中";
  }
  if (error.value) {
    return "质量异常";
  }
  if (readerQualityPassed.value) {
    return "质量通过";
  }
  return "待质检";
});

const readerQualityMetrics = computed<EvaluatorScoreView[]>(() => {
  const fields: Array<[string, string]> = [
    ["Citation Precision", "citation_precision"],
    ["Citation Recall", "citation_recall"],
    ["Primary Sources", "primary_source_ratio"],
    ["Weak Sources", "weak_source_ratio"],
    ["Domain Concentration", "max_domain_concentration"],
    ["Hard Errors", "hard_error_count"]
  ];

  return fields.map(([label, key]) => {
    const rawValue = evaluatorResult.value[key];
    return {
      key,
      label,
      value: formatEvaluatorMetric(key),
      tone: evaluatorTone(key, rawValue)
    };
  });
});

const readerEvidenceSources = computed(() => {
  if (currentTaskSources.value.length) {
    return currentTaskSources.value.slice(0, 3);
  }

  return todoTasks.value
    .flatMap((task) => task.sourceItems)
    .slice(0, 3);
});

const readerAllSources = computed(() => {
  const seen = new Set<string>();
  return todoTasks.value.flatMap((task) => task.sourceItems).filter((source) => {
    const key = source.sourceId || source.url || source.title;
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
});

const readerTotalSourceCount = computed(() => readerAllSources.value.length);
const readerCitedSourceCount = computed(() => {
  const citationIds = new Set(
    todoTasks.value
      .flatMap((task) => task.citations)
      .map((citation) => citation.trim())
      .filter(Boolean)
  );

  return Math.min(citationIds.size, readerTotalSourceCount.value);
});

const hasDebugContent = computed(() =>
  progressLogs.value.length > 0 ||
  executionEvents.value.length > 0 ||
  displayTraceItems.value.length > 0 ||
  hasEvaluatorResult.value
);

const evaluatorScoreGroups = computed<EvaluatorScoreGroup[]>(() => {
  const groups: Array<{
    title: string;
    description: string;
    fields: Array<[string, string, string?]>;
  }> = [
    {
      title: "引用结构",
      description: "重点看引用是否能追溯、是否存在硬错误。",
      fields: [
        ["总分", "overall_score", "规则质检综合分"],
        ["硬错误", "hard_error_count", "应保持为 0"],
        ["引用准确率", "citation_precision", "正文引用是否存在于来源集合"],
        ["证据使用率", "citation_recall", "参考文献/证据表覆盖情况"]
      ]
    },
    {
      title: "来源质量",
      description: "重点看主来源比例、弱来源比例和域名集中度。",
      fields: [
        ["主来源占比", "primary_source_ratio", "academic / official_doc / company_tech"],
        ["Weak 来源占比", "weak_source_ratio", "unknown / blog / marketing 越低越好"],
        ["域名集中度", "max_domain_concentration", "避免正文引用过度依赖单一域名"],
        ["唯一域名数", "unique_domain_count", "来源多样性"]
      ]
    },
    {
      title: "基础统计",
      description: "辅助排查报告规模和引用覆盖。",
      fields: [
        ["引用数", "citations_count"],
        ["唯一引用来源", "unique_citations_count"],
        ["参考文献来源", "reference_sources_count"],
        ["证据来源", "evidence_sources_count"],
        ["质量提醒", "quality_warning_count"]
      ]
    }
  ];

  return groups
    .map((group) => ({
      ...group,
      items: group.fields
        .map(([label, key, hint]) => buildEvaluatorScoreItem(label, key, hint))
        .filter((item): item is EvaluatorScoreView => item !== null)
    }))
    .filter((group) => group.items.length > 0);
});

const evaluatorWarnings = computed(() => {
  const warnings = evaluatorResult.value.warnings;
  if (!Array.isArray(warnings)) {
    return [];
  }
  return warnings.map((item) => String(item)).filter(Boolean);
});

const evaluatorJson = computed(() => formatJsonValue(evaluatorResult.value, 5000));

const liveTraceItems = computed<TraceItemView[]>(() =>
  todoTasks.value.map((task, index) => ({
    task_index: index + 1,
    title: task.title,
    query: task.query,
    stage: task.status,
    source_count: task.sourceItems.length,
    backend: form.searchApi || "hybrid",
    citations: task.citations,
    notices: task.notices,
    top_sources: task.sourceItems.map((source, sourceIndex) => ({
      source_id: source.sourceId || `T${task.id}-S${sourceIndex + 1}`,
      title: source.title,
      url: source.url,
      source_type: source.sourceType || "unknown",
      score: source.score ?? "",
      domain: source.domain || "",
      search_query: source.searchQuery || "",
      reasons: source.reasons.length ? source.reasons : source.raw ? [source.raw] : []
    })),
    summary: task.summary
  }))
);

const displayTraceItems = computed(() =>
  traceItems.value.length ? traceItems.value : liveTraceItems.value
);

const currentTask = computed(() => {
  if (activeTaskId.value !== null) {
    return todoTasks.value.find((task) => task.id === activeTaskId.value) ?? null;
  }
  return todoTasks.value[0] ?? null;
});

const reportFirstSelectedTaskId = computed(() => {
  if (
    reportFirstTaskId.value !== null &&
    todoTasks.value.some((task) => task.id === reportFirstTaskId.value)
  ) {
    return reportFirstTaskId.value;
  }
  return todoTasks.value[0]?.id ?? null;
});

function selectReportFirstTask(taskId: number): void {
  reportFirstTaskId.value = taskId;
  reportFirstView.value = "task";
}

function selectReportFirstReport(): void {
  reportFirstView.value = "report";
}

function selectReportFirstEvidence(): void {
  reportFirstView.value = "evidence";
}

function selectReportFirstRunRecord(): void {
  reportFirstView.value = "run";
}

const currentTaskSources = computed(() => currentTask.value?.sourceItems ?? []);
const currentTaskStrongSourceCount = computed(() =>
  currentTaskSources.value.filter((source) =>
    ["academic", "official_doc", "company_tech"].includes(
      (source.sourceType || "").toLowerCase()
    )
  ).length
);
const currentTaskSummary = computed(() => currentTask.value?.summary ?? "");
const currentTaskTitle = computed(() => currentTask.value?.title ?? "");
const currentTaskIntent = computed(() => currentTask.value?.intent ?? "");
const currentTaskQuery = computed(() => currentTask.value?.query ?? "");
const currentTaskCitations = computed(() => currentTask.value?.citations ?? []);
const currentTaskNotices = computed(() => currentTask.value?.notices ?? []);
const currentTaskNoteId = computed(() => currentTask.value?.noteId ?? "");
const currentTaskNotePath = computed(() => currentTask.value?.notePath ?? "");
const currentTaskToolCalls = computed(
  () => currentTask.value?.toolCalls ?? []
);
const currentTaskNoteToolCalls = computed(() =>
  currentTaskToolCalls.value.filter(isNoteServiceEntry)
);
const currentTaskOtherToolCalls = computed(() =>
  currentTaskToolCalls.value.filter((entry) => !isNoteServiceEntry(entry))
);

const pulse = (flag: typeof summaryHighlight) => {
  flag.value = false;
  requestAnimationFrame(() => {
    flag.value = true;
    window.setTimeout(() => {
      flag.value = false;
    }, 1200);
  });
};

function truncateText(value: string, max = 520): string {
  const trimmed = value.trim();
  return trimmed.length > max ? `${trimmed.slice(0, max)}…` : trimmed;
}

function formatSourceScore(value: unknown): string {
  const numeric = toFiniteNumber(value);
  if (numeric !== null) {
    return `评分 ${formatCompactNumber(numeric)}`;
  }
  if (typeof value === "string" && value.trim()) {
    return value.trim().startsWith("评分") ? value.trim() : `评分 ${value.trim()}`;
  }
  return "";
}

function sourceTypeTone(sourceType: string | undefined): string {
  const normalized = (sourceType || "").toLowerCase();
  if (["academic", "official_doc", "company_tech"].includes(normalized)) {
    return "source-type-strong";
  }
  if (["blog", "unknown", "marketing"].includes(normalized)) {
    return "source-type-weak";
  }
  return "source-type-neutral";
}

function visibleSourceReasons(item: SourceItem): string[] {
  return item.reasons.slice(0, 4);
}

function hasSourceDetail(item: SourceItem): boolean {
  return Boolean(
    item.searchQuery ||
      item.snippet ||
      item.reasons.length ||
      item.raw
  );
}

function parseSources(raw: string): SourceItem[] {
  if (!raw) {
    return [];
  }

  const items: SourceItem[] = [];
  const lines = raw.split("\n");

  let current: SourceItem | null = null;
  const flush = () => {
    if (!current) {
      return;
    }
    const normalized: SourceItem = {
      sourceId: "",
      sourceType: "",
      score: "",
      scoreLabel: "",
      domain: "",
      searchQuery: "",
      reasons: [],
      title: current.title?.trim() || "",
      url: current.url?.trim() || "",
      snippet: current.snippet ? truncateText(current.snippet, 360) : "",
      raw: current.raw ? truncateText(current.raw, 420) : ""
    };

    if (
      normalized.title ||
      normalized.url ||
      normalized.snippet ||
      normalized.raw
    ) {
      if (!normalized.title && normalized.url) {
        normalized.title = normalized.url;
      }
      items.push(normalized);
    }
    current = null;
  };

  const ensureCurrent = () => {
    if (!current) {
      current = {
        title: "",
        url: "",
        snippet: "",
        raw: "",
        reasons: []
      };
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    if (/^\*/.test(trimmed) && trimmed.includes(" : ")) {
      flush();
      const withoutBullet = trimmed.replace(/^\*\s*/, "");
      const [titlePart, urlPart] = withoutBullet.split(" : ");
      current = {
        title: titlePart?.trim() || "",
        url: urlPart?.trim() || "",
        snippet: "",
        raw: "",
        reasons: []
      };
      continue;
    }

    if (/^(Source|信息来源)\s*:/.test(trimmed)) {
      flush();
      const [, titlePart = ""] = trimmed.split(/:\s*(.+)/);
      current = {
        title: titlePart.trim(),
        url: "",
        snippet: "",
        raw: "",
        reasons: []
      };
      continue;
    }

    if (/^URL\s*:/.test(trimmed)) {
      ensureCurrent();
      const [, urlPart = ""] = trimmed.split(/:\s*(.+)/);
      current!.url = urlPart.trim();
      continue;
    }

    if (
      /^(Most relevant content from source|信息内容)\s*:/.test(trimmed)
    ) {
      ensureCurrent();
      const [, contentPart = ""] = trimmed.split(/:\s*(.+)/);
      current!.snippet = contentPart.trim();
      continue;
    }

    if (
      /^(Full source content limited to|信息内容限制为)\s*:/.test(trimmed)
    ) {
      ensureCurrent();
      const [, rawPart = ""] = trimmed.split(/:\s*(.+)/);
      current!.raw = rawPart.trim();
      continue;
    }

    if (/^https?:\/\//.test(trimmed)) {
      ensureCurrent();
      if (!current!.url) {
        current!.url = trimmed;
        continue;
      }
    }

    ensureCurrent();
    current!.raw = current!.raw ? `${current!.raw}\n${trimmed}` : trimmed;
  }

  flush();
  return items;
}

function extractOptionalString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function ensureRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function applyNoteMetadata(
  task: TodoTaskView,
  payload: Record<string, unknown>
): void {
  const noteId = extractOptionalString(payload.note_id);
  if (noteId) {
    task.noteId = noteId;
  }
  const notePath = extractOptionalString(payload.note_path);
  if (notePath) {
    task.notePath = notePath;
  }
}

function applyReportNoteMetadata(
  payload: Record<string, unknown>,
  event?: ResearchEvent
): void {
  const noteType = extractOptionalString(payload.note_type);
  const label = extractOptionalString(payload.label) || event?.message || "";
  const isReportNote =
    noteType === "report" ||
    event?.stage === "reporter" ||
    label.includes("报告") ||
    label.toLowerCase().includes("report");

  if (!isReportNote) {
    return;
  }

  const noteId = extractOptionalString(payload.note_id);
  const notePath = extractOptionalString(payload.note_path);
  if (noteId) {
    reportNoteId.value = noteId;
  }
  if (notePath) {
    reportNotePath.value = notePath;
  }
}

function formatToolParameters(parameters: Record<string, unknown>): string {
  try {
    return JSON.stringify(parameters, null, 2);
  } catch (error) {
    console.warn("无法格式化工具参数", error, parameters);
    return Object.entries(parameters)
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join("\n");
  }
}

function formatToolResult(result: string): string {
  const trimmed = result.trim();
  const limit = 900;
  if (trimmed.length > limit) {
    return `${trimmed.slice(0, limit)}…`;
  }
  return trimmed;
}

function isNoteServiceEntry(entry: ToolCallLog): boolean {
  return entry.agent === "NoteService" && entry.tool === "note";
}

function formatNoteToolLabel(entry: ToolCallLog): string {
  const stage = entry.businessStage || String(entry.parameters.stage || "");
  const action = String(entry.parameters.action || "");

  if (stage === "planner") {
    return "planner 创建笔记";
  }
  if (stage === "searcher") {
    return "search 更新来源";
  }
  if (stage === "summary") {
    return "summary 更新总结";
  }
  if (stage === "task") {
    return "task 归档笔记";
  }
  if (stage === "reporter") {
    return action === "create" ? "report 创建报告笔记" : "report 关联报告";
  }

  return action === "create" ? "创建笔记" : "更新笔记";
}

function formatNoteStage(entry: ToolCallLog): string {
  const stage = entry.businessStage || String(entry.parameters.stage || "");
  const labels: Record<string, string> = {
    planner: "规划",
    searcher: "检索",
    summary: "总结",
    reporter: "报告",
    task: "任务"
  };
  return labels[stage] || stage || "未知";
}

function formatNoteAction(entry: ToolCallLog): string {
  const action = String(entry.parameters.action || "");
  const labels: Record<string, string> = {
    create: "创建",
    update: "更新"
  };
  return labels[action] || action || "记录";
}

function formatNotePreview(entry: ToolCallLog): string {
  const preview = entry.parameters.content_preview;
  if (typeof preview !== "string") {
    return "";
  }
  return preview.trim();
}

function formatJsonValue(value: unknown, limit = 2400): string {
  try {
    const formatted = JSON.stringify(
      value,
      (_key, nestedValue) => {
        if (typeof nestedValue === "string" && nestedValue.length > 900) {
          return `${nestedValue.slice(0, 900)}…`;
        }
        return nestedValue;
      },
      2
    );
    return formatted.length > limit
      ? `${formatted.slice(0, limit)}\n...（已截断）`
      : formatted;
  } catch (error) {
    console.warn("无法格式化 JSON", error, value);
    return String(value);
  }
}

function formatEventTime(timestamp: number | undefined): string {
  if (!timestamp) {
    return "";
  }

  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatEventPayload(event: ResearchEvent): string {
  const payload = event.payload || {};
  const detail: Record<string, unknown> = {};

  if (Object.keys(payload).length) {
    detail.payload = payload;
  }
  if (event.error) {
    detail.error = event.error;
  }

  return Object.keys(detail).length ? formatJsonValue(detail) : "";
}

function recordExecutionEvent(event: ResearchEvent): void {
  // token 级 delta 高频刷新，完整进入事件表会影响页面滚动和渲染。
  if (event.type === "llm_delta" || event.type === "llm_reasoning_delta") {
    return;
  }

  executionEvents.value.push({
    ...event,
    payload: event.payload ? { ...event.payload } : {},
    error: event.error ? { ...event.error } : null
  });

  if (executionEvents.value.length > 300) {
    executionEvents.value.splice(0, executionEvents.value.length - 300);
  }
}

function normalizeTraceSource(value: unknown): TraceSourceView | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const source = value as Record<string, unknown>;
  const reasons = Array.isArray(source.reasons)
    ? source.reasons.map((item) => String(item)).filter(Boolean)
    : [];

  return {
    source_id: typeof source.source_id === "string" ? source.source_id : "",
    title: typeof source.title === "string" ? source.title : "",
    url: typeof source.url === "string" ? source.url : "",
    source_type: typeof source.source_type === "string" ? source.source_type : "",
    score:
      typeof source.score === "number" || typeof source.score === "string"
        ? source.score
        : 0,
    domain: typeof source.domain === "string" ? source.domain : "",
    search_query:
      typeof source.search_query === "string" ? source.search_query : "",
    reasons
  };
}

function normalizeTraceItems(value: unknown): TraceItemView[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return null;
      }

      const trace = item as Record<string, unknown>;
      const topSources = Array.isArray(trace.top_sources)
        ? trace.top_sources
            .map(normalizeTraceSource)
            .filter((source): source is TraceSourceView => source !== null)
        : [];
      const notices = Array.isArray(trace.notices)
        ? trace.notices.map((notice) => String(notice)).filter(Boolean)
        : [];
      // Trace 里的 citations 来自后端任务状态，表示这条任务总结可追溯到哪些 source_id。
      // 它和正文里的引用不是一回事：正文保持可读，排查问题时看这里就能回到具体来源。
      const citations = Array.isArray(trace.citations)
        ? trace.citations
            .map((citation) => String(citation).trim())
            .filter((citation) => citation.length > 0)
        : [];

      return {
        task_index: toNumberId(trace.task_index, index + 1),
        title: typeof trace.title === "string" ? trace.title : "",
        query: typeof trace.query === "string" ? trace.query : "",
        stage: typeof trace.stage === "string" ? trace.stage : "unknown",
        source_count: toNumberId(trace.source_count, topSources.length),
        backend: typeof trace.backend === "string" ? trace.backend : "unknown",
        citations,
        notices,
        top_sources: topSources,
        summary: typeof trace.summary === "string" ? trace.summary : ""
      };
    })
    .filter((item): item is TraceItemView => item !== null);
}

async function copyNotePath(path: string | null | undefined) {
  if (!path) {
    return;
  }

  function showCopyToast(message: string) {
    noteCopyStatus.value = message;
    if (noteCopyTimer !== null) {
      window.clearTimeout(noteCopyTimer);
    }
    noteCopyTimer = window.setTimeout(() => {
      noteCopyStatus.value = "";
      noteCopyTimer = null;
    }, 1800);
  }

  function fallbackCopyText(value: string): boolean {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    document.body.appendChild(textarea);
    textarea.select();

    try {
      return document.execCommand("copy");
    } finally {
      document.body.removeChild(textarea);
    }
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(path);
    } else if (!fallbackCopyText(path)) {
      throw new Error("clipboard api unavailable");
    }
    showCopyToast("已复制笔记路径");
    progressLogs.value.push(`已复制笔记路径：${path}`);
  } catch (error) {
    console.warn("无法直接复制到剪贴板", error);
    if (fallbackCopyText(path)) {
      showCopyToast("已复制笔记路径");
      progressLogs.value.push(`已复制笔记路径：${path}`);
    } else {
      showCopyToast("请手动复制笔记路径");
      window.prompt("复制以下笔记路径", path);
      progressLogs.value.push("请手动复制笔记路径");
    }
  }
}

function resetWorkflowState() {
  todoTasks.value = [];
  activeTaskId.value = null;
  reportFirstView.value = "task";
  reportFirstTaskId.value = null;
  reportMarkdown.value = "";
  reportNoteId.value = "";
  reportNotePath.value = "";
  noteCopyStatus.value = "";
  traceItems.value = [];
  evaluatorResult.value = {};
  progressLogs.value = [];
  executionEvents.value = [];
  activeLogView.value = "logs";
  streamingLogKeys.clear();
  firstStreamEventReceived = false;
  streamErrorLogged = false;
  if (connectWatchTimer !== null) {
    window.clearTimeout(connectWatchTimer);
    connectWatchTimer = null;
  }
  summaryHighlight.value = false;
  sourcesHighlight.value = false;
  reportHighlight.value = false;
  toolHighlight.value = false;
  logsCollapsed.value = false;
}

function findTask(taskId: unknown): TodoTaskView | undefined {
  const numeric =
    typeof taskId === "number"
      ? taskId
      : typeof taskId === "string"
      ? Number(taskId)
      : NaN;
  if (Number.isNaN(numeric)) {
    return undefined;
  }
  return todoTasks.value.find((task) => task.id === numeric);
}

function upsertTaskMetadata(task: TodoTaskView, payload: Record<string, unknown>) {
  if (typeof payload.title === "string" && payload.title.trim()) {
    task.title = payload.title.trim();
  }
  if (typeof payload.intent === "string" && payload.intent.trim()) {
    task.intent = payload.intent.trim();
  }
  if (typeof payload.query === "string" && payload.query.trim()) {
    task.query = payload.query.trim();
  }
}

function toNumberId(value: unknown, fallback: number): number {
  const numeric =
    typeof value === "number"
      ? value
      : typeof value === "string"
      ? Number(value)
      : fallback;

  return Number.isFinite(numeric) ? Number(numeric) : fallback;
}

function sourceItemsFromResults(value: unknown): SourceItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .filter((item): item is Record<string, unknown> => {
      return Boolean(item && typeof item === "object" && !Array.isArray(item));
    })
    .map((item, index) => {
      const sourceId = typeof item.source_id === "string" ? item.source_id : "";
      const title = typeof item.title === "string" && item.title.trim()
        ? item.title.trim()
        : sourceId || `来源 ${index + 1}`;
      const url = typeof item.url === "string" ? item.url : "";
      const content = typeof item.content === "string" ? item.content : "";
      const sourceType = typeof item.source_type === "string" ? item.source_type : "unknown";
      const score =
        typeof item.score === "number" || typeof item.score === "string"
          ? item.score
          : "";
      const scoreLabel = formatSourceScore(score);
      const domain = typeof item.domain === "string" ? item.domain : "";
      const searchQuery =
        typeof item.search_query === "string" ? item.search_query : "";
      const reasons = Array.isArray(item.reasons)
        ? item.reasons.map((reason) => String(reason)).filter(Boolean)
        : [];
      // 后端 source_quality.py 已经给每条来源打了类型、分数和原因；
      // 前端这里只做轻量格式化，方便演示“为什么保留这条来源”。
      const snippetParts = [sourceId, sourceType, scoreLabel, domain].filter(Boolean);

      return {
        sourceId,
        sourceType,
        score,
        scoreLabel,
        domain,
        searchQuery,
        reasons,
        title,
        url,
        snippet: snippetParts.join(" · "),
        raw: truncateText(content)
      };
    });
}

function normalizeTaskSnapshot(value: unknown, index = 0): TodoTaskView | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const item = value as Record<string, unknown>;
  const id = toNumberId(item.id, index + 1);
  const sourceSummary =
    typeof item.source_summary === "string" ? item.source_summary : "";
  const sourceItems = sourceItemsFromResults(item.search_results);
  const citations = Array.isArray(item.citations)
    ? item.citations.filter((citation): citation is string => {
        return typeof citation === "string" && citation.trim().length > 0;
      })
    : sourceItems
        .map((source) => source.sourceId || "")
        .filter((sourceId): sourceId is string => sourceId.length > 0);

  return {
    id,
    title:
      typeof item.title === "string" && item.title.trim()
        ? item.title.trim()
        : `任务${id}`,
    intent:
      typeof item.intent === "string" && item.intent.trim()
        ? item.intent.trim()
        : "探索与主题相关的关键信息",
    query:
      typeof item.query === "string" && item.query.trim()
        ? item.query.trim()
        : form.topic.trim(),
    status:
      typeof item.status === "string" && item.status.trim()
        ? item.status.trim()
        : "pending",
    summary: typeof item.summary === "string" ? item.summary : "",
    sourcesSummary: sourceSummary,
    sourceItems: sourceItems.length ? sourceItems : parseSources(sourceSummary),
    citations,
    notices: Array.isArray(item.notices)
      ? item.notices.filter((notice): notice is string => typeof notice === "string")
      : [],
    noteId: extractOptionalString(item.note_id),
    notePath: extractOptionalString(item.note_path),
    toolCalls: []
  };
}

function upsertTaskFromSnapshot(
  value: unknown,
  index = 0,
  options: { preserveStatus?: boolean } = {}
): TodoTaskView | null {
  const next = normalizeTaskSnapshot(value, index);
  if (!next) {
    return null;
  }

  const existing = findTask(next.id);
  if (!existing) {
    todoTasks.value.push(next);
    return next;
  }

  const oldToolCalls = existing.toolCalls;
  const oldStatus = existing.status;
  Object.assign(existing, next);
  existing.toolCalls = oldToolCalls;
  if (options.preserveStatus) {
    existing.status = oldStatus;
  }
  return existing;
}

function replaceTasks(values: unknown): void {
  if (!Array.isArray(values)) {
    return;
  }

  todoTasks.value = values
    .map((item, index) => normalizeTaskSnapshot(item, index))
    .filter((item): item is TodoTaskView => item !== null);

  if (todoTasks.value.length && activeTaskId.value === null) {
    activeTaskId.value = todoTasks.value[0].id;
  }
}

function mergeTasks(values: unknown): void {
  if (!Array.isArray(values)) {
    return;
  }

  values.forEach((item, index) => {
    upsertTaskFromSnapshot(item, index, { preserveStatus: true });
  });

  if (todoTasks.value.length && activeTaskId.value === null) {
    activeTaskId.value = todoTasks.value[0].id;
  }
}

function readTaskPayload(event: ResearchEvent): unknown {
  return event.payload.task;
}

function ensureActiveTask(preferredId?: number | null): void {
  if (!todoTasks.value.length) {
    activeTaskId.value = null;
    return;
  }

  const currentStillExists = todoTasks.value.some((task) => task.id === activeTaskId.value);
  if (currentStillExists) {
    return;
  }

  const preferred = preferredId == null
    ? null
    : todoTasks.value.find((task) => task.id === preferredId);
  activeTaskId.value = preferred?.id ?? todoTasks.value[0].id;
}

function appendLog(event: ResearchEvent): void {
  if (event.type === "llm_delta" || event.type === "llm_reasoning_delta") {
    return;
  }

  if (event.message) {
    progressLogs.value.push(event.message);
  }
}

function appendStreamingLog(event: ResearchEvent): void {
  const payload = event.payload || {};
  const streamKey = typeof payload.stream_key === "string" ? payload.stream_key : event.agent || event.stage;
  const action = event.type === "llm_reasoning_delta" ? "思考" : "生成";
  const key = `${streamKey}:${event.type}`;

  if (streamingLogKeys.has(key)) {
    return;
  }

  streamingLogKeys.add(key);
  progressLogs.value.push(`${event.agent || streamKey} 正在${action}...`);
}

function applyStreamingDelta(event: ResearchEvent): void {
  appendStreamingLog(event);

  if (event.type !== "llm_delta") {
    return;
  }

  const delta = event.payload?.delta;
  if (typeof delta !== "string" || !delta) {
    return;
  }

  const businessStage = event.payload?.business_stage;
  if (businessStage === "summary") {
    const task = findTask(event.task_id);
    if (task) {
      // 流式 delta 只负责追加内容，不负责切换任务状态。
      // 状态由 task_summary_started / task_summary_done 这类阶段事件统一收口。
      task.summary += delta;
      ensureActiveTask(task.id);
    }
    return;
  }

  if (businessStage === "reporter") {
    reportMarkdown.value += delta;
  }
}

function appendToolEvent(event: ResearchEvent): void {
  const payload = event.payload || {};
  const task = findTask(event.task_id);
  const agent = event.agent || "Agent";
  const tool = typeof payload.tool === "string" ? payload.tool : "tool";
  const noteId = extractOptionalString(payload.note_id);
  const notePath = extractOptionalString(payload.note_path);
  const toolInput = ensureRecord(payload.tool_input);
  const businessStage =
    typeof payload.business_stage === "string"
      ? payload.business_stage
      : typeof toolInput.stage === "string"
      ? toolInput.stage
      : "";

  if (!task) {
    progressLogs.value.push(`${agent} 调用了 ${tool}`);
    return;
  }

  applyNoteMetadata(task, payload);

  const last = task.toolCalls[task.toolCalls.length - 1];
  if (event.type === "tool_result" && last && last.tool === tool && !last.result) {
    last.result = typeof payload.result === "string" ? payload.result : JSON.stringify(payload.result ?? "");
    last.noteId = noteId ?? last.noteId;
    last.notePath = notePath ?? last.notePath;
    last.businessStage = businessStage || last.businessStage;
    pulse(toolHighlight);
    return;
  }

  task.toolCalls.push({
    eventId: event.seq || Date.now(),
    agent,
    tool,
    businessStage,
    parameters: toolInput,
    result: typeof payload.result === "string" ? payload.result : "",
    noteId,
    notePath,
    timestamp: Date.now()
  });
  progressLogs.value.push(`${agent} 调用了 ${tool}（任务 ${task.id}）`);
  if (activeTaskId.value === task.id) {
    pulse(toolHighlight);
  }
}

function appendNoteEvent(event: ResearchEvent): void {
  const payload = event.payload || {};
  const task = findTask(event.task_id);
  const noteId = extractOptionalString(payload.note_id);
  const notePath = extractOptionalString(payload.note_path);
  const label =
    typeof payload.label === "string" && payload.label.trim()
      ? payload.label.trim()
      : event.message || "note 更新记录";

  applyReportNoteMetadata(payload, event);

  if (!task) {
    progressLogs.value.push(label);
    return;
  }

  applyNoteMetadata(task, payload);

  task.toolCalls.push({
    eventId: event.seq || Date.now(),
    agent: "NoteService",
    tool: "note",
    businessStage: event.stage || "",
    parameters: {
      ...payload,
      stage: event.stage
    },
    result: label,
    noteId,
    notePath,
    timestamp: Date.now()
  });

  progressLogs.value.push(`${label}（任务 ${task.id}）`);
  if (activeTaskId.value === task.id) {
    pulse(toolHighlight);
  }
}

function applyFinalResult(value: unknown): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return;
  }

  const result = value as Record<string, unknown>;
  const state = ensureRecord(result.state);
  const resultTasks = Array.isArray(result.tasks) ? result.tasks : state.todo_items;
  if (Array.isArray(resultTasks)) {
    // workflow_done 会带回最终任务快照，但运行过程中累积的 toolCalls 只存在前端内存里。
    // 这里必须“合并任务快照”，不能直接 replace 整个任务列表，否则最终报告出来后
    // 工具调用记录会被 normalizeTaskSnapshot() 初始化成空数组。
    mergeTasks(resultTasks);
  }

  if (typeof result.report === "string" && result.report.trim()) {
    reportMarkdown.value = result.report;
    pulse(reportHighlight);
  }

  traceItems.value = normalizeTraceItems(result.traces ?? result.trace);
  evaluatorResult.value = ensureRecord(result.evaluator);
}

function handleResearchEvent(event: ResearchEvent): void {
  if (!firstStreamEventReceived) {
    firstStreamEventReceived = true;
    if (connectWatchTimer !== null) {
      window.clearTimeout(connectWatchTimer);
      connectWatchTimer = null;
    }
  }

  recordExecutionEvent(event);
  appendLog(event);

  if (event.type === "llm_delta" || event.type === "llm_reasoning_delta") {
    applyStreamingDelta(event);
    return;
  }

  if (event.type === "config_warning") {
    const warnings = event.payload.warnings;
    if (Array.isArray(warnings)) {
      warnings.forEach((item) => {
        if (typeof item === "string") {
          progressLogs.value.push(item);
        }
      });
    }
    return;
  }

  if (event.type === "planner_done") {
    replaceTasks(event.payload.tasks);
    ensureActiveTask();
    return;
  }

  if (event.type === "task_started") {
    const task = upsertTaskFromSnapshot(readTaskPayload(event), 0, { preserveStatus: true });
    if (task) {
      ensureActiveTask(task.id);
    }
    return;
  }

  if (event.type === "task_status") {
    const task = upsertTaskFromSnapshot(readTaskPayload(event));
    const targetTask = task ?? findTask(event.task_id);
    if (targetTask) {
      // 任务状态统一由 task_status 事件收口。
      const nextStatus =
        typeof event.status === "string" && event.status.trim()
          ? event.status.trim()
          : targetTask.status;
      targetTask.status = nextStatus;

      const summary = event.payload.summary;
      if (typeof summary === "string" && summary.trim()) {
        targetTask.summary = summary.trim();
      }

      const sourcesSummary = event.payload.sources_summary;
      if (typeof sourcesSummary === "string" && sourcesSummary.trim()) {
        targetTask.sourcesSummary = sourcesSummary.trim();
        targetTask.sourceItems = parseSources(targetTask.sourcesSummary);
      }

      ensureActiveTask(targetTask.id);
      if (terminalTaskStatuses.has(nextStatus)) {
        pulse(sourcesHighlight);
        pulse(summaryHighlight);
      }
    }
    return;
  }

  if (event.type === "task_done") {
    const task = upsertTaskFromSnapshot(readTaskPayload(event), 0, { preserveStatus: true });
    const targetTask = task ?? findTask(event.task_id);
    if (targetTask) {
      ensureActiveTask(targetTask.id);
      pulse(sourcesHighlight);
      pulse(summaryHighlight);
    }
    return;
  }

  if (event.type === "task_search_started" || event.type === "task_summary_started") {
    const task = upsertTaskFromSnapshot(readTaskPayload(event), 0, { preserveStatus: true });
    if (task) {
      ensureActiveTask(task.id);
    }
    return;
  }

  if (event.type === "task_sources_done") {
    const task = upsertTaskFromSnapshot(readTaskPayload(event), 0, { preserveStatus: true });
    if (task) {
      ensureActiveTask(task.id);
      pulse(sourcesHighlight);
    }
    return;
  }

  if (event.type === "task_summary_done" || event.type === "task_summary_skipped") {
    const task = upsertTaskFromSnapshot(readTaskPayload(event), 0, { preserveStatus: true });
    const targetTask = task ?? findTask(event.task_id);
    if (targetTask) {
      ensureActiveTask(targetTask.id);
      pulse(summaryHighlight);
    }
    return;
  }

  if (event.type === "report_done") {
    const report = event.payload.report;
    if (typeof report === "string") {
      reportMarkdown.value = report;
      pulse(reportHighlight);
    }
    if (Array.isArray(event.payload.tasks)) {
      event.payload.tasks.forEach((task, index) => {
        upsertTaskFromSnapshot(task, index, { preserveStatus: true });
      });
    }
    return;
  }

  if (event.type === "evaluator_done" || event.type === "evaluator_failed") {
    evaluatorResult.value = ensureRecord(event.payload.evaluator);
    return;
  }

  if (event.type === "note_event") {
    appendNoteEvent(event);
    return;
  }

  if (event.type === "tool_called" || event.type === "tool_result") {
    appendToolEvent(event);
    return;
  }

  if (event.type === "workflow_done") {
    applyFinalResult(event.payload.result);
    loading.value = false;
    stopCurrentStream = null;
    return;
  }

  if (event.type === "workflow_failed") {
    applyFinalResult(event.payload.result);
    error.value = event.error?.message as string || "研究流程失败";
    loading.value = false;
    stopCurrentStream = null;
    return;
  }

  if (event.type === "api_error") {
    error.value = event.error?.message as string || "接口调用失败";
    loading.value = false;
    stopCurrentStream = null;
  }
}

const handleSubmit = () => {
  if (!form.topic.trim()) {
    error.value = "请输入研究主题";
    return;
  }

  if (stopCurrentStream) {
    stopCurrentStream();
    stopCurrentStream = null;
  }

  loading.value = true;
  error.value = "";
  isExpanded.value = true;
  resetWorkflowState();
  progressLogs.value.push("正在连接深度研究事件流...");

  stopCurrentStream = startResearchStream(
    {
      topic: form.topic.trim(),
      backend: form.searchApi || "hybrid"
    },
    {
      onOpen: () => {
        progressLogs.value.push("事件流连接成功");
      },
      onEvent: handleResearchEvent,
      onError: () => {
        if (loading.value) {
          if (!firstStreamEventReceived && !streamErrorLogged) {
            streamErrorLogged = true;
            progressLogs.value.push("事件流连接失败，请检查后端是否启动、页面地址是否为本机地址");
          }
          console.warn("事件流暂时中断，浏览器正在尝试重连...");
        }
      }
    }
  );

  connectWatchTimer = window.setTimeout(() => {
    if (loading.value && !firstStreamEventReceived) {
      progressLogs.value.push("还没有收到后端事件，请确认 API 地址：http://127.0.0.1:8000");
    }
  }, 6000);
};

const cancelResearch = () => {
  if (!loading.value || !stopCurrentStream) {
    return;
  }
  progressLogs.value.push("正在尝试取消当前研究任务…");
  stopCurrentStream();
  stopCurrentStream = null;
  if (connectWatchTimer !== null) {
    window.clearTimeout(connectWatchTimer);
    connectWatchTimer = null;
  }
  loading.value = false;
};

const goBack = () => {
  if (loading.value) {
    return; // 研究进行中不允许返回
  }
  isExpanded.value = false;
};

const startNewResearch = () => {
  if (loading.value) {
    cancelResearch();
  }
  resetWorkflowState();
  isExpanded.value = false;
  form.topic = "";
  form.searchApi = "";
};

onMounted(async () => {
  try {
    const response = await listBackends();
    if (response.backends.length) {
      searchOptions.value = response.backends.map((item) => item.value);
      form.searchApi = response.default || "hybrid";
    }
  } catch (err) {
    console.warn("获取搜索后端列表失败，使用默认选项", err);
  }
});

onBeforeUnmount(() => {
  if (stopCurrentStream) {
    stopCurrentStream();
    stopCurrentStream = null;
  }
  if (connectWatchTimer !== null) {
    window.clearTimeout(connectWatchTimer);
    connectWatchTimer = null;
  }
  if (noteCopyTimer !== null) {
    window.clearTimeout(noteCopyTimer);
    noteCopyTimer = null;
  }
});
</script>


<style scoped>
.app-shell {
  position: relative;
  min-height: 100vh;
  padding: 72px 24px;
  display: flex;
  justify-content: center;
  align-items: center;
  background: radial-gradient(circle at 20% 20%, #f8fafc, #dbeafe 60%);
  color: #1f2937;
  overflow: hidden;
  box-sizing: border-box;
  transition: padding 0.4s ease;
}

.app-shell.expanded {
  padding: 0;
  align-items: stretch;
  overflow: clip;
}

.aurora {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.55;
}

.aurora span {
  position: absolute;
  width: 45vw;
  height: 45vw;
  max-width: 520px;
  max-height: 520px;
  background: radial-gradient(circle, rgba(148, 197, 255, 0.35), transparent 60%);
  filter: blur(90px);
  animation: float 26s infinite linear;
}

.aurora span:nth-child(1) {
  top: -20%;
  left: -18%;
  animation-delay: 0s;
}

.aurora span:nth-child(2) {
  bottom: -25%;
  right: -20%;
  background: radial-gradient(circle, rgba(166, 139, 255, 0.28), transparent 60%);
  animation-delay: -9s;
}

.aurora span:nth-child(3) {
  top: 35%;
  left: 45%;
  background: radial-gradient(circle, rgba(164, 219, 216, 0.26), transparent 60%);
  animation-delay: -16s;
}

.layout {
  position: relative;
  width: 100%;
  display: flex;
  gap: 24px;
  z-index: 1;
  transition: all 0.4s ease;
}

.copy-toast {
  position: fixed;
  top: 22px;
  left: 50%;
  z-index: 50;
  min-width: 168px;
  max-width: min(360px, calc(100vw - 32px));
  padding: 11px 18px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.94);
  color: #ffffff;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
  font-size: 13px;
  font-weight: 700;
  text-align: center;
  transform: translateX(-50%);
}

.copy-toast-enter-active,
.copy-toast-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.copy-toast-enter-from,
.copy-toast-leave-to {
  opacity: 0;
  transform: translate(-50%, -8px);
}

.layout-centered {
  max-width: 600px;
  justify-content: center;
  align-items: center;
}

.layout-fullscreen {
  height: 100vh;
  max-width: 100%;
  gap: 0;
  align-items: stretch;
}

.report-first-layout {
  height: 100vh;
  min-height: 0;
  overflow: hidden;
}

.panel {
  position: relative;
  flex: 1 1 360px;
  padding: 24px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 24px 48px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(8px);
  overflow: hidden;
}

.panel-form {
  max-width: 420px;
}

.panel-centered {
  width: 100%;
  max-width: 600px;
  padding: 40px;
  box-shadow: 0 32px 64px rgba(15, 23, 42, 0.15);
  transform: scale(1);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.panel-centered:hover {
  transform: scale(1.02);
  box-shadow: 0 40px 80px rgba(15, 23, 42, 0.2);
}

.panel-result {
  min-width: 360px;
  flex: 2 1 420px;
}

.panel::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), rgba(125, 86, 255, 0.1));
  opacity: 0;
  transition: opacity 0.35s ease;
  z-index: 0;
}

.panel:hover::before {
  opacity: 1;
}

.panel > * {
  position: relative;
  z-index: 1;
}

.panel-form h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: 0.01em;
}

.panel-form p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.logo {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  box-shadow: 0 12px 28px rgba(59, 130, 246, 0.4);
}

.logo svg {
  width: 28px;
  height: 28px;
  fill: #f8fafc;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field span {
  font-weight: 600;
  color: #475569;
}

textarea,
input,
select {
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(255, 255, 255, 0.92);
  color: #1f2937;
  font-size: 14px;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}

textarea:focus,
input:focus,
select:focus {
  outline: none;
  border-color: rgba(37, 99, 235, 0.65);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
  background: #ffffff;
}

.options {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.option {
  flex: 1;
  min-width: 140px;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.submit {
  align-self: flex-start;
  padding: 12px 24px;
  border-radius: 16px;
  border: none;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s, opacity 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  position: relative;
}

.submit-label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.submit .spinner {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: rgba(255, 255, 255, 0.85);
  stroke-linecap: round;
  animation: spin 1s linear infinite;
}

.submit:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.submit:not(:disabled):hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.28);
}

.secondary-btn {
  padding: 10px 18px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.28);
  color: #1f2937;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.secondary-btn:hover {
  background: rgba(148, 163, 184, 0.2);
  border-color: rgba(148, 163, 184, 0.35);
  color: #0f172a;
}

.error-chip {
  margin-top: 16px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 14px;
  color: #b91c1c;
  font-size: 14px;
}

.error-chip svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

.panel-result {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.status-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.status-controls {
  display: flex;
  gap: 8px;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(191, 219, 254, 0.28);
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 13px;
  color: #1f2937;
  border: 1px solid rgba(59, 130, 246, 0.35);
  transition: background 0.3s ease, color 0.3s ease;
}

.status-chip.active {
  background: rgba(129, 140, 248, 0.2);
  border-color: rgba(129, 140, 248, 0.4);
  color: #1e293b;
}

.status-chip .dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #2563eb;
  box-shadow: 0 0 12px rgba(37, 99, 235, 0.45);
  animation: pulse 1.8s ease-in-out infinite;
}

.status-meta {
  color: #64748b;
  font-size: 13px;
}

.artifacts-panel {
  padding: 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.88), rgba(248, 250, 252, 0.94));
  border: 1px solid rgba(147, 197, 253, 0.34);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.45);
}

.artifacts-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.artifacts-head h3 {
  margin: 0;
  color: #1e293b;
  font-size: 16px;
}

.artifacts-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.artifact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.artifact-card {
  min-width: 0;
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.artifact-card-wide {
  grid-column: span 2;
}

.artifact-card span {
  color: #64748b;
  font-size: 12px;
}

.artifact-card strong {
  display: block;
  margin-top: 6px;
  color: #0f172a;
  font-size: 16px;
  line-height: 1.25;
  word-break: break-all;
}

.artifact-card p {
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.artifact-path {
  display: flex;
  align-items: center;
  gap: 8px;
  word-break: break-all;
}

.debug-panel {
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 18px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.42);
}

.debug-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.debug-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.debug-tabs {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px;
  border-radius: 14px;
  background: rgba(226, 232, 240, 0.58);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.debug-tabs button {
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #475569;
  padding: 7px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
}

.debug-tabs button.active {
  background: #ffffff;
  color: #1d4ed8;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
}

.logs-wrapper {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.debug-subtitle {
  margin: 0 0 10px;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
}

.timeline-wrapper {
  max-height: 220px;
  overflow-y: auto;
  padding-right: 8px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.45) rgba(226, 232, 240, 0.6);
}

.timeline-wrapper::-webkit-scrollbar {
  width: 6px;
}

.timeline-wrapper::-webkit-scrollbar-track {
  background: rgba(226, 232, 240, 0.6);
  border-radius: 999px;
}

.timeline-wrapper::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(129, 140, 248, 0.8), rgba(59, 130, 246, 0.7));
  border-radius: 999px;
}

.timeline-wrapper::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.9), rgba(37, 99, 235, 0.8));
}

.timeline {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: relative;
  padding-left: 12px;
}

.timeline::before {
  content: "";
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 0;
  width: 2px;
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.35), rgba(129, 140, 248, 0.15));
}

.timeline li {
  position: relative;
  padding-left: 24px;
  color: #1e293b;
  font-size: 14px;
  line-height: 1.5;
}

.timeline-node {
  position: absolute;
  left: -12px;
  top: 6px;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, #38bdf8, #7c3aed);
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.22);
}

.timeline-enter-active,
.timeline-leave-active {
  transition: all 0.35s ease, opacity 0.35s ease;
}

.timeline-enter-from,
.timeline-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.event-log-wrapper,
.trace-wrapper,
.evaluator-wrapper {
  max-height: 340px;
  overflow-y: auto;
  padding-right: 8px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.45) rgba(226, 232, 240, 0.6);
}

.event-log-wrapper::-webkit-scrollbar,
.trace-wrapper::-webkit-scrollbar,
.evaluator-wrapper::-webkit-scrollbar {
  width: 6px;
}

.event-log-wrapper::-webkit-scrollbar-track,
.trace-wrapper::-webkit-scrollbar-track,
.evaluator-wrapper::-webkit-scrollbar-track {
  background: rgba(226, 232, 240, 0.6);
  border-radius: 999px;
}

.event-log-wrapper::-webkit-scrollbar-thumb,
.trace-wrapper::-webkit-scrollbar-thumb,
.evaluator-wrapper::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(129, 140, 248, 0.76), rgba(59, 130, 246, 0.66));
  border-radius: 999px;
}

.event-log {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.event-row {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-left: 3px solid rgba(59, 130, 246, 0.7);
  border-radius: 14px;
  padding: 12px;
  background: rgba(248, 250, 252, 0.92);
}

.event-row.completed {
  border-left-color: #22c55e;
}

.event-row.failed {
  border-left-color: #ef4444;
}

.event-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: #475569;
  font-size: 12px;
}

.event-seq,
.event-stage,
.event-status,
.event-agent,
.event-time {
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.78);
}

.event-type {
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.event-message {
  margin: 8px 0 0;
  color: #1f2937;
  font-size: 13px;
  line-height: 1.6;
}

.event-payload,
.trace-summary {
  margin: 10px 0 0;
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular,
    Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #1f2937;
  white-space: pre-wrap;
  word-break: break-word;
  background: rgba(241, 245, 249, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 12px;
  padding: 12px;
  max-height: 220px;
  overflow: auto;
}

.trace-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.trace-item {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 14px;
  padding: 14px;
  background: rgba(248, 250, 252, 0.92);
}

.trace-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.trace-header h4 {
  margin: 0;
  color: #1f2937;
  font-size: 14px;
  font-weight: 700;
}

.trace-header p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.trace-stage {
  flex: 0 0 auto;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(191, 219, 254, 0.36);
  border: 1px solid rgba(59, 130, 246, 0.28);
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}

.trace-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.trace-meta span {
  padding: 4px 9px;
  border-radius: 999px;
  color: #475569;
  background: rgba(226, 232, 240, 0.74);
  font-size: 12px;
}

.trace-citations {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
}

.trace-citations strong {
  padding: 4px 8px;
  border-radius: 999px;
  color: #1d4ed8;
  background: rgba(219, 234, 254, 0.72);
  border: 1px solid rgba(147, 197, 253, 0.64);
}

.trace-notices {
  margin: 10px 0 0 18px;
  padding: 0;
  color: #92400e;
  font-size: 12px;
  line-height: 1.5;
}

.trace-sources {
  margin-top: 12px;
}

.trace-sources h5 {
  margin: 0 0 8px;
  font-size: 13px;
  color: #1f2937;
}

.trace-sources ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trace-sources li {
  border-radius: 12px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.trace-sources a,
.trace-sources span {
  display: block;
  color: #2563eb;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}

.trace-sources small {
  display: block;
  margin-top: 4px;
  color: #64748b;
}

.trace-sources p {
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.trace-query {
  color: #0369a1 !important;
}

.score-group-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.score-group {
  padding: 12px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.score-group-header {
  margin-bottom: 10px;
}

.score-group-header h4 {
  margin: 0;
  color: #1e293b;
  font-size: 14px;
}

.score-group-header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.score-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 10px;
}

.score-item {
  padding: 12px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.24);
}

.score-item.tone-good {
  background: rgba(236, 253, 245, 0.78);
  border-color: rgba(52, 211, 153, 0.35);
}

.score-item.tone-warn {
  background: rgba(255, 251, 235, 0.84);
  border-color: rgba(245, 158, 11, 0.32);
}

.score-item.tone-danger {
  background: rgba(254, 242, 242, 0.86);
  border-color: rgba(248, 113, 113, 0.38);
}

.score-item span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.score-item strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 22px;
  line-height: 1;
}

.score-item small {
  display: block;
  margin-top: 8px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.evaluator-warnings {
  margin-top: 12px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(254, 243, 199, 0.55);
  border: 1px solid rgba(245, 158, 11, 0.28);
}

.evaluator-warnings h4 {
  margin: 0 0 8px;
  color: #92400e;
  font-size: 13px;
}

.evaluator-warnings ul {
  margin: 0 0 0 18px;
  padding: 0;
  color: #78350f;
  font-size: 12px;
  line-height: 1.6;
}

.evaluator-json {
  max-height: 260px;
}

.evaluator-raw {
  margin-top: 12px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.evaluator-raw summary {
  cursor: pointer;
  padding: 10px 12px;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.evaluator-raw .evaluator-json {
  margin: 0;
  border-radius: 0 0 14px 14px;
  border-left: none;
  border-right: none;
  border-bottom: none;
}

.tasks-section {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 20px;
  align-items: start;
}

@media (max-width: 960px) {
  .tasks-section {
    grid-template-columns: 1fr;
  }
}

.tasks-list {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 18px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.4);
}

.tasks-list h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.tasks-list ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-item {
  border-radius: 14px;
  border: 1px solid transparent;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.task-item.completed {
  border-color: rgba(56, 189, 248, 0.35);
  background: rgba(191, 219, 254, 0.28);
}

.task-item.active {
  border-color: rgba(129, 140, 248, 0.5);
  background: rgba(224, 231, 255, 0.5);
}

.task-button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px 6px;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.task-title {
  flex: 1 1 auto;
  min-width: 0;
  font-weight: 600;
  font-size: 14px;
  line-height: 1.45;
  color: #1e293b;
}

.task-status {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 54px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  color: #1f2937;
  background: rgba(148, 163, 184, 0.2);
}

.task-status.pending {
  background: rgba(148, 163, 184, 0.18);
  color: #475569;
}

.task-status.in_progress {
  background: rgba(129, 140, 248, 0.24);
  color: #312e81;
}

.task-status.searching {
  background: rgba(14, 165, 233, 0.18);
  color: #0369a1;
}

.task-status.summarizing {
  background: rgba(129, 140, 248, 0.22);
  color: #3730a3;
}

.task-status.completed {
  background: rgba(34, 197, 94, 0.2);
  color: #15803d;
}

.task-status.failed {
  background: rgba(248, 113, 113, 0.2);
  color: #b91c1c;
}

.task-status.skipped {
  background: rgba(248, 113, 113, 0.18);
  color: #b91c1c;
}

.task-intent {
  margin: 0;
  padding: 0 14px 12px 14px;
  font-size: 13px;
  color: #64748b;
}

.task-detail {
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 18px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.5);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
}

.task-chip-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.task-citation-row {
  flex-basis: 100%;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 2px;
}

.citation-title {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.citation-chip {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(219, 234, 254, 0.7);
  border: 1px solid rgba(96, 165, 250, 0.35);
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
}

.task-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.task-header .muted {
  margin: 6px 0 0;
}

.task-label {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(191, 219, 254, 0.32);
  border: 1px solid rgba(59, 130, 246, 0.35);
  font-size: 12px;
  color: #1e3a8a;
}

.task-label.note-chip {
  background: rgba(34, 197, 94, 0.2);
  border-color: rgba(34, 197, 94, 0.35);
  color: #15803d;
}

.task-label.path-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 360px;
  background: rgba(56, 189, 248, 0.2);
  border-color: rgba(56, 189, 248, 0.35);
  color: #0369a1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-label {
  font-weight: 500;
}

.path-text {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-action {
  border: none;
  background: rgba(56, 189, 248, 0.2);
  color: #0369a1;
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.chip-action:hover {
  background: rgba(14, 165, 233, 0.28);
  color: #0f172a;
}

.task-notices {
  background: rgba(191, 219, 254, 0.28);
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 16px;
  padding: 14px 18px;
  color: #1f2937;
}

.task-notices h4 {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.task-notices ul {
  list-style: disc;
  margin: 0 0 0 18px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task-notices li {
  font-size: 13px;
}

.report-block {
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 18px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.report-block h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.report-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.report-path {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0369a1;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.block-pre {
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular,
    Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1f2937;
  background: rgba(248, 250, 252, 0.9);
  padding: 16px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  overflow: auto;
  max-height: 420px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.6) rgba(226, 232, 240, 0.7);
}

.block-pre::-webkit-scrollbar {
  width: 6px;
}

.block-pre::-webkit-scrollbar-track {
  background: rgba(226, 232, 240, 0.7);
  border-radius: 999px;
}

.block-pre::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.75), rgba(59, 130, 246, 0.65));
  border-radius: 999px;
}

.block-pre::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, rgba(79, 70, 229, 0.8), rgba(37, 99, 235, 0.75));
}

.summary-block .block-pre,
.sources-block .block-pre {
  max-height: 360px;
}


.tools-block {
  position: relative;
  margin-top: 16px;
  padding: 20px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.4);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tools-block h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  letter-spacing: 0.02em;
}

.tool-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.note-tool-group {
  border-radius: 14px;
  border: 1px solid rgba(14, 165, 233, 0.26);
  background: rgba(240, 249, 255, 0.72);
  padding: 12px 14px;
}

.note-tool-group > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  cursor: pointer;
  color: #0f172a;
  font-weight: 700;
}

.note-tool-group > summary::-webkit-details-marker {
  display: none;
}

.note-tool-group > summary::before {
  content: "▾";
  color: #0284c7;
  font-size: 13px;
  transition: transform 0.2s ease;
}

.note-tool-group:not([open]) > summary::before {
  transform: rotate(-90deg);
}

.note-tool-group > summary span {
  flex: 1 1 auto;
}

.note-tool-group > summary strong {
  flex: 0 0 auto;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(186, 230, 253, 0.72);
  color: #0369a1;
  font-size: 12px;
}

.note-tool-path {
  margin-top: 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: #0369a1;
  font-size: 12px;
}

.note-tool-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.note-tool-entry {
  padding: 9px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(125, 211, 252, 0.28);
}

.note-event-detail {
  width: 100%;
}

.note-event-detail summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  cursor: pointer;
  list-style: none;
}

.note-event-detail summary::-webkit-details-marker {
  display: none;
}

.note-tool-stage {
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
}

.note-tool-id {
  color: #0f766e;
  font-size: 12px;
  word-break: break-all;
}

.note-event-meta {
  margin: 10px 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.note-event-meta span {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  padding: 5px 9px;
  border-radius: 999px;
  background: rgba(240, 249, 255, 0.78);
  border: 1px solid rgba(186, 230, 253, 0.58);
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
  word-break: break-all;
}

.note-event-preview {
  margin: 10px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(203, 213, 225, 0.58);
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.tool-entry {
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 14px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-entry-header {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.tool-entry-title {
  font-weight: 600;
  color: #1f2937;
}

.tool-entry-note {
  font-size: 12px;
  color: #0f766e;
}

.tool-entry-path {
  margin: 0;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #2563eb;
}

.tool-subtitle {
  margin: 0;
  font-size: 13px;
  color: #475569;
  font-weight: 500;
}

.tool-pre {
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular,
    Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1f2937;
  background: rgba(248, 250, 252, 0.9);
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  overflow: auto;
  max-height: 260px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.6) rgba(226, 232, 240, 0.7);
}

.tool-pre::-webkit-scrollbar {
  width: 6px;
}

.tool-pre::-webkit-scrollbar-track {
  background: rgba(226, 232, 240, 0.7);
}

.tool-pre::-webkit-scrollbar-thumb {
  background: rgba(99, 102, 241, 0.7);
  border-radius: 10px;
}

.link-btn {
  background: none;
  border: none;
  color: #0369a1;
  cursor: pointer;
  padding: 0 4px;
  font-size: 12px;
  border-radius: 8px;
  transition: color 0.2s ease, background 0.2s ease;
}

.link-btn:hover {
  color: #0ea5e9;
  background: rgba(14, 165, 233, 0.16);
}


.sources-block,
.summary-block {
  position: relative;
  margin-top: 16px;
  padding: 18px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.4);
}

.sources-history {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sources-history h4 {
  margin: 0;
  color: #1f2937;
  font-size: 14px;
  letter-spacing: 0.01em;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.history-list details {
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 14px;
  padding: 12px 16px;
  color: #1f2937;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.history-list details[open] {
  background: rgba(224, 231, 255, 0.55);
  border-color: rgba(129, 140, 248, 0.4);
}

.history-list summary {
  cursor: pointer;
  font-weight: 600;
  outline: none;
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.history-list summary::-webkit-details-marker {
  display: none;
}

.history-list summary::after {
  content: "▾";
  margin-left: 6px;
  font-size: 12px;
  opacity: 0.7;
  transition: transform 0.2s ease;
}

.history-list details[open] summary::after {
  transform: rotate(180deg);
}

.block-highlight {
  animation: glow 1.2s ease;
}

.sources-block h3,
.summary-block h3 {
  margin: 0 0 14px;
  color: #1f2937;
  letter-spacing: 0.02em;
}

.sources-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source-item {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.58);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.source-link {
  color: #2563eb;
  text-decoration: none;
  font-weight: 600;
  font-size: 14px;
  line-height: 1.45;
  letter-spacing: 0.01em;
  transition: color 0.2s ease;
}

.source-link::after {
  content: " ↗";
  font-size: 12px;
  opacity: 0.6;
}

.source-link:hover {
  color: #0f172a;
}

.source-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.source-meta span {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.3);
  color: #64748b;
  font-size: 10px;
  font-weight: 600;
}

.source-meta .source-type-strong {
  background: rgba(236, 253, 245, 0.92);
  border-color: rgba(52, 211, 153, 0.36);
  color: #047857;
}

.source-meta .source-type-weak {
  background: rgba(255, 247, 237, 0.92);
  border-color: rgba(251, 146, 60, 0.34);
  color: #c2410c;
}

.source-meta .source-type-neutral {
  background: rgba(239, 246, 255, 0.9);
  border-color: rgba(147, 197, 253, 0.35);
  color: #1d4ed8;
}

.source-query {
  margin: 0;
  color: #0369a1;
  font-size: 12px;
  line-height: 1.5;
}

.source-snippet {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.source-reasons {
  margin: 0;
  padding-left: 18px;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.source-preview {
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.56);
  border: 1px solid rgba(203, 213, 225, 0.38);
}

.source-preview summary {
  cursor: pointer;
  padding: 7px 9px;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.source-detail-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 10px 10px;
}

.source-detail-title {
  margin: 0;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
}

.source-raw {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.hint.muted {
  color: #64748b;
}

/* D-blue 研究阅读器布局：对应设计稿 variant-d-blue-saas.svg */
.reader-layout {
  display: block;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: #e9edf5;
}

.reader-page {
  width: min(1440px, calc(100vw - 56px));
  height: calc(100vh - 56px);
  height: calc(100dvh - 56px);
  margin: 28px auto;
  border-radius: 28px;
  background: linear-gradient(135deg, #f7f9ff 0%, #edf4ff 55%, #f8fbff 100%);
  border: 1px solid rgba(203, 213, 225, 0.64);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.1);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.reader-topbar {
  flex: 0 0 72px;
  height: 72px;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 34px;
  background: #ffffff;
  border-bottom: 1px solid #e1e8f2;
}

.reader-page {
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
}

.reader-brand {
  display: flex;
  align-items: center;
  min-width: 156px;
  padding-right: 24px;
  border-right: 1px solid #d8e2f2;
}

.reader-brand button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #172033;
  font: inherit;
  font-size: 20px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.reader-brand button:disabled {
  cursor: default;
}

.reader-nav {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 36px;
  color: #7a879e;
  font-size: 14px;
  font-weight: 450;
}

.reader-nav .active {
  color: #2563eb;
  font-weight: 700;
}

.reader-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.reader-status-pill {
  min-height: 40px;
  padding: 0 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.reader-task-count {
  color: #2f63eb;
  background: #f1f6ff;
  border: 1px solid #c9dcff;
}

.reader-quality-status {
  color: #7a879e;
  background: #f8fafc;
  border-color: #e2e8f0;
}

.reader-quality-status.passed {
  color: #059669;
  background: #ecfbf5;
  border-color: #acefd1;
}

.reader-new-button {
  min-height: 40px;
  padding: 0 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: 999px;
  border: 1px solid #1d4ed8;
  color: #ffffff;
  background: #1e3a8a;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: 0 5px 14px rgba(30, 58, 138, 0.16);
  transition: background-color 0.18s ease, border-color 0.18s ease,
    box-shadow 0.18s ease, transform 0.18s ease;
}

.reader-new-button:hover {
  border-color: #2563eb;
  background: #2563eb;
  box-shadow: 0 7px 18px rgba(37, 99, 235, 0.22);
  transform: translateY(-1px);
}

.reader-new-button-icon {
  font-size: 19px;
  font-weight: 400;
  line-height: 1;
}

.reader-kicker,
.reader-section-label {
  margin: 0;
  color: #4f75dc;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.reader-content {
  min-height: 0;
  flex: 1;
  display: grid;
  grid-template-columns: 272px minmax(520px, 1fr) 316px;
  gap: 20px;
  padding: 24px 32px 32px;
  overflow: hidden;
}

.reader-index,
.reader-report,
.reader-quality {
  min-height: 0;
  border-radius: 20px;
  background: #ffffff;
  border: 1px solid #dce5f2;
  overflow: hidden;
}

.reader-index,
.reader-quality {
  padding: 22px;
}

.reader-index {
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow-y: auto;
}

.reader-index-head h2 {
  margin: 12px 0 8px;
  color: #1f2937;
  display: -webkit-box;
  overflow: hidden;
  font-size: 16px;
  line-height: 1.4;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.reader-index-head span {
  color: #6b7890;
  font-size: 12px;
  font-weight: 500;
}

.reader-menu,
.reader-task-notes {
  margin-top: 22px;
  padding-top: 20px;
  border-top: 1px solid #e4ebf5;
}

.reader-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.reader-menu a {
  display: block;
  min-height: 40px;
  padding: 10px 14px;
  border-radius: 10px;
  color: #52617c;
  font-size: 14px;
  font-weight: 450;
  text-decoration: none;
}

.reader-menu a.active {
  color: #172033;
  background: #f1f6ff;
  border-left: 4px solid #2563eb;
  font-weight: 700;
}

.reader-task-notes {
  flex: 0 0 auto;
  margin-bottom: 0;
  overflow: visible;
}

.reader-task-notes ul {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reader-task-notes li button {
  width: 100%;
  min-height: 66px;
  padding: 11px 14px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  border-radius: 12px;
  border: 1px solid #e1e8f2;
  background: #f8faff;
  cursor: pointer;
  text-align: left;
}

.reader-task-notes li.active button {
  background: #edf4ff;
  border-color: #91b4ff;
}

.reader-task-notes span {
  color: #63718a;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
}

.reader-task-notes li.active span {
  color: #1f3f7a;
  font-weight: 700;
}

.reader-task-notes small {
  color: #059669;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.reader-note-card {
  flex: 0 0 auto;
  margin-top: auto;
  min-height: 150px;
  padding: 18px 16px 14px;
  border-radius: 14px;
  background: #17233b;
  color: #f4f7ff;
}

.reader-note-card p {
  margin: 0 0 12px;
  color: #a7b4ca;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.reader-note-card strong {
  display: block;
  min-height: 44px;
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.6;
  word-break: break-all;
}

.reader-note-card button {
  width: 100%;
  margin-top: 12px;
  min-height: 34px;
  border-radius: 9px;
  border: none;
  color: #ffffff;
  background: #2563eb;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.reader-report {
  padding: 42px 48px max(64px, env(safe-area-inset-bottom));
  overflow-y: auto;
  overscroll-behavior-y: contain;
  scrollbar-gutter: stable;
  scroll-padding-block: 42px 64px;
}

.reader-report-head {
  padding-bottom: 28px;
  border-bottom: 1px solid #e4ebf5;
}

.reader-report-head h2 {
  margin: 0 0 8px;
  color: #111827;
  display: -webkit-box;
  overflow: hidden;
  font-size: 28px;
  font-weight: 750;
  line-height: 1.2;
  letter-spacing: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.reader-report-head p:not(.reader-kicker) {
  margin: 0;
  color: #66758f;
  font-size: 14px;
  font-weight: 450;
}

.reader-report-summary {
  margin-top: 28px;
  padding: 0;
  background: transparent;
  border: 0;
}

.reader-report-summary h3 {
  margin: 0 0 14px;
  color: #000000;
  font-size: 14px;
  font-weight: 800;
}

.reader-report-summary p {
  margin: 0;
  color: #43516a;
  font-size: 14px;
  font-weight: 450;
  line-height: 1.85;
}

.reader-report-summary .link-btn {
  font-size: 14px;
}

.reader-report-body {
  margin: 26px 0 0;
  padding: 0;
  border: none;
  background: transparent;
  color: #43516a;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 14px !important;
  font-weight: 450;
  line-height: 1.85;
  white-space: pre-wrap;
  word-break: break-word;
}

.reader-report-body > span {
  display: block;
  min-height: 1.85em;
}

.reader-report-body .reader-report-heading {
  color: #000000;
  font-weight: 800;
}

.reader-finding {
  margin-top: 28px;
  padding: 18px 22px;
  border-radius: 14px;
  background: #f2f7ff;
  border-left: 5px solid #2563eb;
}

.reader-finding strong {
  display: block;
  margin-top: 10px;
  color: #1f3f7a;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.7;
}

.reader-task-panel {
  margin-top: 28px;
  padding: 20px;
  border-radius: 14px;
  background: #f8fbff;
  border: 1px solid #dbe7f8;
}

.reader-task-panel h3 {
  margin: 0 0 12px;
  color: #172033;
  font-size: 16px;
  font-weight: 700;
}

.reader-task-panel p {
  margin: 0 0 12px;
  color: #52617c;
  font-size: 14px;
  font-weight: 450;
  line-height: 1.7;
}

.reader-citation-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.reader-citation-row span {
  padding: 4px 9px;
  border-radius: 999px;
  color: #2563eb;
  background: #edf4ff;
  border: 1px solid #cfe0ff;
  font-size: 12px;
  font-weight: 800;
}

.reader-source-mini-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reader-source-mini-list li {
  padding: 10px 12px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #e1e8f2;
}

.reader-source-mini-list a,
.reader-source-mini-list span {
  display: block;
  color: #2563eb;
  text-decoration: none;
  font-size: 13px;
  font-weight: 800;
}

.reader-source-mini-list small {
  display: block;
  margin-top: 4px;
  color: #6b7890;
  font-size: 12px;
}

.reader-error {
  margin-top: 20px;
  padding: 14px 16px;
  border-radius: 12px;
  color: #b91c1c;
  background: #fff1f2;
  border: 1px solid #fecdd3;
}

.reader-debug {
  margin-top: 28px;
  border-radius: 16px;
  background: #f8fbff;
  border: 1px solid #dbe7f8;
  overflow: hidden;
}

.reader-debug > summary {
  min-height: 54px;
  padding: 0 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  cursor: pointer;
  color: #172033;
  font-weight: 800;
  list-style: none;
}

.reader-debug > summary::-webkit-details-marker {
  display: none;
}

.reader-debug > summary small {
  color: #8492ad;
  font-weight: 700;
}

.reader-debug .debug-tabs {
  margin: 0 18px 14px;
}

.reader-log-list {
  margin: 0 18px 18px;
  max-height: 260px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.reader-log-list p {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  color: #52617c;
  background: #ffffff;
  border: 1px solid #e1e8f2;
  font-size: 12px;
  line-height: 1.6;
}

.reader-debug .trace-wrapper,
.reader-debug .event-payload {
  margin: 0 18px 18px;
}

.reader-quality {
  background: #f7faff;
  overflow-y: auto;
}

.reader-quality h2 {
  margin: 0 0 18px;
  color: #172033;
  font-size: 16px;
  font-weight: 700;
}

.reader-score-card {
  padding: 20px;
  border-radius: 15px;
  background: #111d33;
  border: 1px solid #111d33;
}

.reader-score-card p {
  margin: 0 0 10px;
  color: #a7b4ca;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.reader-score-main {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.reader-score-main > strong {
  display: block;
  color: #ffffff;
  font-size: 48px;
  font-weight: 800;
  line-height: 1;
  white-space: nowrap;
}

.reader-score-main > strong.is-pending {
  font-size: 26px;
  letter-spacing: -0.02em;
}

.reader-score-main b {
  margin-bottom: 8px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #a7b4ca;
  font-size: 12px;
  font-weight: 500;
}

.reader-score-main b i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #64748b;
}

.reader-score-main b.passed {
  color: #8ce8c5;
}

.reader-score-main b.passed i {
  background: #8ce8c5;
}

.reader-score-card span {
  display: block;
  margin-top: 10px;
  color: #c3cddd;
  font-size: 12px;
  font-weight: 500;
}

.reader-metric-list,
.reader-warning-list,
.reader-evidence {
  margin-top: 28px;
}

.reader-quality .reader-section-label {
  font-size: 12px;
}

.reader-metric {
  min-height: 48px;
  padding: 0 14px;
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-radius: 11px;
  background: #ffffff;
  border: 1px solid #e4ebf5;
}

.reader-metric span {
  color: #63718a;
  font-size: 12px;
  font-weight: 500;
}

.reader-metric strong {
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
}

.reader-metric.tone-good strong {
  color: #059669;
}

.reader-metric.tone-warn {
  background: #fff8ed;
  border-color: #ffe0b6;
}

.reader-metric.tone-warn strong {
  color: #c76b12;
}

.reader-metric.tone-danger {
  background: #fff1f2;
  border-color: #fecdd3;
}

.reader-metric.tone-danger strong {
  color: #dc2626;
}

.reader-warning-list {
  padding: 14px;
  border-radius: 13px;
  background: #fff8ed;
  border: 1px solid #ffe0b6;
}

.reader-warning-list ul {
  margin: 10px 0 0 18px;
  padding: 0;
  color: #92400e;
  font-size: 12px;
  line-height: 1.6;
}

.reader-evidence ul {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.reader-evidence li {
  padding: 14px;
  border-radius: 13px;
  background: #ffffff;
  border: 1px solid #dce5f2;
}

.reader-evidence a,
.reader-evidence span {
  display: block;
  color: #172033;
  text-decoration: none;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
}

.reader-evidence small {
  display: block;
  margin-top: 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.reader-evidence em {
  display: block;
  margin-top: 6px;
  color: #6b7890;
  font-size: 12px;
  font-weight: 500;
  font-style: normal;
}

.reader-evidence-summary {
  margin-top: 28px;
  padding: 14px;
  border-radius: 13px;
  background: #edf4ff;
  border: 1px solid #cfe0ff;
}

.reader-evidence-summary span,
.reader-evidence-summary strong {
  display: block;
  font-size: 12px;
}

.reader-quality .muted {
  font-size: 12px;
}

.reader-evidence-summary span {
  color: #52617c;
  font-weight: 500;
}

.reader-evidence-summary strong {
  margin-top: 8px;
  color: #2563eb;
  font-weight: 500;
}

.reader-index,
.reader-report,
.reader-quality,
.reader-task-notes {
  scrollbar-color: #c9d8ee transparent;
  scrollbar-width: thin;
}

@media (max-width: 1200px) {
  .reader-page {
    width: 100vw;
    height: 100vh;
    height: 100dvh;
    margin: 0;
    border-radius: 0;
  }

  .reader-content {
    grid-template-columns: 220px minmax(400px, 1fr) 260px;
    gap: 16px;
    padding: 20px;
  }

  .reader-index,
  .reader-quality {
    padding: 18px;
  }

  .reader-report {
    padding-right: 36px;
    padding-left: 36px;
  }
}

@media (max-width: 900px) {
  .reader-layout {
    overflow-y: auto;
  }

  .reader-page {
    min-height: 100vh;
    min-height: 100dvh;
    height: auto;
  }

  .reader-topbar {
    flex-wrap: wrap;
    height: auto;
    padding: 16px 20px;
  }

  .reader-brand {
    min-width: 0;
  }

  .reader-nav {
    order: 3;
    width: 100%;
    padding-top: 14px;
    border-top: 1px solid #e4ebf5;
    flex-wrap: wrap;
  }

  .reader-actions {
    margin-left: auto;
  }

  .reader-content {
    grid-template-columns: 1fr;
    padding: 0 18px 24px;
    overflow: visible;
  }

  .reader-index,
  .reader-quality {
    overflow: visible;
  }

  .reader-report {
    padding: 28px 24px max(48px, env(safe-area-inset-bottom));
    overflow: visible;
    scrollbar-gutter: auto;
  }

  .reader-quality {
    display: block;
  }
}

@media (max-width: 560px) {
  .reader-brand {
    padding-right: 14px;
  }

  .reader-brand button {
    font-size: 17px;
  }

  .reader-status-pill {
    min-height: 36px;
    padding: 0 12px;
    font-size: 12px;
  }

  .reader-quality-status {
    display: none;
  }

  .reader-nav {
    gap: 22px;
  }
}

@keyframes float {
  0% {
    transform: translate3d(0, 0, 0) rotate(0deg);
  }
  50% {
    transform: translate3d(10%, 6%, 0) rotate(3deg);
  }
  100% {
    transform: translate3d(0, 0, 0) rotate(0deg);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.3);
    opacity: 0.5;
  }
}

@keyframes glow {
  0% {
    box-shadow: 0 0 0 rgba(59, 130, 246, 0.3);
    border-color: rgba(59, 130, 246, 0.5);
  }
  100% {
    box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.12);
    border-color: rgba(148, 163, 184, 0.2);
  }
}

@media (max-width: 960px) {
  .app-shell {
    padding: 56px 16px;
  }

  .layout {
    flex-direction: column;
    align-items: stretch;
  }

  .panel {
    padding: 22px;
  }

  .panel-form,
  .panel-result {
    max-width: none;
  }

  .status-bar {
    flex-direction: column;
    align-items: flex-start;
  }

  .status-main,
  .status-controls {
    width: 100%;
  }

  .status-controls {
    justify-content: flex-start;
  }
}

@media (max-width: 600px) {
  .options {
    flex-direction: column;
  }

  .status-meta {
    font-size: 12px;
  }

  .panel-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .panel-form h1 {
    font-size: 24px;
  }
}

/* 侧边栏样式 */
.sidebar {
  width: 400px;
  min-width: 400px;
  height: 100vh;
  background: rgba(255, 255, 255, 0.98);
  border-right: 1px solid rgba(148, 163, 184, 0.2);
  padding: 32px 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  overflow-y: auto;
  box-shadow: 4px 0 24px rgba(15, 23, 42, 0.08);
}

.sidebar-header {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sidebar-header h2 {
  font-size: 24px;
  font-weight: 700;
  margin: 0;
  color: #1f2937;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: transparent;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 12px;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  width: fit-content;
}

.back-btn:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.1);
  border-color: #3b82f6;
  color: #3b82f6;
}

.back-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.research-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.info-item label {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
}

.info-item p {
  margin: 0;
  font-size: 14px;
  color: #1f2937;
  line-height: 1.6;
}

.topic-display {
  font-size: 16px !important;
  font-weight: 600;
  color: #0f172a !important;
  padding: 12px;
  background: rgba(59, 130, 246, 0.05);
  border-radius: 8px;
  border-left: 3px solid #3b82f6;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  border-radius: 4px;
  transition: width 0.5s ease;
}

.progress-text {
  font-size: 13px !important;
  color: #64748b !important;
  font-weight: 500;
}

.sidebar-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.2);
}

.new-research-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 20px;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  border: none;
  border-radius: 12px;
  color: white;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.new-research-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4);
}

.new-research-btn:active {
  transform: translateY(0);
}

/* 全屏状态下的结果面板 */
.layout-fullscreen .panel-result {
  flex: 1;
  height: 100vh;
  border-radius: 0;
  border: none;
  overflow-y: auto;
  max-width: none;
}

@media (max-width: 1024px) {
  .sidebar {
    width: 320px;
    min-width: 320px;
  }
}

@media (max-width: 768px) {
  .layout-fullscreen {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    min-width: 100%;
    height: auto;
    max-height: 40vh;
  }

  .layout-fullscreen .panel-result {
    height: 60vh;
  }
}

/* Figma · Deep Research Assistant / Results Dashboard */
.app-shell.expanded {
  background: #f4f6fb;
  color: #151b2a;
}

.layout-centered .panel-centered {
  flex: 0 1 600px;
  height: auto;
}

.app-shell.expanded .aurora {
  display: none;
}

.dashboard-layout {
  display: block;
  width: 100%;
  height: 100vh;
  padding: 20px;
  overflow: auto;
  box-sizing: border-box;
  background:
    radial-gradient(circle at 76% 4%, rgba(219, 234, 254, 0.8), transparent 25%),
    radial-gradient(circle at 96% 28%, rgba(237, 233, 254, 0.56), transparent 25%),
    #f5f7fb;
  color: #151b2a;
  font-family: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
  scroll-behavior: smooth;
}

.dashboard-shell {
  --dashboard-sidebar-column-width: 190px;
  --dashboard-main-left-padding: 20px;
  --dashboard-main-right-padding: 42px;
  --dashboard-evaluator-column-width: 168px;
  --dashboard-content-width: calc(
    225px + 354px + var(--dashboard-evaluator-column-width) + 40px
  );
  --dashboard-main-width: calc(
    var(--dashboard-main-left-padding) + var(--dashboard-content-width) +
      var(--dashboard-main-right-padding)
  );
  width: calc(var(--dashboard-sidebar-column-width) + var(--dashboard-main-width));
  max-width: 100%;
  height: calc(100vh - 40px);
  min-height: calc(100vh - 40px);
  margin: 0 auto;
  display: grid;
  grid-template-columns: var(--dashboard-sidebar-column-width) var(--dashboard-main-width);
}

.dashboard-sidebar {
  position: relative;
  width: 190px;
  height: calc(100vh - 40px);
  min-height: 0;
  padding: 20px;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  border-radius: 20px;
  background: linear-gradient(180deg, #101729 0%, #111a2e 58%, #121b2f 100%);
  color: #ffffff;
  overflow: hidden;
}

.dashboard-sidebar::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 0 0, rgba(64, 102, 239, 0.16), transparent 28%),
    linear-gradient(115deg, transparent 64%, rgba(255, 255, 255, 0.018));
}

.dashboard-sidebar > * {
  position: relative;
  z-index: 1;
}

.dashboard-brand {
  width: 100%;
  padding: 0;
  display: flex;
  align-items: center;
  gap: 15px;
  border: none;
  background: none;
  color: #ffffff;
  text-align: left;
  cursor: pointer;
}

.dashboard-brand:disabled {
  cursor: not-allowed;
}

.dashboard-brand-mark {
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: linear-gradient(145deg, #416ff0, #345bda);
  box-shadow:
    0 12px 28px rgba(37, 72, 190, 0.36),
    inset 0 1px rgba(255, 255, 255, 0.2);
}

.dashboard-brand-mark svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: rgba(255, 255, 255, 0.94);
  stroke-width: 2;
  stroke-linecap: round;
}

.dashboard-brand strong {
  display: block;
  font-size: 14px;
  font-weight: 800;
  line-height: 1.2;
  letter-spacing: -0.03em;
}

.dashboard-brand small {
  display: block;
  margin-top: 3px;
  color: #aeb8ca;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.2;
}

.dashboard-nav {
  margin-top: 39px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.dashboard-nav a {
  width: 100%;
  min-height: 38px;
  padding: 0 11px;
  display: flex;
  align-items: center;
  gap: 0;
  box-sizing: border-box;
  border-radius: 9px;
  color: #c5ccda;
  text-decoration: none;
  font-size: 12px;
  font-weight: 520;
  transition: color 160ms ease, background 160ms ease, transform 160ms ease;
}

.dashboard-nav a:hover {
  color: #ffffff;
  background: rgba(74, 105, 212, 0.16);
  transform: translateX(2px);
}

.dashboard-nav a.active {
  color: #ffffff;
  background: linear-gradient(90deg, #3157d8, #365edc);
  box-shadow: 0 10px 22px rgba(32, 62, 165, 0.25);
}

.dashboard-nav-icon {
  width: 18px;
  display: none;
  place-items: center;
  color: #aab4c7;
  font-size: 15px;
}

.dashboard-nav a.active .dashboard-nav-icon {
  color: #ffffff;
}

.dashboard-sidebar-spacer {
  flex: 1 1 auto;
  min-height: 34px;
}

.dashboard-baseline {
  padding: 15px 12px;
  border-radius: 14px;
  background: rgba(18, 29, 51, 0.82);
  border: 1px solid #2c3954;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.025);
}

.dashboard-baseline p {
  margin: 0;
  color: #a8b2c5;
  font-size: 11px;
  line-height: 1;
}

.dashboard-baseline > strong {
  display: block;
  margin-top: 11px;
  color: #ffffff;
  font-size: 25px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.04em;
}

.dashboard-progress-track {
  height: 5px;
  margin-top: 15px;
  overflow: hidden;
  border-radius: 99px;
  background: #33405a;
}

.dashboard-progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #42d0a0;
  transition: width 400ms ease;
}

.dashboard-baseline small {
  display: block;
  margin-top: 12px;
  color: #c2cad8;
  font-size: 10px;
  line-height: 1.52;
}

.dashboard-baseline em {
  display: block;
  margin-top: 8px;
  color: #51d5a8;
  font-size: 10px;
  font-style: normal;
}

.dashboard-new-research {
  min-height: 38px;
  margin-top: 13px;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 10px;
  border: 1px solid #33415e;
  background: rgba(21, 32, 54, 0.9);
  color: #cbd3e1;
  font-size: 11px;
  font-weight: 650;
  box-sizing: border-box;
  cursor: pointer;
  transition: border-color 160ms ease, color 160ms ease, background 160ms ease;
}

.dashboard-new-research:hover {
  color: #ffffff;
  border-color: #4965b5;
  background: #1b2946;
}

.dashboard-main {
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: 0 var(--dashboard-main-right-padding) 0 var(--dashboard-main-left-padding);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dashboard-hero {
  width: min(100%, var(--dashboard-content-width));
  min-height: 0;
  padding-bottom: 20px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 28px;
}

.dashboard-hero > div:first-child {
  flex: 1 1 auto;
  min-width: 0;
}

.dashboard-eyebrow {
  margin: 0 0 10px;
  color: #4470d4;
  font-size: 12px;
  font-weight: 750;
}

.dashboard-hero h1 {
  max-width: 100%;
  margin: 0;
  overflow: hidden;
  color: #111827;
  font-size: 24px;
  font-weight: 850;
  line-height: 1.14;
  letter-spacing: -0.045em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-subtitle {
  max-width: 900px;
  margin: 10px 0 0;
  color: #6f7789;
  font-size: 11px;
  line-height: 1.65;
}

.dashboard-hero-badges {
  flex: 0 0 auto;
  padding-top: 5px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.dashboard-hero-badges span {
  min-height: 30px;
  padding: 0 14px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 999px;
  border: 1px solid #cfdbf1;
  background: rgba(247, 250, 255, 0.9);
  color: #3965bc;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}

.dashboard-hero-badges span.success {
  color: #2a8768;
  border-color: #c9ebdf;
  background: #f0fbf7;
}

.dashboard-hero-badges i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #35b887;
}

.dashboard-artifacts,
.dashboard-card {
  border: 1px solid #dfe4ec;
  background: rgba(255, 255, 255, 0.94);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.015),
    inset 0 1px rgba(255, 255, 255, 0.58);
}

.dashboard-artifacts {
  min-height: 148px;
  padding: 23px;
  border-radius: 19px;
}

.dashboard-artifacts header h2,
.dashboard-card-head h2,
.dashboard-report-preview h2,
.dashboard-evaluator h2 {
  margin: 0;
  color: #141a28;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.dashboard-artifacts header p,
.dashboard-card-head p {
  margin: 5px 0 0;
  color: #8a92a2;
  font-size: 12px;
  line-height: 1.5;
}

.dashboard-artifact-grid {
  margin-top: 15px;
  display: grid;
  grid-template-columns: 1fr 1.12fr 0.9fr 0.9fr;
  gap: 20px;
}

.dashboard-artifact-grid article {
  min-width: 0;
  height: 52px;
  padding: 0 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-radius: 13px;
  border: 1px solid;
}

.dashboard-artifact-grid span {
  color: #697286;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.dashboard-artifact-grid strong {
  min-width: 0;
  overflow: hidden;
  color: #325ec0;
  font-size: 17px;
  font-weight: 800;
  line-height: 1.05;
  text-align: right;
  text-overflow: ellipsis;
}

.dashboard-artifact-grid .artifact-blue {
  border-color: #dce7f8;
  background: #f3f7fd;
}

.dashboard-artifact-grid .artifact-neutral {
  border-color: #e1e5eb;
  background: #fafbfc;
}

.dashboard-artifact-grid .artifact-neutral strong {
  max-width: 58%;
  color: #50596a;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 13px;
}

.dashboard-artifact-grid .artifact-green {
  border-color: #d0eee2;
  background: #effaf6;
}

.dashboard-artifact-grid .artifact-green strong {
  color: #2d8468;
}

.dashboard-artifact-grid .artifact-purple {
  border-color: #e4dcf7;
  background: #f7f4fd;
}

.dashboard-artifact-grid .artifact-purple strong {
  color: #6540b7;
}

.dashboard-workspace {
  --dashboard-row-height: 408px;
  width: min(100%, var(--dashboard-content-width));
  margin-top: 0;
  display: grid;
  grid-template-columns: 225px 354px var(--dashboard-evaluator-column-width);
  gap: 20px;
  align-items: start;
}

.dashboard-card {
  min-width: 0;
  border-radius: 20px;
}

.dashboard-task-list {
  height: 408px;
  padding: 24px 15px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dashboard-task-list .dashboard-card-head h2 {
  font-size: 14px;
}

.dashboard-task-list .dashboard-card-head p {
  font-size: 10px;
}

.dashboard-task-list ul {
  flex: 1 1 auto;
  min-height: 0;
  list-style: none;
  margin: 18px 0 0;
  padding: 2px 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 15px;
  scrollbar-width: thin;
  scrollbar-color: #c8d3e3 transparent;
}

.dashboard-task-list ul::-webkit-scrollbar {
  width: 5px;
}

.dashboard-task-list ul::-webkit-scrollbar-track {
  background: transparent;
}

.dashboard-task-list ul::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #c8d3e3;
}

.dashboard-task-list li button {
  width: 100%;
  min-height: 51px;
  height: 51px;
  padding: 11px 15px;
  display: flex;
  align-items: center;
  gap: 13px;
  border: 1px solid #e1e5ec;
  border-radius: 14px;
  background: #fafbfc;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}

.dashboard-task-list li button:hover {
  transform: translateY(-1px);
  border-color: #b9cae8;
}

.dashboard-task-list li.active button {
  border-color: #a6c3e0;
  background: #f1f5fc;
  box-shadow: inset 0 0 0 1px rgba(87, 134, 195, 0.05);
}

.dashboard-task-index {
  width: 33px;
  height: 22px;
  flex: 0 0 33px;
  display: grid;
  place-items: center;
  border: 1px solid #d7dce5;
  border-radius: 11px;
  background: #ffffff;
  color: #536074;
  font-size: 9px;
  font-weight: 650;
}

.dashboard-task-list li.active .dashboard-task-index {
  border-color: #c6d7ed;
  color: #3d6bad;
}

.dashboard-task-copy {
  min-width: 0;
}

.dashboard-task-copy strong,
.dashboard-task-copy small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-task-copy strong {
  color: #1c2330;
  font-size: 11px;
  font-weight: 750;
}

.dashboard-task-copy small {
  margin-top: 4px;
  color: #727c8c;
  font-size: 9px;
  text-transform: lowercase;
}

.dashboard-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.dashboard-empty-tasks {
  min-height: 330px;
  padding: 28px;
}

.dashboard-empty-icon {
  width: 45px;
  height: 45px;
  display: grid;
  place-items: center;
  border-radius: 13px;
  background: #f1f5fb;
  color: #6781b2;
  font-size: 19px;
}

.dashboard-empty strong {
  margin-top: 18px;
  color: #263044;
  font-size: 13px;
}

.dashboard-empty p {
  max-width: 190px;
  margin: 8px 0 0;
  color: #8a93a4;
  font-size: 11px;
  line-height: 1.6;
}

.dashboard-current-task {
  height: var(--dashboard-row-height);
  padding: 24px 18px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dashboard-current-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.dashboard-current-head h2 {
  font-size: 14px;
}

.dashboard-current-head p {
  font-size: 10px;
}

.dashboard-task-state {
  flex: 0 0 auto;
  min-height: 26px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: #eff9f5;
  border: 1px solid #d3ede3;
  color: #318168;
  font-size: 10px;
  font-weight: 700;
}

.dashboard-task-insights {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: center;
  gap: 6px;
}

.dashboard-task-insights span {
  width: 100%;
  min-height: 27px;
  padding: 0 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #dfe5ee;
  border-radius: 999px;
  background: #f8fafc;
  color: #68758a;
  font-size: 9px;
  font-weight: 650;
  white-space: nowrap;
}

.dashboard-task-insights span:nth-child(2) {
  border-color: #cfe9df;
  background: #f0faf6;
  color: #2f8468;
}

.dashboard-query {
  margin-top: 18px;
  padding: 11px 13px;
  border-radius: 12px;
  background: #f7f9fc;
  border: 1px solid #e7eaf0;
}

.dashboard-query span {
  color: #7790bc;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.dashboard-query p {
  margin: 4px 0 0;
  color: #536075;
  font-size: 11px;
  line-height: 1.5;
}

.dashboard-source-list {
  list-style: none;
  margin: 19px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.dashboard-source-list li {
  min-height: 76px;
  padding: 13px 16px;
  border-radius: 13px;
  border: 1px solid #e2e6ed;
  background: #fbfcfd;
}

.dashboard-source-list a,
.dashboard-source-list > li > strong {
  display: -webkit-box;
  overflow: hidden;
  color: #3569ba;
  font-size: 12px;
  font-weight: 720;
  line-height: 1.25;
  text-decoration: none;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.dashboard-source-list li > div {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dashboard-source-list li > div span {
  min-height: 21px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  border: 1px solid #dce1e9;
  border-radius: 999px;
  background: #ffffff;
  color: #566174;
  font-size: 9px;
  font-weight: 600;
}

.dashboard-source-list li > div span.source-type-strong {
  border-color: #cceadf;
  background: #effaf6;
  color: #2d8c6c;
}

.dashboard-source-list li > div span.source-type-weak {
  border-color: #f3dcc3;
  background: #fff8f0;
  color: #bb6c24;
}

.dashboard-source-placeholder {
  min-height: 148px;
  margin-top: 19px;
  display: grid;
  place-items: center;
  border: 1px dashed #dce2eb;
  border-radius: 13px;
  color: #9aa3b2;
  background: #fbfcfd;
  font-size: 11px;
}

.dashboard-stage-summary {
  flex: 1 1 auto;
  min-height: 0;
  margin-top: 16px;
  padding: 18px 18px 17px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 14px;
  border: 1px solid #e1e6ee;
  background: #f7f9fc;
}

.dashboard-stage-summary h3 {
  margin: 0;
  color: #181e2b;
  font-size: 13px;
  font-weight: 800;
}

.dashboard-stage-summary p {
  flex: 1 1 auto;
  min-height: 0;
  margin: 11px 0 0;
  padding-right: 8px;
  overflow-y: auto;
  color: #626d7e;
  font-size: 11px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
  scrollbar-width: thin;
  scrollbar-color: #c8d3e3 transparent;
}

.dashboard-stage-summary p::-webkit-scrollbar {
  width: 5px;
}

.dashboard-stage-summary p::-webkit-scrollbar-track {
  background: transparent;
}

.dashboard-stage-summary p::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #c8d3e3;
}

.dashboard-evaluator {
  height: var(--dashboard-row-height);
  padding: 24px 18px;
  overflow: hidden;
}

.dashboard-evaluator h2 {
  font-size: 14px;
}

.dashboard-score {
  display: block;
  margin-top: 16px;
  color: #00866a;
  font-size: 34px;
  font-weight: 830;
  line-height: 1;
  letter-spacing: -0.045em;
}

.dashboard-score.is-pending {
  font-size: 29px;
  letter-spacing: -0.025em;
}

.dashboard-evaluator > p {
  margin: 7px 0 0;
  color: #8a93a2;
  font-size: 10px;
}

.dashboard-metric-list {
  margin-top: 22px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.dashboard-metric-list > div {
  min-height: 30px;
  height: 30px;
  padding: 0 11px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid #e2e6ec;
  border-radius: 11px;
  background: #fafbfc;
}

.dashboard-metric-list span {
  color: #6e7788;
  font-size: 8.5px;
  line-height: 1.1;
}

.dashboard-metric-list strong {
  color: #00866a;
  font-size: 10px;
  font-weight: 800;
}

.dashboard-metric-list .tone-neutral strong {
  color: #2468f2;
}

.dashboard-metric-list .tone-warn strong {
  color: #c45b00;
}

.dashboard-metric-list .tone-danger strong {
  color: #c84e57;
}

.dashboard-report-preview {
  width: min(100%, var(--dashboard-content-width));
  margin-top: 20px;
  height: auto;
  min-height: 0;
  flex: 1 1 0;
  padding: 25px 27px 27px;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
}

.dashboard-report-preview h2 {
  font-size: 15px;
}

.dashboard-report-preview > header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e7eaf0;
}

.dashboard-report-preview > header button {
  max-width: 44%;
  overflow: hidden;
  border: none;
  background: none;
  color: #3c68bc;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.dashboard-report-body {
  flex: 1 1 auto;
  min-height: 0;
  margin-top: 17px;
  padding-right: 10px;
  overflow-y: auto;
  color: #566070;
  font-size: 12px;
  line-height: 1.8;
  scrollbar-width: thin;
  scrollbar-color: #c8d3e3 transparent;
}

.dashboard-report-body::-webkit-scrollbar {
  width: 6px;
}

.dashboard-report-body::-webkit-scrollbar-track {
  background: transparent;
}

.dashboard-report-body::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #c8d3e3;
}

.dashboard-report-body > span {
  display: block;
  min-height: 1.8em;
  white-space: pre-wrap;
  word-break: break-word;
}

.dashboard-report-body > span.heading {
  margin: 8px 0 2px;
  color: #19202e;
  font-size: 13px;
  font-weight: 800;
}

.dashboard-report-placeholder strong {
  display: block;
  margin-top: 10px;
  color: #19202e;
  font-size: 13px;
}

.dashboard-report-placeholder p {
  margin: 7px 0 0;
}

.dashboard-error {
  margin-top: 16px;
  padding: 11px 13px;
  border: 1px solid #f4c9cd;
  border-radius: 10px;
  background: #fff4f5;
  color: #b33f4a;
  font-size: 11px;
}

.dashboard-run-log {
  margin-top: 28px;
  padding: 0;
  overflow: hidden;
}

.dashboard-run-log > summary {
  min-height: 66px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  list-style: none;
  cursor: pointer;
}

.dashboard-run-log > summary::-webkit-details-marker {
  display: none;
}

.dashboard-run-log > summary span {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.dashboard-run-log > summary strong {
  color: #1b2230;
  font-size: 14px;
}

.dashboard-run-log > summary small,
.dashboard-run-log > summary em {
  color: #8791a2;
  font-size: 10px;
  font-style: normal;
}

.dashboard-run-log .debug-tabs {
  margin: 0 24px 16px;
}

.dashboard-log-list {
  max-height: 280px;
  margin: 0 24px 24px;
  overflow: auto;
}

.dashboard-log-list p {
  margin: 0;
  padding: 9px 0;
  border-bottom: 1px solid #edf0f4;
  color: #5f6878;
  font-size: 11px;
  line-height: 1.55;
}

.dashboard-run-log .trace-wrapper,
.dashboard-run-log .event-payload {
  margin: 0 24px 24px;
}

@media (max-width: 1220px) {
  .dashboard-shell {
    --dashboard-main-right-padding: 28px;
    --dashboard-content-width: calc(225px + 354px + 20px);
  }

  .dashboard-sidebar {
    padding-right: 20px;
    padding-left: 20px;
  }

  .dashboard-main {
    padding-top: 0;
    padding-right: var(--dashboard-main-right-padding);
    padding-left: var(--dashboard-main-left-padding);
  }

  .dashboard-workspace {
    grid-template-columns: 225px 354px;
  }

  .dashboard-evaluator {
    grid-column: 1 / -1;
    height: auto;
    min-height: 0;
  }

  .dashboard-metric-list {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .layout-centered {
    flex-direction: row;
    align-items: center;
  }

  .dashboard-layout {
    height: auto;
    min-height: 100vh;
    overflow: visible;
  }

  .dashboard-shell {
    display: block;
    height: auto;
  }

  .dashboard-sidebar {
    position: relative;
    width: 100%;
    height: auto;
    min-height: 0;
    padding: 18px 22px;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 18px;
  }

  .dashboard-brand {
    width: auto;
  }

  .dashboard-brand-mark {
    width: 42px;
    height: 42px;
    flex-basis: 42px;
  }

  .dashboard-brand strong {
    font-size: 14px;
  }

  .dashboard-nav {
    margin: 0;
    flex-direction: row;
    justify-content: flex-start;
    overflow-x: auto;
  }

  .dashboard-nav a {
    min-width: max-content;
  }

  .dashboard-nav-icon,
  .dashboard-baseline,
  .dashboard-sidebar-spacer {
    display: none;
  }

  .dashboard-new-research {
    min-width: 118px;
    margin: 0;
  }

  .dashboard-main {
    height: auto;
    padding-top: 28px;
    overflow: visible;
  }

  .dashboard-artifact-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .dashboard-workspace {
    grid-template-columns: 1fr;
  }

  .dashboard-task-list,
  .dashboard-current-task,
  .dashboard-evaluator {
    height: auto;
    min-height: 0;
  }
}

@media (max-width: 640px) {
  .dashboard-sidebar {
    grid-template-columns: 1fr auto;
  }

  .dashboard-nav {
    grid-column: 1 / -1;
    justify-content: flex-start;
    order: 3;
  }

  .dashboard-nav a {
    padding: 0 12px;
  }

  .dashboard-main {
    padding: 24px 16px 36px;
  }

  .dashboard-hero {
    display: block;
  }

  .dashboard-hero-badges {
    margin-top: 18px;
    justify-content: flex-start;
  }

  .dashboard-artifact-grid {
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .dashboard-artifact-grid article {
    height: 62px;
    display: block;
    padding: 11px 13px;
  }

  .dashboard-artifact-grid strong {
    display: block;
    margin-top: 7px;
    text-align: left;
  }

  .dashboard-current-task,
  .dashboard-task-list,
  .dashboard-evaluator,
  .dashboard-report-preview {
    padding-right: 18px;
    padding-left: 18px;
  }

  .dashboard-metric-list {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
