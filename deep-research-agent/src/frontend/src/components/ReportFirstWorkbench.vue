<template>
  <section class="report-first-shell">
    <header class="report-first-topbar">
      <button
        type="button"
        class="report-first-brand"
        :disabled="loading"
        @click="$emit('back')"
      >
        <span class="report-first-brand-mark" aria-hidden="true">＋</span>
        <span>
          <strong>深度研究</strong>
          <small>Deep Research</small>
        </span>
      </button>

      <nav class="report-first-topbar-tabs" aria-label="内容视图">
        <button
          type="button"
          :class="{ active: selectedView === 'report' }"
          @click="$emit('select-report')"
        >
          研究报告
        </button>
        <button
          type="button"
          :class="{ active: selectedView === 'evidence' }"
          @click="$emit('select-evidence')"
        >
          证据表
        </button>
        <button
          type="button"
          :class="{ active: selectedView === 'run' }"
          @click="openRunRecord(null)"
        >
          运行记录
        </button>
      </nav>

      <div class="report-first-topbar-actions">
        <span>{{ backend || "hybrid" }}</span>
        <button
          type="button"
          class="report-first-topbar-new"
          @click="$emit('new-research')"
        >
          ＋ 新建研究
        </button>
      </div>
    </header>

    <div class="report-first-grid">
      <aside class="report-first-index">
        <header>
          <span>RESEARCH INDEX</span>
          <h1 :title="topic || '等待研究主题'">{{ topic || "等待研究主题" }}</h1>
          <p>{{ loading ? "research in progress" : `${completedTasks}/${totalTasks || 0} completed` }}</p>
        </header>

        <section class="report-first-task-nav">
          <h2>研究任务</h2>
          <div v-if="tasks.length" class="report-first-task-list">
            <button
              v-for="(task, index) in tasks"
              :key="task.id"
              type="button"
              :class="{
                selected: selectedView === 'task' && selectedTask?.id === task.id
              }"
              @click="$emit('select-task', task.id)"
            >
              <span>{{ String(index + 1).padStart(2, "0") }}</span>
              <span>
                <strong>{{ task.title }}</strong>
                <small>
                  {{ task.sourceItems.length }} sources · {{ formatTaskStatus(task.status) }}
                </small>
              </span>
            </button>
          </div>
          <div v-else class="report-first-task-empty">
            规划器正在生成任务入口…
          </div>
        </section>

        <button
          type="button"
          class="report-first-report-link"
          :class="{ selected: selectedView === 'report' }"
          @click="$emit('select-report')"
        >
          <span aria-hidden="true">▤</span>
          <span>
            <strong>报告概览</strong>
            <small>已完成 {{ completedTasks }}/{{ totalTasks || 0 }} 个任务</small>
          </span>
        </button>

        <div class="report-first-index-spacer"></div>

        <section v-if="reportNoteId || reportNotePath" class="report-first-note">
          <span>报告笔记</span>
          <strong :title="reportNotePath || reportNoteId">{{ reportNoteId || "报告笔记" }}</strong>
          <button
            v-if="reportNotePath"
            type="button"
            @click="$emit('copy-note', reportNotePath)"
          >
            复制笔记路径
          </button>
        </section>

      </aside>

      <main class="report-first-reader">
        <article v-if="selectedView === 'task'" class="report-first-document">
          <template v-if="selectedTask">
            <header
              class="report-first-document-head report-first-task-head"
              :class="{ 'with-task-note': selectedTaskMetaVisible }"
            >
              <div>
                <span>RESEARCH TASK {{ selectedTaskNumber }}</span>
                <h2 :title="selectedTask.title">{{ selectedTask.title }}</h2>
                <p>{{ selectedTask.intent || "围绕研究主题收集、筛选并总结可追溯证据。" }}</p>
              </div>
              <em>{{ formatTaskStatus(selectedTask.status) }}</em>
              <div v-if="selectedTaskMetaVisible" class="report-first-task-meta">
                <div
                  v-if="selectedTaskNoteLabel"
                  class="report-first-task-note"
                  :title="selectedTaskNoteLabel"
                >
                  <span>研究笔记：</span>
                  <strong>{{ selectedTaskNoteLabel }}</strong>
                  <button
                    v-if="selectedTaskNoteCopyPath"
                    type="button"
                    @click="$emit('copy-note', selectedTaskNoteCopyPath)"
                    >
                      复制
                    </button>
                </div>
                <button
                  v-if="selectedTaskRunEventCount > 0"
                  type="button"
                  class="report-first-task-run-link"
                  @click="openRunRecord(selectedTask.id)"
                >
                  <span>运行记录</span>
                  <strong>{{ selectedTaskRunEventCount }}</strong>
                  <span>条</span>
                  <em>查看</em>
                </button>
              </div>
            </header>

            <section class="report-first-summary">
              <h3>任务总结</h3>
              <p>
                {{
                  selectedTaskSummary ||
                  "该任务正在执行。检索与总结完成后，这里会展示当前任务的独立研究结论。"
                }}
              </p>
            </section>

            <section v-if="selectedTaskSummaryDone" class="report-first-sources">
              <header>
                <h3>检索来源</h3>
              </header>

              <ol v-if="selectedTask.sourceItems.length" class="report-first-source-list">
                <li
                  v-for="(source, index) in selectedTask.sourceItems"
                  :key="source.sourceId || source.url || `${source.title}-${index}`"
                >
                  <a v-if="source.url" :href="source.url" target="_blank" rel="noreferrer">
                    {{ source.title || source.url }}
                  </a>
                  <strong v-else>{{ source.title || "未命名来源" }}</strong>
                </li>
              </ol>
              <div v-else class="report-first-source-empty">
                当前任务没有返回可展示的检索来源。
              </div>
            </section>
          </template>

          <div v-else class="report-first-document-empty">
            <span>RESEARCH TASK</span>
            <h2>等待任务规划</h2>
            <p>任务生成后，可从左侧选择任意任务查看独立内容。</p>
          </div>
        </article>

        <article v-else-if="selectedView === 'report'" class="report-first-document report-first-report">
          <header class="report-first-document-head">
            <div>
              <span>RESEARCH REPORT</span>
              <h2 :title="topic || '最终研究报告'">{{ topic || "最终研究报告" }}</h2>
              <p>基于全部研究任务、证据来源和规则质检生成的最终报告。</p>
            </div>
            <button
              v-if="reportNotePath"
              type="button"
              @click="$emit('copy-note', reportNotePath)"
            >
              复制笔记
            </button>
          </header>

          <div v-if="error" class="report-first-error">{{ error }}</div>

          <div v-if="reportReady" class="report-first-report-body">
            <span
              v-for="(line, index) in visibleReportLines"
              :key="`${index}-${line.text.slice(0, 24)}`"
              :class="{
                heading: line.isHeading,
                blank: line.isBlank,
                'first-report-heading': line.isFirstHeading
              }"
            >
              {{ line.displayText || "\u00a0" }}
            </span>

            <section v-if="reportReferences.length" class="report-first-references">
              <h3>参考文献</h3>
              <ol class="report-first-reference-list">
                <li
                  v-for="(reference, index) in reportReferences"
                  :key="reference.url || `${reference.label}-${index}`"
                >
                  <a
                    v-if="reference.url"
                    :href="reference.url"
                    target="_blank"
                    rel="noreferrer"
                    :title="reference.label"
                  >
                    {{ reference.label }}
                  </a>
                  <strong v-else :title="reference.label">{{ reference.label }}</strong>
                </li>
              </ol>
            </section>
          </div>

          <div v-else class="report-first-report-waiting">
            <span>REPORT STATUS</span>
            <h3>{{ reportStatusTitle }}</h3>
            <p>{{ reportStatusText }}</p>
            <div class="report-first-report-progress">
              <span
                :style="{
                  width: `${totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0}%`
                }"
              ></span>
            </div>
            <small>{{ completedTasks }} / {{ totalTasks || 0 }} research tasks completed</small>
          </div>
        </article>

        <article v-else-if="selectedView === 'evidence'" class="report-first-document report-first-evidence">
          <header class="report-first-document-head">
            <div>
              <span>EVIDENCE TABLE</span>
              <h2>证据表</h2>
              <p>汇总全部研究任务的检索来源，方便核对报告依据和来源质量。</p>
            </div>
            <em>{{ filteredEvidenceRows.length }} 条证据</em>
          </header>

          <div class="report-first-evidence-metrics">
            <button
              type="button"
              :class="{ active: evidenceFilter === 'all' }"
              @click="evidenceFilter = 'all'"
            >
              <strong>{{ evidenceRows.length }}</strong>
              <span>全部来源</span>
            </button>
            <button
              type="button"
              :class="{ active: evidenceFilter === 'cited' }"
              @click="evidenceFilter = 'cited'"
            >
              <strong>{{ citedEvidenceCount }}</strong>
              <span>已被引用</span>
            </button>
            <button
              type="button"
              :class="{ active: evidenceFilter === 'strong' }"
              @click="evidenceFilter = 'strong'"
            >
              <strong>{{ strongEvidenceCount }}</strong>
              <span>高质量来源</span>
            </button>
            <span>
              <strong>{{ evidenceDomainCount }}</strong>
              <span>唯一域名</span>
            </span>
          </div>

          <div v-if="evidenceRows.length" class="report-first-evidence-list">
            <details
              v-for="row in filteredEvidenceRows"
              :key="row.id"
              class="report-first-evidence-row"
            >
              <summary class="report-first-evidence-summary">
                <span class="report-first-evidence-task">{{ row.taskNumber }}</span>
                <span class="report-first-evidence-main">
                  <a
                    v-if="row.url"
                    class="report-first-evidence-title"
                    :href="row.url"
                    target="_blank"
                    rel="noreferrer"
                    :title="row.title"
                    @click.stop
                  >
                    {{ row.title }}
                  </a>
                  <strong v-else class="report-first-evidence-title" :title="row.title">{{ row.title }}</strong>
                  <small>{{ row.taskTitle }}</small>
                  <span class="report-first-evidence-meta">
                    <span :class="row.sourceTone">{{ row.sourceTypeLabel }}</span>
                    <span>{{ row.domain || "unknown domain" }}</span>
                    <span v-if="row.scoreLabel">{{ row.scoreLabel }}</span>
                  </span>
                </span>
                <span :class="['report-first-evidence-citation', { cited: row.isCited }]">
                  {{ row.isCited ? `引用 ${row.citationCount}` : "未引用" }}
                </span>
              </summary>

              <div class="report-first-evidence-detail">
                <p v-if="row.snippet">{{ row.snippet }}</p>
                <p v-else-if="row.raw">{{ row.raw }}</p>
                <ul v-if="row.reasons.length">
                  <li v-for="reason in row.reasons" :key="reason">{{ reason }}</li>
                </ul>
              </div>
            </details>

            <div v-if="!filteredEvidenceRows.length" class="report-first-evidence-empty">
              当前筛选下暂无证据。
            </div>
          </div>

          <div v-else class="report-first-report-waiting">
            <span>EVIDENCE STATUS</span>
            <h3>等待证据来源</h3>
            <p>研究任务完成检索后，来源、引用状态和质量标记会在这里汇总展示。</p>
          </div>
        </article>

        <article v-else class="report-first-document report-first-run">
          <header class="report-first-document-head">
            <div>
              <span>RUN RECORD</span>
              <h2>运行记录</h2>
              <p>按事件顺序展示本次研究的完整运行过程，不影响任务总结和最终报告。</p>
            </div>
            <em>{{ runRecordCount }} 条记录</em>
          </header>

          <template v-if="runEvents.length">
            <div v-if="runTaskFilter !== null" class="report-first-run-scope">
              <span>{{ activeRunTaskLabel }}</span>
              <button type="button" @click="clearRunTaskFilter">查看全部任务</button>
            </div>

            <div class="report-first-run-filters" aria-label="运行记录阶段筛选">
              <button
                v-for="option in runStageFilterOptions"
                :key="option.value"
                type="button"
                :class="{ active: runStageFilter === option.value }"
                :aria-pressed="runStageFilter === option.value"
                @click="runStageFilter = option.value"
              >
                <span>{{ option.label }}</span>
                <strong>{{ option.count }}</strong>
              </button>
            </div>

            <div v-if="filteredRunEvents.length" class="report-first-run-list">
              <article
                v-for="event in filteredRunEvents"
                :key="`${event.seq}-${event.type}`"
                class="report-first-run-item"
                :class="`status-${event.status || 'unknown'}`"
              >
                <header>
                  <span>#{{ event.seq }}</span>
                  <strong>{{ formatRunEventTitle(event) }}</strong>
                  <em>{{ formatRunStatus(event.status) }}</em>
                </header>
                <p v-if="event.message">{{ event.message }}</p>
                <dl>
                  <div>
                    <dt>阶段</dt>
                    <dd>{{ formatRunStage(event) }}</dd>
                  </div>
                  <div v-if="event.agent">
                    <dt>Agent</dt>
                    <dd>{{ event.agent }}</dd>
                  </div>
                  <div v-if="event.task_id !== null">
                    <dt>任务</dt>
                    <dd>{{ event.task_id }}</dd>
                  </div>
                  <div v-if="formatRunTime(event.timestamp)">
                    <dt>时间</dt>
                    <dd>{{ formatRunTime(event.timestamp) }}</dd>
                  </div>
                </dl>
                <pre v-if="formatRunPayload(event)">{{ formatRunPayload(event) }}</pre>
              </article>
            </div>

            <div v-else class="report-first-run-empty">
              当前阶段暂无运行记录。
            </div>
          </template>

          <ol v-else-if="runLogs.length" class="report-first-run-log-list">
            <li v-for="(log, index) in runLogs" :key="`${index}-${log}`">
              <span>{{ String(index + 1).padStart(2, "0") }}</span>
              <p>{{ log }}</p>
            </li>
          </ol>

          <div v-else class="report-first-report-waiting">
            <span>RUN STATUS</span>
            <h3>等待运行记录</h3>
            <p>研究启动后，连接、规划、检索、总结和报告生成事件会出现在这里。</p>
          </div>
        </article>
      </main>

      <aside class="report-first-evaluator">
        <h2>质检器</h2>
        <section class="report-first-score">
          <span class="report-first-score-label">质检评分</span>
          <div class="report-first-score-row">
            <strong>{{ evaluatorScoreDisplay }}</strong>
            <em :class="{ passed: qualityPassed }">
              {{ evaluatorStatusLabel }}
            </em>
          </div>
        </section>

        <h3>质量指标</h3>
        <div class="report-first-metrics">
          <div
            v-for="metric in qualityMetrics"
            :key="metric.key"
            :class="`tone-${metric.tone}`"
          >
            <span>{{ localizedMetricLabel(metric) }}</span>
            <strong>{{ metric.value }}</strong>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<script lang="ts" setup>
import { computed, ref } from "vue";

type ScoreTone = "good" | "warn" | "danger" | "neutral";
type EvidenceFilter = "all" | "cited" | "strong";
type RunStageFilter =
  | "all"
  | "planner"
  | "search"
  | "summary"
  | "reporter"
  | "evaluator"
  | "reflection";

interface SourceView {
  sourceId?: string;
  sourceType?: string;
  score?: string | number;
  scoreLabel?: string;
  domain?: string;
  searchQuery?: string;
  reasons?: string[];
  title: string;
  url: string;
  snippet: string;
  raw?: string;
}

interface TaskView {
  id: number;
  title: string;
  intent: string;
  status: string;
  summary: string;
  sourceItems: SourceView[];
  citations: string[];
  noteId: string | null;
  notePath: string | null;
}

interface QualityMetric {
  key: string;
  label: string;
  value: string;
  tone: ScoreTone;
}

interface ReportLine {
  text: string;
  isHeading: boolean;
  isBlank: boolean;
}

interface VisibleReportLine extends ReportLine {
  isFirstHeading: boolean;
  displayText: string;
}

interface ReportReference {
  label: string;
  url: string;
}

interface RunEvent {
  run_id: string;
  seq: number;
  type: string;
  stage: string;
  status: string;
  message: string;
  step: number;
  task_id: number | null;
  agent?: string | null;
  payload: Record<string, unknown>;
  error: Record<string, unknown> | null;
  timestamp?: number;
}

interface EvidenceRow {
  id: string;
  taskNumber: string;
  taskTitle: string;
  title: string;
  url: string;
  domain: string;
  sourceTypeLabel: string;
  sourceTone: string;
  scoreLabel: string;
  snippet: string;
  raw: string;
  reasons: string[];
  citationCount: number;
  isCited: boolean;
}

interface RunStageOption {
  value: RunStageFilter;
  label: string;
  count: number;
}

const RUN_STAGE_FILTERS: Array<{ value: RunStageFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "planner", label: "planner" },
  { value: "search", label: "search" },
  { value: "summary", label: "summary" },
  { value: "reporter", label: "reporter" },
  { value: "evaluator", label: "evaluator" },
  { value: "reflection", label: "reflection" }
];

const props = defineProps<{
  topic: string;
  backend: string;
  loading: boolean;
  error: string;
  tasks: TaskView[];
  selectedView: "task" | "report" | "evidence" | "run";
  selectedTaskId: number | null;
  completedTasks: number;
  totalTasks: number;
  evaluatorScore: string;
  hardErrorCount: string;
  qualityPassed: boolean;
  qualityMetrics: QualityMetric[];
  reportReady: boolean;
  reportLines: ReportLine[];
  reportNoteId: string;
  reportNotePath: string;
  runLogs: string[];
  runEvents: RunEvent[];
}>();

const evidenceFilter = ref<EvidenceFilter>("all");
const runStageFilter = ref<RunStageFilter>("all");
const runTaskFilter = ref<number | null>(null);

const emit = defineEmits<{
  (event: "select-task", taskId: number): void;
  (event: "select-report"): void;
  (event: "select-evidence"): void;
  (event: "select-run-record"): void;
  (event: "new-research"): void;
  (event: "back"): void;
  (event: "copy-note", path: string): void;
}>();

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

const QUALITY_METRIC_LABELS: Record<string, string> = {
  citation_precision: "引用准确率",
  citation_recall: "引用召回率",
  primary_source_ratio: "一手来源比例",
  weak_source_ratio: "弱来源比例",
  max_domain_concentration: "域名集中度",
  hard_error_count: "硬错误"
};

function localizedMetricLabel(metric: QualityMetric): string {
  return QUALITY_METRIC_LABELS[metric.key] ?? metric.label;
}

function truncateInline(value: string | undefined, max = 280): string {
  const trimmed = (value || "").trim();
  return trimmed.length > max ? `${trimmed.slice(0, max)}…` : trimmed;
}

function formatEvidenceDomain(source: SourceView): string {
  if (source.domain) {
    return source.domain;
  }
  if (!source.url) {
    return "";
  }

  try {
    return new URL(source.url).hostname.replace(/^www\./u, "");
  } catch {
    return "";
  }
}

function formatEvidenceSourceType(sourceType: string | undefined): string {
  const labels: Record<string, string> = {
    academic: "学术来源",
    official_doc: "官方文档",
    company_tech: "企业技术",
    blog: "博客",
    marketing: "营销内容",
    unknown: "未知来源"
  };
  return labels[(sourceType || "").toLowerCase()] ?? (sourceType || "unknown");
}

function evidenceSourceTone(sourceType: string | undefined): string {
  const normalized = (sourceType || "").toLowerCase();
  if (["academic", "official_doc", "company_tech"].includes(normalized)) {
    return "source-tone-strong";
  }
  if (["blog", "marketing", "unknown"].includes(normalized)) {
    return "source-tone-weak";
  }
  return "source-tone-neutral";
}

function formatEvidenceScore(source: SourceView): string {
  if (source.scoreLabel) {
    return source.scoreLabel;
  }
  if (typeof source.score === "number") {
    return `评分 ${Number.isInteger(source.score) ? source.score : source.score.toFixed(2)}`;
  }
  if (typeof source.score === "string" && source.score.trim()) {
    return source.score.trim().startsWith("评分")
      ? source.score.trim()
      : `评分 ${source.score.trim()}`;
  }
  return "";
}

function citationMatchesSource(citation: string, source: SourceView): boolean {
  const normalizedCitation = citation.toLowerCase();
  const sourceId = (source.sourceId || "").toLowerCase();
  const url = (source.url || "").toLowerCase();
  return Boolean(
    (sourceId && normalizedCitation.includes(sourceId)) ||
      (url && normalizedCitation.includes(url))
  );
}

function formatRunStatus(status: string): string {
  const labels: Record<string, string> = {
    started: "开始",
    running: "运行中",
    success: "成功",
    completed: "完成",
    failed: "失败",
    skipped: "跳过",
    warning: "警告",
    cancelled: "已取消"
  };
  return labels[status] ?? (status || "unknown");
}

function formatRunEventTitle(event: RunEvent): string {
  const eventLabels: Record<string, string> = {
    workflow_started: "研究流程启动",
    workflow_done: "研究流程完成",
    workflow_failed: "研究流程失败",
    task_started: "任务开始",
    task_done: "任务完成",
    task_failed: "任务失败",
    tool_call: "工具调用",
    tool_result: "工具返回",
    note_updated: "笔记更新",
    report_started: "报告生成启动",
    report_done: "报告生成完成",
    evaluator_done: "质检完成",
    reflection_started: "报告反思启动",
    reflection_done: "报告反思完成",
    reflection_skipped: "报告反思跳过",
    reflection_failed: "报告反思失败",
    api_error: "接口错误"
  };
  return eventLabels[event.type] ?? (event.type || "运行事件");
}

function runEventBusinessStage(event: RunEvent): string {
  const businessStage = event.payload?.business_stage;
  return typeof businessStage === "string" ? businessStage.toLowerCase() : "";
}

function normalizeRunStage(event: RunEvent): RunStageFilter | "workflow" | "task" | "other" {
  const stage = (event.stage || "").toLowerCase();
  const type = (event.type || "").toLowerCase();
  const agent = (event.agent || "").toLowerCase();
  const businessStage = runEventBusinessStage(event);

  if (stage === "planner" || type.includes("planner") || agent.includes("planner")) {
    return "planner";
  }
  if (
    stage === "search" ||
    stage === "searcher" ||
    type.includes("search") ||
    agent.includes("search")
  ) {
    return "search";
  }
  if (stage === "summary" || businessStage === "summary" || type.includes("summary")) {
    return "summary";
  }
  if (
    stage === "reporter" ||
    businessStage === "reporter" ||
    type.includes("report")
  ) {
    return "reporter";
  }
  if (stage === "evaluator" || type.includes("evaluator")) {
    return "evaluator";
  }
  if (stage === "reflection" || type.includes("reflection")) {
    return "reflection";
  }
  if (stage === "workflow") {
    return "workflow";
  }
  if (stage === "task") {
    return "task";
  }
  return "other";
}

function formatRunStage(event: RunEvent): string {
  const labels: Record<string, string> = {
    planner: "planner",
    search: "search",
    summary: "summary",
    reporter: "reporter",
    evaluator: "evaluator",
    reflection: "reflection",
    workflow: "workflow",
    task: "task",
    other: event.stage || "unknown"
  };
  return labels[normalizeRunStage(event)];
}

function runEventMatchesStage(event: RunEvent, filter: RunStageFilter): boolean {
  return filter === "all" || normalizeRunStage(event) === filter;
}

function runEventTaskId(event: RunEvent): number | null {
  if (typeof event.task_id === "number") {
    return event.task_id;
  }

  const payloadTaskId = event.payload?.task_id;
  if (typeof payloadTaskId === "number") {
    return payloadTaskId;
  }
  if (typeof payloadTaskId === "string" && payloadTaskId.trim()) {
    const numeric = Number(payloadTaskId);
    return Number.isFinite(numeric) ? numeric : null;
  }

  const payloadTask = event.payload?.task;
  if (payloadTask && typeof payloadTask === "object" && "id" in payloadTask) {
    const taskId = (payloadTask as { id?: unknown }).id;
    if (typeof taskId === "number") {
      return taskId;
    }
    if (typeof taskId === "string" && taskId.trim()) {
      const numeric = Number(taskId);
      return Number.isFinite(numeric) ? numeric : null;
    }
  }

  return null;
}

function runEventMatchesTask(event: RunEvent, taskId: number | null): boolean {
  return taskId === null || runEventTaskId(event) === taskId;
}

function formatRunTime(timestamp: number | undefined): string {
  if (!timestamp) {
    return "";
  }
  return new Date(timestamp * 1000).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatRunPayload(event: RunEvent): string {
  const detail: Record<string, unknown> = {};
  if (event.error) {
    detail.error = event.error;
  }
  if (event.payload && Object.keys(event.payload).length) {
    detail.payload = event.payload;
  }
  if (!Object.keys(detail).length) {
    return "";
  }

  return JSON.stringify(
    detail,
    (_key, value) => {
      if (typeof value === "string" && value.length > 600) {
        return `${value.slice(0, 600)}…`;
      }
      return value;
    },
    2
  );
}

const evaluatorScoreDisplay = computed(() =>
  props.evaluatorScore.toLowerCase() === "pending" ? "待定" : props.evaluatorScore
);

const evaluatorStatusLabel = computed(() => {
  if (props.qualityPassed) {
    return "质检通过";
  }
  if (props.loading) {
    return "质检中";
  }
  return evaluatorScoreDisplay.value === "待定" ? "待质检" : "质检失败";
});

const selectedTask = computed(() => {
  if (props.selectedTaskId !== null) {
    const task = props.tasks.find((item) => item.id === props.selectedTaskId);
    if (task) {
      return task;
    }
  }
  return props.tasks[0] ?? null;
});

const selectedTaskNumber = computed(() => {
  const index = props.tasks.findIndex((task) => task.id === selectedTask.value?.id);
  return String(Math.max(index + 1, 1)).padStart(2, "0");
});

const selectedTaskSummary = computed(() =>
  (selectedTask.value?.summary || "")
    .replace(/^\s*#{1,6}\s*任务总结\s*/u, "")
    .trim()
);

const selectedTaskNoteLabel = computed(() =>
  formatNotePath(selectedTask.value?.notePath || "") || selectedTask.value?.noteId || ""
);

const selectedTaskNoteCopyPath = computed(() =>
  formatNotePath(selectedTask.value?.notePath || "")
);

const selectedTaskRunEventCount = computed(() => {
  const taskId = selectedTask.value?.id ?? null;
  if (taskId === null) {
    return 0;
  }
  return props.runEvents.filter((event) => runEventMatchesTask(event, taskId)).length;
});

const selectedTaskMetaVisible = computed(() =>
  Boolean(selectedTaskNoteLabel.value || selectedTaskRunEventCount.value > 0)
);

const selectedTaskSummaryDone = computed(() => {
  const status = selectedTask.value?.status || "";
  return Boolean(selectedTaskSummary.value) || ["completed", "skipped", "failed"].includes(status);
});

function formatNotePath(path: string): string {
  const normalized = path.replace(/\\/g, "/").trim();
  if (!normalized) {
    return "";
  }

  const notesIndex = normalized.lastIndexOf("/notes/");
  if (notesIndex >= 0) {
    return normalized.slice(notesIndex + 1);
  }

  if (normalized.startsWith("notes/")) {
    return normalized;
  }

  return normalized;
}

function openRunRecord(taskId: number | null): void {
  runTaskFilter.value = taskId;
  runStageFilter.value = "all";
  emit("select-run-record");
}

function clearRunTaskFilter(): void {
  runTaskFilter.value = null;
  runStageFilter.value = "all";
}

const runTaskFilteredEvents = computed(() =>
  props.runEvents.filter((event) => runEventMatchesTask(event, runTaskFilter.value))
);

const filteredRunEvents = computed(() =>
  runTaskFilteredEvents.value.filter((event) => runEventMatchesStage(event, runStageFilter.value))
);

const runStageFilterOptions = computed<RunStageOption[]>(() =>
  RUN_STAGE_FILTERS.map((option) => ({
    ...option,
    count:
      option.value === "all"
        ? runTaskFilteredEvents.value.length
        : runTaskFilteredEvents.value.filter((event) => runEventMatchesStage(event, option.value)).length
  }))
);

const activeRunTaskLabel = computed(() => {
  const taskId = runTaskFilter.value;
  if (taskId === null) {
    return "";
  }
  const index = props.tasks.findIndex((task) => task.id === taskId);
  const numberLabel = String(Math.max(index + 1, 1)).padStart(2, "0");
  const taskTitle = props.tasks.find((task) => task.id === taskId)?.title || `任务 ${taskId}`;
  return `当前仅看任务 ${numberLabel}：${taskTitle}`;
});

const runRecordCount = computed(() =>
  props.runEvents.length ? filteredRunEvents.value.length : props.runLogs.length
);

const evidenceRows = computed<EvidenceRow[]>(() =>
  props.tasks.flatMap((task, taskIndex) =>
    task.sourceItems.map((source, sourceIndex) => {
      const citationCount = task.citations.filter((citation) =>
        citationMatchesSource(citation, source)
      ).length;
      const title = source.title || source.url || "未命名来源";

      return {
        id: `${task.id}-${source.sourceId || source.url || title}-${sourceIndex}`,
        taskNumber: String(taskIndex + 1).padStart(2, "0"),
        taskTitle: task.title || `任务 ${taskIndex + 1}`,
        title,
        url: source.url || "",
        domain: formatEvidenceDomain(source),
        sourceTypeLabel: formatEvidenceSourceType(source.sourceType),
        sourceTone: evidenceSourceTone(source.sourceType),
        scoreLabel: formatEvidenceScore(source),
        snippet: truncateInline(source.snippet, 320),
        raw: truncateInline(source.raw, 320),
        reasons: (source.reasons || []).slice(0, 3).map((reason) => truncateInline(reason, 180)),
        citationCount,
        isCited: citationCount > 0
      };
    })
  )
);

const filteredEvidenceRows = computed(() => {
  if (evidenceFilter.value === "cited") {
    return evidenceRows.value.filter((row) => row.isCited);
  }
  if (evidenceFilter.value === "strong") {
    return evidenceRows.value.filter((row) => row.sourceTone === "source-tone-strong");
  }
  return evidenceRows.value;
});

const citedEvidenceCount = computed(() =>
  evidenceRows.value.filter((row) => row.isCited).length
);

const strongEvidenceCount = computed(() =>
  evidenceRows.value.filter((row) => row.sourceTone === "source-tone-strong").length
);

const evidenceDomainCount = computed(() => {
  const domains = new Set(
    evidenceRows.value.map((row) => row.domain).filter(Boolean)
  );
  return domains.size;
});

function isReportSection(line: ReportLine, section: "参考文献" | "证据表"): boolean {
  return new RegExp(`^#{1,6}\\s*${section}\\s*$`, "u").test(line.text.trim());
}

const reportReferences = computed<ReportReference[]>(() => {
  const referenceHeadingIndex = props.reportLines.findIndex((line) =>
    isReportSection(line, "参考文献")
  );
  if (referenceHeadingIndex < 0) {
    return [];
  }

  const nextHeadingOffset = props.reportLines
    .slice(referenceHeadingIndex + 1)
    .findIndex((line) => line.isHeading);
  const referenceEndIndex =
    nextHeadingOffset >= 0
      ? referenceHeadingIndex + 1 + nextHeadingOffset
      : props.reportLines.length;

  return props.reportLines
    .slice(referenceHeadingIndex + 1, referenceEndIndex)
    .filter((line) => !line.isBlank && !line.isHeading)
    .map((line, index) => {
      const rawReference = line.text.trim();
      const urlMatch = rawReference.match(/https?:\/\/\S+/u);
      const matchedUrl = urlMatch?.[0] ?? "";
      const url = matchedUrl.replace(/[)\],.;，。；]+$/u, "");
      const label =
        rawReference
          .replace(/^\s*\[[^\]]+\]\s*/u, "")
          .replace(matchedUrl, "")
          .replace(/\s*[–—-]\s*$/u, "")
          .trim() || `参考文献 ${index + 1}`;

      return { label, url };
    });
});

const visibleReportLines = computed<VisibleReportLine[]>(() => {
  const firstContentIndex = props.reportLines.findIndex((line) => !line.isBlank);
  let lines = (
    firstContentIndex >= 0 &&
    /^#\s+/.test(props.reportLines[firstContentIndex]?.text || "")
      ? props.reportLines.filter((_, index) => index !== firstContentIndex)
      : props.reportLines
  );

  const hiddenSectionIndex = lines.findIndex(
    (line) => isReportSection(line, "参考文献") || isReportSection(line, "证据表")
  );
  if (hiddenSectionIndex >= 0) {
    lines = lines.slice(0, hiddenSectionIndex);
  }

  while (lines[0]?.isBlank) {
    lines = lines.slice(1);
  }
  while (lines[lines.length - 1]?.isBlank) {
    lines = lines.slice(0, -1);
  }

  const compactLines = lines.filter((line, index) => {
    if (!line.isBlank) {
      return true;
    }
    const previous = lines[index - 1];
    const next = lines[index + 1];
    return !previous?.isHeading && !next?.isHeading && !previous?.isBlank;
  });

  const firstHeadingIndex = compactLines.findIndex((line) => line.isHeading);
  return compactLines.map((line, index) => ({
    ...line,
    displayText: line.isHeading
      ? line.text.replace(/^#{1,6}\s+/u, "").trim()
      : line.text,
    isFirstHeading: index === firstHeadingIndex
  }));
});

const reportStatusTitle = computed(() => {
  if (!props.totalTasks) {
    return "等待任务规划";
  }
  if (props.completedTasks < props.totalTasks) {
    return "研究任务进行中";
  }
  return "正在整合最终报告";
});

const reportStatusText = computed(() => {
  if (!props.totalTasks) {
    return "任务规划完成后，报告器会在这里独立生成最终报告。";
  }
  if (props.completedTasks < props.totalTasks) {
    return `已完成 ${props.completedTasks}/${props.totalTasks} 个任务。这里不会混入当前任务的加载内容。`;
  }
  return "全部任务已完成，报告器正在汇总证据并生成最终报告。";
});
</script>

<style scoped>
.report-first-shell {
  --report-first-workspace-width: 1046px;
  width: 100%;
  flex: 1 1 100%;
  height: 100vh;
  min-height: 0;
  padding: 28px 28px 28px;
  box-sizing: border-box;
  overflow: hidden;
  background:
    radial-gradient(circle at 72% 0%, rgba(226, 236, 255, 0.96), transparent 34%),
    #dbe6f6;
  color: #151b27;
  font-family: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.report-first-topbar {
  width: min(100%, var(--report-first-workspace-width));
  margin: 0 auto;
  min-height: 82px;
  padding: 0 34px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 28px;
  box-sizing: border-box;
  border: 1px solid #d8e1ee;
  border-radius: 26px 26px 0 0;
  background: #ffffff;
}

.report-first-brand {
  padding: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  border: none;
  background: none;
  color: #182018;
  text-align: left;
  cursor: pointer;
}

.report-first-brand:disabled {
  cursor: not-allowed;
}

.report-first-brand-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(145deg, #3871ee, #2455df);
  color: #ffffff;
  font-size: 22px;
}

.report-first-brand strong,
.report-first-brand small {
  display: block;
}

.report-first-brand strong {
  font-size: 14px;
}

.report-first-brand small {
  margin-top: 2px;
  color: #7d8ca4;
  font-size: 10px;
}

.report-first-topbar-tabs {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 4px;
}

.report-first-topbar-tabs button {
  min-height: 34px;
  padding: 0 15px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #8b99ad;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
  cursor: pointer;
  transition: color 160ms ease, background 160ms ease;
}

.report-first-topbar-tabs button:hover,
.report-first-topbar-tabs button.active {
  background: #f2f6fc;
  color: #1d2737;
}

.report-first-topbar-actions {
  display: flex;
  gap: 8px;
}

.report-first-topbar-spacer {
  min-width: 0;
}

.report-first-topbar-actions span {
  min-height: 30px;
  padding: 0 13px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: #f5f7fb;
  color: #617089;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}

.report-first-topbar-actions span.passed {
  background: #2456df;
  color: #ffffff;
}

.report-first-topbar-new {
  min-height: 30px;
  padding: 0 13px;
  border: 1px solid #cfdaeb;
  border-radius: 999px;
  background: #ffffff;
  color: #536681;
  font-size: 10px;
  font-weight: 750;
  white-space: nowrap;
  cursor: pointer;
}

.report-first-topbar-new:hover {
  border-color: #8eb0ee;
  color: #2456df;
  background: #f7faff;
}

.report-first-grid {
  width: min(100%, var(--report-first-workspace-width));
  margin: 0 auto;
  height: calc(100vh - 138px);
  min-height: 0;
  padding: 28px 22px 34px;
  display: grid;
  grid-template-columns: 200px 538px 220px;
  gap: 22px;
  box-sizing: border-box;
  border: 1px solid #d8e1ee;
  border-top: none;
  border-radius: 0 0 26px 26px;
  background: #ffffff;
}

.report-first-index,
.report-first-reader,
.report-first-evaluator {
  min-width: 0;
  border: 1px solid #d7e1ef;
  border-radius: 17px;
  background: #ffffff;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.72);
}

.report-first-index {
  min-height: 0;
  padding: 18px 16px 12px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  scrollbar-width: none;
}

.report-first-index::-webkit-scrollbar {
  display: none;
}

.report-first-index > header {
  padding: 0 4px 14px;
  border-bottom: 1px solid #dce5f0;
}

.report-first-index > header span,
.report-first-task-nav h2,
.report-first-note > span {
  color: #8b9ab1;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.report-first-index > header h1 {
  margin: 9px 0 0;
  display: -webkit-box;
  overflow: hidden;
  font-size: 14px;
  line-height: 1.4;
  text-overflow: ellipsis;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.report-first-index > header p {
  margin: 5px 0 0;
  color: #74849d;
  font-size: 10px;
}

.report-first-task-nav {
  margin-top: 16px;
}

.report-first-task-nav h2 {
  margin: 0 4px 12px;
}

.report-first-task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.report-first-task-list button,
.report-first-report-link {
  width: 100%;
  min-height: 50px;
  padding: 5px 11px;
  display: flex;
  align-items: center;
  gap: 4px;
  border: 1px solid #edf2f8;
  border-radius: 12px;
  background: #f8fafc;
  color: #243049;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}

.report-first-task-list button:hover,
.report-first-report-link:hover {
  transform: translateY(-1px);
}

.report-first-task-list button.selected,
.report-first-report-link.selected {
  border-color: #78aafc;
  background: #eff6ff;
  box-shadow: inset 3px 0 #2d70f3;
}

.report-first-task-list button > span:first-child,
.report-first-report-link > span:first-child {
  flex: 0 0 22px;
  color: #4f6690;
  font-size: 10px;
  font-weight: 800;
}

.report-first-task-list button > span:last-child,
.report-first-report-link > span:last-child {
  min-width: 0;
}

.report-first-task-list strong,
.report-first-task-list small,
.report-first-report-link strong,
.report-first-report-link small {
  display: block;
}

.report-first-task-list strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-task-list small,
.report-first-report-link small {
  margin-top: 5px;
  color: #13805f;
  font-size: 10px;
  font-weight: 750;
}

.report-first-task-empty {
  padding: 18px 12px;
  border: 1px dashed #c8d6e8;
  border-radius: 12px;
  color: #8290a6;
  font-size: 10px;
  line-height: 1.5;
}

.report-first-report-link {
  margin-top: 12px;
}

.report-first-report-link strong {
  font-size: 12px;
}

.report-first-index-spacer {
  flex: 0 0 12px;
  min-height: 12px;
}

.report-first-note {
  margin-top: auto;
  padding: 12px;
  border-radius: 11px;
  background: #101c35;
  color: #ffffff;
}

.report-first-note strong {
  display: block;
  margin-top: 6px;
  overflow: hidden;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-note button {
  width: 100%;
  min-height: 28px;
  margin-top: 8px;
  border: none;
  border-radius: 7px;
  background: #2456df;
  color: #ffffff;
  font-size: 9px;
  font-weight: 700;
  cursor: pointer;
}

.report-first-reader {
  min-height: 0;
  background: #ffffff;
  overflow: hidden;
}

.report-first-document {
  height: 100%;
  min-height: 0;
  padding: 30px;
  box-sizing: border-box;
  overflow-y: auto;
}

.report-first-report {
  padding-top: 30px;
}

.report-first-report .report-first-document-head {
  padding-bottom: 18px;
}

.report-first-document-head {
  padding-bottom: 24px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  border-bottom: 1px solid #e1e8f1;
}

.report-first-task-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: 24px;
  row-gap: 12px;
}

.report-first-document-head.with-task-note {
  padding-bottom: 18px;
}

.report-first-document-head > div {
  flex: 1;
  min-width: 0;
}

.report-first-document-head span,
.report-first-summary > span,
.report-first-sources header span,
.report-first-report-waiting > span {
  color: #2868e6;
  font-size: 9px;
  font-weight: 850;
  letter-spacing: 0.08em;
}

.report-first-document-head h2 {
  margin: 10px 0 0;
  overflow: hidden;
  font-size: 20px;
  line-height: 1.25;
  letter-spacing: -0.035em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-document-head p {
  margin: 9px 0 0;
  color: #424b45;
  font-size: 13px;
  line-height: 1.7;
}

.report-first-task-meta {
  grid-column: 1 / -1;
  width: 100%;
  margin-top: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.report-first-task-note {
  width: 100%;
  min-width: 0;
  height: 30px;
  margin-top: 0;
  padding: 3px 9px 3px 11px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
  border: 1px solid #bae6fd;
  border-radius: 999px;
  background: #f0f9ff;
  color: #0369a1;
  font-size: 11px;
  font-weight: 750;
  line-height: 1;
  white-space: nowrap;
}

.report-first-task-note span {
  color: #0369a1;
  font-size: inherit;
  font-weight: 850;
  letter-spacing: 0;
}

.report-first-task-note strong {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: #075985;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10.5px;
  font-weight: 750;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-document-head .report-first-task-note button {
  flex: 0 0 auto;
  height: 22px;
  min-height: auto;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
  border: none;
  border-radius: 999px;
  background: #bae6fd;
  color: #0369a1;
  font-size: 10px;
  font-weight: 850;
  line-height: 22px;
  white-space: nowrap;
  cursor: pointer;
}

.report-first-document-head .report-first-task-note button:hover {
  background: #a7dcf8;
  color: #075985;
}

.report-first-document-head .report-first-task-run-link {
  width: max-content;
  min-width: 0;
  height: 30px;
  padding: 3px 9px 3px 11px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #bee6d8;
  border-radius: 999px;
  background: #eaf8f2;
  color: #13805f;
  font-family: inherit;
  font-size: 11px;
  font-weight: 750;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease;
}

.report-first-document-head .report-first-task-run-link:hover {
  border-color: #92d8c1;
  background: #def5ec;
  color: #0f7558;
}

.report-first-document-head .report-first-task-run-link span {
  overflow: hidden;
  color: inherit;
  font-size: inherit;
  font-weight: inherit;
  letter-spacing: 0;
  text-overflow: ellipsis;
}

.report-first-document-head .report-first-task-run-link strong {
  color: #0f8a67;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10.5px;
}

.report-first-document-head .report-first-task-run-link em {
  height: 22px;
  padding: 0 8px;
  min-height: auto;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: #c9f1e4;
  color: #13805f;
  font-size: 10px;
  font-style: normal;
  font-weight: 850;
  line-height: 22px;
}

.report-first-document-head em {
  min-height: 30px;
  padding: 0 13px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: #eaf8f2;
  color: #13805f;
  font-size: 10px;
  font-style: normal;
  font-weight: 750;
  white-space: nowrap;
}

.report-first-document-head button {
  min-height: 30px;
  max-width: 200px;
  overflow: hidden;
  padding: 0 13px;
  border: 1px solid #d7e2f0;
  border-radius: 999px;
  background: #f8fafc;
  color: #3b6ea9;
  font-family: inherit;
  font-size: 10px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.report-first-summary {
  margin-top: 24px;
  padding: 0;
}

.report-first-summary h3,
.report-first-sources h3 {
  margin: 9px 0 0;
  font-size: 19px;
}

.report-first-summary p {
  margin: 18px 0 0;
  color: #424b45;
  font-size: 14px;
  line-height: 1.9;
  white-space: pre-wrap;
}

.report-first-sources {
  margin-top: 28px;
}

.report-first-sources header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
}

.report-first-sources header small {
  color: #808780;
  font-size: 10px;
}

.report-first-source-list {
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
  counter-reset: source-item;
}

.report-first-source-list li {
  counter-increment: source-item;
  min-height: 34px;
  padding: 7.5px 0;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: center;
  gap: 2px;
}

.report-first-source-list li::before {
  content: counter(source-item) ".";
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.report-first-source-list a,
.report-first-source-list li > strong {
  overflow: hidden;
  color: #2468f2;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-source-list a:hover {
  text-decoration: underline;
}

.report-first-source-empty,
.report-first-document-empty {
  margin-top: 16px;
  padding: 24px;
  border: 1px dashed #d7d9d4;
  border-radius: 14px;
  color: #858b84;
  font-size: 11px;
}

.report-first-document-empty {
  margin-top: 0;
}

.report-first-document-empty span {
  color: #54806d;
  font-size: 9px;
  font-weight: 800;
}

.report-first-document-empty h2 {
  margin: 12px 0 0;
  color: #222a23;
  font-size: 24px;
}

.report-first-document-empty p {
  margin: 10px 0 0;
  line-height: 1.7;
}

.report-first-report-body {
  margin-top: 0;
  padding-top: 18px;
  color: #424b45;
  font-size: 14px;
  line-height: 1.75;
}

.report-first-report-body > span {
  display: block;
  min-height: 1.75em;
  white-space: pre-wrap;
  word-break: break-word;
}

.report-first-report-body > span.blank {
  min-height: 0.55em;
}

.report-first-report-body > span.heading {
  margin: 18px 0;
  color: #172019;
  font-size: 19px;
  font-weight: 800;
  line-height: 1.45;
}

.report-first-report-body > span.heading.first-report-heading {
  margin-top: 0;
}

.report-first-references {
  margin-top: 18px;
}

.report-first-references h3 {
  margin: 0 0 10px;
  color: #172019;
  font-size: 19px;
  font-weight: 800;
  line-height: 1.45;
}

.report-first-reference-list {
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: report-reference;
}

.report-first-reference-list li {
  counter-increment: report-reference;
  min-height: 34px;
  padding: 7.5px 0;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: center;
  gap: 2px;
}

.report-first-reference-list li::before {
  content: counter(report-reference) ".";
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.report-first-reference-list a,
.report-first-reference-list li > strong {
  overflow: hidden;
  color: #2468f2;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-reference-list a:hover {
  text-decoration: underline;
}

.report-first-report-waiting {
  margin-top: 30px;
  padding: 32px;
  border-radius: 16px;
  background: #f3f7fd;
}

.report-first-report-waiting h3 {
  margin: 12px 0 0;
  font-size: 22px;
}

.report-first-report-waiting p {
  margin: 12px 0 0;
  color: #6e766f;
  font-size: 13px;
  line-height: 1.75;
}

.report-first-report-progress {
  height: 7px;
  margin-top: 24px;
  overflow: hidden;
  border-radius: 999px;
  background: #dce6f4;
}

.report-first-report-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #2d70ef;
  transition: width 300ms ease;
}

.report-first-report-waiting small {
  display: block;
  margin-top: 9px;
  color: #868c86;
  font-size: 9px;
}

.report-first-evidence .report-first-document-head {
  padding-bottom: 18px;
}

.report-first-evidence-metrics {
  margin-top: 18px;
  display: grid !important;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.report-first-evidence-metrics > button,
.report-first-evidence-metrics > span {
  min-height: 58px;
  padding: 10px;
  display: flex !important;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 1px solid #dde8f4;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f5f8fd 100%);
  color: #71809a;
  font-size: 10px;
  font-weight: 800;
  font-family: inherit;
  text-align: center;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.8);
}

.report-first-evidence-metrics > button {
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.report-first-evidence-metrics > button:hover {
  border-color: #aac3ea;
  transform: translateY(-1px);
}

.report-first-evidence-metrics > button.active {
  border-color: #75a4f3;
  background: #eff5ff;
  box-shadow:
    inset 0 0 0 1px rgba(45, 112, 239, 0.16),
    0 8px 18px rgba(45, 112, 239, 0.08);
}

.report-first-evidence-metrics > button:nth-child(2) strong,
.report-first-evidence-metrics > button:nth-child(3) strong {
  color: #09866a;
}

.report-first-evidence-metrics > button strong,
.report-first-evidence-metrics > span strong {
  margin-bottom: 5px;
  color: #275ee8;
  font-size: 19px;
  line-height: 1;
}

.report-first-evidence-metrics > button span,
.report-first-evidence-metrics > span span {
  color: inherit;
}

.report-first-evidence-list {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.report-first-evidence-row {
  border: 1px solid #dbe5f1;
  border-radius: 15px;
  background: #f8fafc;
  box-shadow: 0 1px 0 rgba(15, 23, 42, 0.02);
  overflow: hidden;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.report-first-evidence-row:hover {
  border-color: #b9cdec;
  box-shadow: 0 10px 24px rgba(42, 88, 145, 0.08);
  transform: translateY(-1px);
}

.report-first-evidence-row[open] {
  background: #f8fafc;
  border-color: #aac5ed;
}

.report-first-evidence-summary {
  position: relative;
  min-height: 74px;
  padding: 12px 44px 12px 14px;
  display: grid !important;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  list-style: none !important;
  cursor: pointer;
  outline: none;
}

.report-first-evidence-summary::marker,
.report-first-evidence-summary::-webkit-details-marker {
  display: none;
  content: "";
}

.report-first-evidence-summary::after {
  content: "⌄";
  position: absolute;
  right: 15px;
  top: 50%;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: #edf4ff;
  color: #5573a5;
  font-size: 13px;
  font-weight: 900;
  transform: translateY(-50%);
  transition: transform 160ms ease, background 160ms ease;
}

.report-first-evidence-row[open] .report-first-evidence-summary::after {
  background: #dfeeff;
  transform: translateY(-50%) rotate(180deg);
}

.report-first-evidence-task {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: #edf4ff;
  color: #315fba;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 11px;
  font-weight: 850;
}

.report-first-evidence-main {
  display: block;
  min-width: 0;
}

.report-first-evidence-title {
  display: block !important;
  overflow: hidden;
  color: #172033 !important;
  font-size: 13px !important;
  font-weight: 850 !important;
  line-height: 1.3;
  text-decoration: none !important;
  text-overflow: ellipsis;
  white-space: nowrap !important;
}

.report-first-evidence-title:hover {
  color: #2456df;
}

.report-first-evidence-main small {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #7c8aa0;
  font-size: 10px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-evidence-meta {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.report-first-evidence-meta span {
  min-height: 22px;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
  border: 1px solid #e2e8f2;
  border-radius: 999px;
  background: #ffffff;
  color: #59677a;
  font-size: 9px;
  font-weight: 800;
}

.report-first-evidence-meta .source-tone-strong {
  border-color: #bee6d8;
  background: #edf9f4;
  color: #13805f;
}

.report-first-evidence-meta .source-tone-weak {
  border-color: #f1d4c0;
  background: #fff8f2;
  color: #b85f25;
}

.report-first-evidence-citation {
  min-height: 28px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: #f3f6fa;
  color: #7b8797;
  font-size: 10px;
  font-weight: 800;
  white-space: nowrap;
}

.report-first-evidence-citation.cited {
  background: #e9f8f2;
  color: #13805f;
}

.report-first-evidence-detail {
  margin: 0 14px 14px 60px;
  padding: 12px 14px;
  border: 1px solid #e7edf5;
  border-radius: 12px;
  background: #f8fafd;
}

.report-first-evidence-detail p {
  margin: 0;
  color: #536072;
  font-size: 11px;
  line-height: 1.7;
}

.report-first-evidence-detail ul {
  margin: 10px 0 0;
  padding-left: 16px;
  color: #657185;
  font-size: 10px;
  line-height: 1.65;
}

.report-first-evidence-empty {
  padding: 28px;
  border: 1px dashed #cdd9e8;
  border-radius: 14px;
  background: #f8fbff;
  color: #75849a;
  font-size: 12px;
  font-weight: 750;
  text-align: center;
}

.report-first-run .report-first-document-head {
  padding-bottom: 18px;
}

.report-first-run-scope {
  min-height: 34px;
  margin-top: 16px;
  padding: 0 11px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  background: #eff6ff;
  color: #2456df;
  font-size: 10.5px;
  font-weight: 850;
}

.report-first-run-scope span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-run-scope button {
  border: none;
  background: transparent;
  color: #3b6ea9;
  font-family: inherit;
  font-size: 10px;
  font-weight: 850;
  white-space: nowrap;
  cursor: pointer;
}

.report-first-run-filters {
  margin-top: 16px;
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
}

.report-first-run-filters button {
  min-height: 30px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid #dfe7f2;
  border-radius: 999px;
  background: #fbfdff;
  color: #68778d;
  font-family: inherit;
  font-size: 10px;
  font-weight: 800;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease;
}

.report-first-run-filters button:hover,
.report-first-run-filters button.active {
  border-color: #8eb0ee;
  background: #edf4ff;
  color: #2456df;
}

.report-first-run-filters strong {
  min-width: 19px;
  height: 19px;
  padding: 0 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #ffffff;
  color: inherit;
  font-size: 9px;
}

.report-first-run-list {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.report-first-run-item {
  padding: 14px 15px;
  border: 1px solid #dfe7f2;
  border-radius: 13px;
  background: #fbfdff;
}

.report-first-run-item.status-failed {
  border-color: #f0c5ca;
  background: #fff7f8;
}

.report-first-run-item header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.report-first-run-item header span {
  color: #6c7e99;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
}

.report-first-run-item header strong {
  overflow: hidden;
  color: #1c2636;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-run-item header em {
  min-height: 22px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: #eef8f4;
  color: #158064;
  font-size: 9px;
  font-style: normal;
  font-weight: 800;
  white-space: nowrap;
}

.report-first-run-item.status-failed header em {
  background: #fff0f1;
  color: #b8404d;
}

.report-first-run-item p {
  margin: 10px 0 0;
  color: #59667a;
  font-size: 11px;
  line-height: 1.65;
  word-break: break-word;
}

.report-first-run-item dl {
  margin: 11px 0 0;
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
}

.report-first-run-item dl div {
  min-height: 24px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #e2e8f2;
  border-radius: 999px;
  background: #ffffff;
}

.report-first-run-item dt,
.report-first-run-item dd {
  margin: 0;
  font-size: 9px;
}

.report-first-run-item dt {
  color: #8b98aa;
  font-weight: 700;
}

.report-first-run-item dd {
  max-width: 150px;
  overflow: hidden;
  color: #4f5e74;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-first-run-item pre {
  max-height: 180px;
  margin: 12px 0 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid #e3e9f2;
  border-radius: 10px;
  background: #f7f9fc;
  color: #3d4758;
  font-size: 10px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.report-first-run-empty {
  margin-top: 18px;
  padding: 28px;
  border: 1px dashed #cdd9e8;
  border-radius: 14px;
  background: #f8fbff;
  color: #75849a;
  font-size: 12px;
  font-weight: 750;
  text-align: center;
}

.report-first-run-log-list {
  margin: 18px 0 0;
  padding: 0;
  list-style: none;
}

.report-first-run-log-list li {
  min-height: 38px;
  padding: 10px 0;
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 10px;
  border-bottom: 1px solid #eef2f7;
}

.report-first-run-log-list span {
  color: #70819c;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
}

.report-first-run-log-list p {
  margin: 0;
  color: #4c586b;
  font-size: 12px;
  line-height: 1.65;
}

.report-first-error {
  margin-top: 20px;
  padding: 12px 14px;
  border: 1px solid #efc5c7;
  border-radius: 10px;
  background: #fff3f3;
  color: #a23c42;
  font-size: 11px;
}

.report-first-evaluator {
  padding: 24px 18px;
  overflow-y: auto;
}

.report-first-evaluator h2 {
  margin: 0;
  font-size: 17px;
}

.report-first-score {
  margin-top: 17px;
  padding: 18px;
  border-radius: 14px;
  background: #101c35;
  color: #ffffff;
}

.report-first-evaluator > h3 {
  color: #424b45;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.report-first-score-label {
  display: block;
  color: #9fb0a8;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.report-first-score-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 10px;
}

.report-first-score-row strong {
  font-size: 42px;
  line-height: 1;
}

.report-first-score em {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  color: #d1b96c;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  white-space: nowrap;
}

.report-first-score em::before {
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
}

.report-first-score em.passed {
  color: #75d5a9;
}

.report-first-evaluator > h3 {
  margin: 26px 0 12px;
  color: #424b45;
}

.report-first-metrics {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.report-first-metrics > div {
  min-height: 46px;
  padding: 0 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid #e5e4df;
  border-radius: 11px;
  background: #f8fafc;
}

.report-first-metrics span {
  color: #424b45;
  font-size: 11px;
  line-height: 1.15;
}

.report-first-metrics strong {
  color: #00866a;
  font-size: 12px;
}

.report-first-metrics .tone-neutral strong {
  color: #2468f2;
}

.report-first-metrics .tone-warn strong {
  color: #c45b00;
}

.report-first-metrics .tone-danger strong {
  color: #c84e57;
}

@media (max-width: 1180px) {
  .report-first-grid {
    grid-template-columns: 230px minmax(0, 1fr);
  }

  .report-first-evaluator {
    grid-column: 1 / -1;
  }

  .report-first-metrics {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 780px) {
  .report-first-shell {
    padding: 12px;
  }

  .report-first-topbar {
    padding: 14px 16px;
    grid-template-columns: 1fr auto;
  }

  .report-first-topbar-tabs {
    grid-column: 1 / -1;
    order: 3;
    overflow-x: auto;
  }

  .report-first-topbar-actions span:first-child {
    display: none;
  }

  .report-first-grid {
    padding: 12px;
    grid-template-columns: 1fr;
  }

  .report-first-task-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .report-first-document {
    padding: 26px 22px;
  }

  .report-first-document-head h2 {
    font-size: 23px;
  }

  .report-first-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
