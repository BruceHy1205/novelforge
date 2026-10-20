<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { api, type Action, type Book } from '../api'
import BookDetail from '../components/BookDetail.vue'
import { formatTime } from '../stages'
import { genreName, refreshStatus, store } from '../store'

const props = defineProps<{ kind: 'outline' | 'trial' }>()

const books = ref<Book[]>([])
const selected = ref<Book[]>([])
const openId = ref<number | null>(null)
const queueOn = ref(false)
const cursor = ref('')

function stamp(book: Book): string {
  return `${book.updated_at}\u0000${String(book.id).padStart(8, '0')}`
}

const ordered = computed(() => [...books.value].sort((a, b) => stamp(a).localeCompare(stamp(b))))

const queueLabel = computed(() => {
  if (!queueOn.value || !cursor.value) return ''
  const later = ordered.value.filter((book) => stamp(book) > cursor.value).length
  return later
    ? `通过、毙掉或退回后自动打开下一本。后面还有 ${later} 本。`
    : '通过、毙掉或退回后这一批就审完了。这是队列里的最后一本。'
})

const stage = computed(() => (props.kind === 'outline' ? 'outline_review' : 'trial_review'))
const title = computed(() => (props.kind === 'outline' ? '大纲审核' : '试读审核'))
const enabled = computed(() =>
  props.kind === 'outline' ? store.status?.settings.outline_review : store.status?.settings.trial_review,
)
const next = computed(() =>
  props.kind === 'outline'
    ? `通过后立即排进试读队列（先于新大纲），写满 ${store.status?.settings.trial_chapters ?? 5} 章试读`
    : '通过后立即排进全书续写队列，优先于其他任务',
)

async function load(): Promise<void> {
  books.value = await api.books([stage.value])
}

watch([() => store.revision, () => props.kind], () => void load(), { immediate: true })

watch(
  () => props.kind,
  () => {
    queueOn.value = false
    openId.value = null
    cursor.value = ''
  },
)

function openAt(book: Book): void {
  queueOn.value = true
  cursor.value = stamp(book)
  openId.value = book.id
}

function startQueue(): void {
  const first = ordered.value[0]
  if (first) openAt(first)
}

function stopQueue(): void {
  queueOn.value = false
  openId.value = null
  cursor.value = ''
}

async function onReviewed(): Promise<void> {
  const key = cursor.value
  await load()
  const next = ordered.value.find((book) => stamp(book) > key)
  if (!next) {
    stopQueue()
    ElMessage.success('按顺序审完了')
    return
  }
  openAt(next)
}

async function setEnabled(value: boolean): Promise<void> {
  const key = props.kind === 'outline' ? 'outline_review' : 'trial_review'
  await api.saveSettings({ [key]: value })
  await refreshStatus()
}

async function batch(action: Action): Promise<void> {
  const ids = selected.value.map((book) => book.id)
  if (!ids.length) return
  let note = ''
  if (action === 'reject') {
    try {
      note = (await ElMessageBox.prompt(`毙掉选中的 ${ids.length} 本，进入回收站。原因（可不填）：`, '批量毙掉')).value ?? ''
    } catch {
      return
    }
  }
  const result = await api.batch(ids, action, note)
  const failed = Object.values(result.errors)
  if (failed.length) ElMessage.warning(failed.join('；'))
  else ElMessage.success(`${action === 'approve' ? '通过' : '毙掉'} ${result.done.length} 本`)
  await refreshStatus()
}
</script>

<template>
  <div>
    <div class="page-title">
      <h2>{{ title }}</h2>
      <el-switch
        :model-value="enabled"
        :active-text="`${title}已开启`"
        :inactive-text="'关闭（自动放行）'"
        @change="(v: string | number | boolean) => setEnabled(Boolean(v))"
      />
    </div>
    <el-alert
      v-if="!enabled"
      type="info"
      :closable="false"
      show-icon
      class="gap"
      :title="`${title}已关闭：新${kind === 'outline' ? '大纲' : '试读'}完成后直接进入下一阶段。下面列出的是关闭前就在等审核的书。`"
    />
    <p class="muted">
      {{ next }}。列表按完成时间从早到晚排，先审等得最久的。「按顺序审核」从第一本开始，审完自动打开下一本。毙掉的书进入回收站，{{ store.status?.settings.trash_days ?? 30 }} 天后自动删除。
    </p>

    <div class="toolbar gap">
      <el-button type="primary" :disabled="!ordered.length" @click="startQueue">
        按顺序审核（{{ ordered.length }}）
      </el-button>
      <el-button type="success" plain :disabled="!selected.length" @click="batch('approve')">
        通过选中（{{ selected.length }}）
      </el-button>
      <el-button type="danger" plain :disabled="!selected.length" @click="batch('reject')">毙掉选中</el-button>
    </div>

    <el-table :data="ordered" border row-key="id" @selection-change="(rows: Book[]) => (selected = rows)" @row-click="(row: Book) => openAt(row)">
      <el-table-column type="selection" width="44" />
      <el-table-column label="#" width="52">
        <template #default="{ $index }">{{ $index + 1 }}</template>
      </el-table-column>
      <el-table-column label="书名" min-width="180">
        <template #default="{ row }">
          <b>{{ row.title || row.slug }}</b>
          <div class="muted">{{ row.slug }}</div>
        </template>
      </el-table-column>
      <el-table-column label="规则集" width="90">
        <template #default="{ row }">{{ genreName(row.genre) }}</template>
      </el-table-column>
      <el-table-column label="创意" min-width="240">
        <template #default="{ row }"><div class="clip">{{ row.idea }}</div></template>
      </el-table-column>
      <el-table-column label="章节" width="110">
        <template #default="{ row }">{{ kind === 'trial' ? `${row.written} / ${row.chapters}` : `${row.chapters} 章` }}</template>
      </el-table-column>
      <el-table-column label="完成时间" width="170">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="" width="90">
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="openAt(row)">{{ kind === 'outline' ? '看大纲' : '试读' }}</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="没有等待审核的书" /></template>
    </el-table>

    <BookDetail :book-id="openId" :queue-label="queueLabel" @close="stopQueue" @changed="refreshStatus" @reviewed="onReviewed" />
  </div>
</template>

<style scoped>
.gap {
  margin-bottom: 12px;
}
.clip {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
