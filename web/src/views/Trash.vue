<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { ref, watch } from 'vue'
import { api, type Action, type Book } from '../api'
import BookDetail from '../components/BookDetail.vue'
import { formatTime, stageLabel } from '../stages'
import { genreName, refreshStatus, store } from '../store'

const books = ref<Book[]>([])
const selected = ref<Book[]>([])
const openId = ref<number | null>(null)

async function load(): Promise<void> {
  books.value = await api.books(['trashed'])
}

watch(() => store.revision, () => void load(), { immediate: true })

function daysLeft(book: Book): number {
  const days = store.status?.settings.trash_days ?? 30
  if (!book.trashed_at) return days
  const expires = new Date(book.trashed_at).getTime() + days * 86400000
  return Math.max(0, Math.ceil((expires - Date.now()) / 86400000))
}

async function batch(action: Action): Promise<void> {
  const ids = selected.value.map((book) => book.id)
  if (action === 'delete') {
    try {
      await ElMessageBox.confirm(`永久删除 ${ids.length} 本？文件会一起删掉，无法恢复。`, '永久删除', { type: 'warning' })
    } catch {
      return
    }
  }
  const result = await api.batch(ids, action)
  const failed = Object.values(result.errors)
  if (failed.length) ElMessage.warning(failed.join('；'))
  else ElMessage.success(`完成 ${result.done.length} 本`)
  await refreshStatus()
}

async function empty(): Promise<void> {
  try {
    await ElMessageBox.confirm('清空回收站里的全部书？无法恢复。', '清空回收站', { type: 'warning' })
  } catch {
    return
  }
  const result = await api.emptyTrash()
  ElMessage.success(`删除 ${result.removed} 本`)
  await refreshStatus()
}
</script>

<template>
  <div>
    <div class="page-title">
      <h2>回收站</h2>
      <el-button type="danger" :disabled="!books.length" @click="empty">清空回收站</el-button>
    </div>
    <p class="muted">
      被毙掉或手动移入的书放在这里，{{ store.status?.settings.trash_days ?? 30 }} 天后自动永久删除。恢复后回到进回收站之前的阶段。
    </p>
    <div class="toolbar gap">
      <el-button type="primary" :disabled="!selected.length" @click="batch('restore')">恢复选中</el-button>
      <el-button type="danger" plain :disabled="!selected.length" @click="batch('delete')">永久删除选中</el-button>
    </div>
    <el-table :data="books" border row-key="id" @selection-change="(rows: Book[]) => (selected = rows)" @row-click="(row: Book) => (openId = row.id)">
      <el-table-column type="selection" width="44" />
      <el-table-column label="书名" min-width="200">
        <template #default="{ row }">
          <b>{{ row.title || '（大纲未完成）' }}</b>
          <div class="muted">{{ row.slug }}</div>
        </template>
      </el-table-column>
      <el-table-column label="规则集" width="90">
        <template #default="{ row }">{{ genreName(row.genre) }}</template>
      </el-table-column>
      <el-table-column label="毙掉时阶段" width="120">
        <template #default="{ row }">{{ stageLabel(row.prev_stage) }}</template>
      </el-table-column>
      <el-table-column label="原因" min-width="180">
        <template #default="{ row }"><span class="muted">{{ row.note }}</span></template>
      </el-table-column>
      <el-table-column label="进入时间" width="170">
        <template #default="{ row }">{{ formatTime(row.trashed_at) }}</template>
      </el-table-column>
      <el-table-column label="剩余" width="90">
        <template #default="{ row }">
          <el-tag :type="daysLeft(row) <= 3 ? 'danger' : 'info'">{{ daysLeft(row) }} 天</el-tag>
        </template>
      </el-table-column>
      <template #empty><el-empty description="回收站是空的" /></template>
    </el-table>
    <BookDetail :book-id="openId" @close="openId = null" @changed="refreshStatus" />
  </div>
</template>

<style scoped>
.gap {
  margin-bottom: 12px;
}
</style>
