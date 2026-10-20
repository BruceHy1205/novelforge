<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Book, type EventItem, type Settings } from '../api'
import BookDetail from '../components/BookDetail.vue'
import { PIPELINE, STAGE_LABEL, formatTime } from '../stages'
import { genreName, refreshStatus, store } from '../store'

const router = useRouter()
const busyBooks = ref<Book[]>([])
const events = ref<EventItem[]>([])
const topicCount = ref<number | null>(null)
const openId = ref<number | null>(null)

const status = computed(() => store.status)

const meters = computed(() => {
  const s = status.value
  if (!s) return []
  return [
    {
      title: '总体未完成',
      hint: '没写完、没进回收站的书。低于上限才从题材里补新书',
      value: s.active,
      max: s.settings.max_total,
    },
    {
      title: '大纲积压',
      hint: '大纲生成中 + 大纲待审 + 待写试读。满了就不再开新大纲',
      value: s.outline_backlog,
      max: s.settings.max_outline_backlog,
    },
    {
      title: '试读积压',
      hint: '试读生成中 + 试读待审 + 待续写全书。满了就不再开新试读',
      value: s.trial_backlog,
      max: s.settings.max_trial_backlog,
    },
  ]
})

function percent(value: number, max: number): number {
  return max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
}

function color(value: number, max: number): string {
  const p = percent(value, max)
  return p >= 100 ? '#c4513a' : p >= 80 ? '#c4893a' : '#3d6b58'
}

async function load(): Promise<void> {
  const [books, recent, topics] = await Promise.all([
    api.books(['outlining', 'trial_writing', 'full_writing']),
    api.events(30),
    api.topics(),
  ])
  busyBooks.value = books
  events.value = recent
  topicCount.value = topics.filter((topic) => topic.enabled).length
}

watch(() => store.revision, () => void load(), { immediate: true })

async function toggle(key: keyof Settings, value: boolean | number): Promise<void> {
  await api.saveSettings({ [key]: value })
  await refreshStatus()
}

function target(book: Book): number {
  const trial = status.value?.settings.trial_chapters ?? 5
  return book.stage === 'trial_writing' ? Math.min(trial, book.chapters) : book.chapters
}
</script>

<template>
  <div v-if="status">
    <div class="page-title">
      <div>
        <h2>总览</h2>
        <p class="lede">这一批书写到哪了。审核开着的阶段会停下来等你。</p>
      </div>
    </div>

    <el-alert
      v-if="topicCount === 0"
      type="info"
      show-icon
      :closable="false"
      title="还没有启用的题材批次"
      description="先去「题材批次」写好题材、核心内容和要生产的本数，再点右上角「开始生产」。"
      class="block"
    >
      <el-button size="small" type="primary" @click="router.push('/topics')">去建题材</el-button>
    </el-alert>

    <el-row :gutter="16" class="block">
      <el-col v-for="meter in meters" :key="meter.title" :span="8">
        <el-card shadow="never">
          <div class="meter-head">
            <span>{{ meter.title }}</span>
            <b>{{ meter.value }} / {{ meter.max }}</b>
          </div>
          <el-progress
            :percentage="percent(meter.value, meter.max)"
            :color="color(meter.value, meter.max)"
            :stroke-width="10"
            :show-text="false"
          />
          <div class="muted meter-hint">{{ meter.hint }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span>流水线</span>
          <div class="toolbar">
            <el-switch
              :model-value="status.settings.outline_review"
              active-text="大纲人工审核"
              @change="(v: string | number | boolean) => toggle('outline_review', Boolean(v))"
            />
            <el-switch
              :model-value="status.settings.trial_review"
              active-text="试读人工审核"
              @change="(v: string | number | boolean) => toggle('trial_review', Boolean(v))"
            />
            <span class="muted">试读章数</span>
            <el-input-number
              :model-value="status.settings.trial_chapters"
              :min="1"
              :max="50"
              size="small"
              @change="(v: number | undefined) => v && toggle('trial_chapters', v)"
            />
          </div>
        </div>
      </template>
      <div class="pipeline">
        <div v-for="group in PIPELINE" :key="group.title" class="group">
          <div class="group-title">{{ group.title }}</div>
          <div class="group-cells">
            <div
              v-for="stage in group.stages"
              :key="stage"
              class="cell"
              :class="stage"
              @click="router.push({ path: stage === 'trashed' ? '/trash' : '/library', query: { stage } })"
            >
              <div class="cell-num">{{ status.counts[stage] }}</div>
              <div class="cell-label">{{ STAGE_LABEL[stage] }}</div>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>正在生成</template>
          <el-empty v-if="!busyBooks.length" description="没有正在跑的任务" :image-size="60" />
          <div v-for="book in busyBooks" :key="book.id" class="busy" @click="openId = book.id">
            <div class="busy-head">
              <span>
                <b>{{ book.title || book.slug }}</b>
                <span class="muted"> · {{ genreName(book.genre) }} · {{ STAGE_LABEL[book.stage] }}</span>
              </span>
              <span class="muted">{{ book.written }} / {{ target(book) }} 章</span>
            </div>
            <el-progress
              v-if="book.stage !== 'outlining'"
              :percentage="percent(book.written, target(book))"
              :stroke-width="6"
            />
            <el-progress v-else :percentage="100" :indeterminate="true" :stroke-width="6" :show-text="false" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>最近动态</template>
          <el-scrollbar max-height="360px">
            <el-timeline>
              <el-timeline-item
                v-for="event in events"
                :key="event.id"
                :timestamp="formatTime(event.at)"
                :type="event.level === 'error' ? 'danger' : 'primary'"
                size="normal"
              >
                <span v-if="event.book_id" class="link" @click="openId = event.book_id">#{{ event.book_id }}</span>
                {{ event.message }}
              </el-timeline-item>
            </el-timeline>
          </el-scrollbar>
        </el-card>
      </el-col>
    </el-row>

    <BookDetail :book-id="openId" @close="openId = null" @changed="refreshStatus" />
  </div>
</template>

<style scoped>
.lede {
  margin: 6px 0 0;
}
.block {
  margin-bottom: 16px;
}
.meter-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}
.meter-head span {
  color: #5c534a;
}
.meter-head b {
  font-family: Fraunces, Palatino, serif;
  font-size: 26px;
  font-weight: 560;
  font-variant-numeric: tabular-nums;
}
.meter-hint {
  margin-top: 10px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.pipeline {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}
.group {
  flex: 1;
  min-width: 220px;
}
.group-title {
  font-family: Fraunces, 'Songti SC', Palatino, serif;
  font-size: 15px;
  color: #241c16;
  margin-bottom: 8px;
}
.group-cells {
  display: flex;
  gap: 8px;
}
.cell {
  flex: 1;
  border-radius: 16px;
  padding: 14px 8px 12px;
  text-align: center;
  background: #f6f1e8;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.cell:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 20px rgba(48, 32, 16, 0.08);
}
.cell.outlining,
.cell.trial_writing,
.cell.full_writing {
  background: #e7f0ec;
}
.cell.outline_review,
.cell.trial_review {
  background: #f8ead4;
}
.cell.done {
  background: #e5f2ea;
}
.cell.failed {
  background: #f8e4e0;
}
.cell.trashed {
  background: #eeeae4;
}
.cell-num {
  font-family: Fraunces, Palatino, serif;
  font-size: 26px;
  font-weight: 560;
  line-height: 1;
}
.cell-label {
  margin-top: 6px;
  font-size: 12px;
  color: #5c534a;
}
.busy {
  padding: 10px 0;
  border-bottom: 1px solid rgba(36, 28, 22, 0.06);
  cursor: pointer;
}
.busy-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}
.link {
  color: #c4513a;
  cursor: pointer;
  font-weight: 560;
}
</style>
