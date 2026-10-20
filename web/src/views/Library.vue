<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Action, type Book, type Stage } from '../api'
import BookDetail from '../components/BookDetail.vue'
import { STAGE_LABEL, STAGE_TAG, formatTime } from '../stages'
import { genreName, refreshStatus, store } from '../store'

const route = useRoute()
const router = useRouter()
const books = ref<Book[]>([])
const selected = ref<Book[]>([])
const openId = ref<number | null>(null)
const keyword = ref('')

const stageOptions = (Object.keys(STAGE_LABEL) as Stage[]).filter((stage) => stage !== 'trashed')
const stage = computed<string>({
  get: () => String(route.query.stage ?? ''),
  set: (value) => void router.replace({ query: value ? { stage: value } : {} }),
})

const shown = computed(() => {
  const word = keyword.value.trim()
  if (!word) return books.value
  return books.value.filter((book) => `${book.title}${book.slug}${book.idea}`.includes(word))
})

async function load(): Promise<void> {
  const stages = stage.value ? [stage.value as Stage] : stageOptions
  books.value = await api.books(stages)
}

watch([() => store.revision, stage], () => void load(), { immediate: true })

async function batch(action: Action): Promise<void> {
  const ids = selected.value.map((book) => book.id)
  const result = await api.batch(ids, action)
  const failed = Object.values(result.errors)
  if (failed.length) ElMessage.warning(failed.join('；'))
  else ElMessage.success(`完成 ${result.done.length} 本`)
  await refreshStatus()
}

function target(book: Book): string {
  return `${book.written} / ${book.chapters}`
}
</script>

<template>
  <div>
    <div class="page-title">
      <h2>书库</h2>
      <div class="toolbar">
        <el-input v-model="keyword" placeholder="搜书名或创意" clearable style="width: 200px" />
        <el-select v-model="stage" placeholder="全部阶段" clearable style="width: 150px">
          <el-option v-for="item in stageOptions" :key="item" :label="STAGE_LABEL[item]" :value="item" />
        </el-select>
      </div>
    </div>

    <div class="toolbar gap">
      <el-button :disabled="!selected.length" @click="batch('retry')">重试失败的</el-button>
      <el-button type="danger" plain :disabled="!selected.length" @click="batch('trash')">移入回收站</el-button>
      <span class="muted">共 {{ shown.length }} 本</span>
    </div>

    <el-table :data="shown" border row-key="id" @selection-change="(rows: Book[]) => (selected = rows)" @row-click="(row: Book) => (openId = row.id)">
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
      <el-table-column label="阶段" width="130">
        <template #default="{ row }">
          <el-tag :type="STAGE_TAG[row.stage as Stage]">{{ STAGE_LABEL[row.stage as Stage] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="已写 / 章数" width="110">
        <template #default="{ row }">{{ target(row) }}</template>
      </el-table-column>
      <el-table-column label="备注" min-width="200">
        <template #default="{ row }">
          <span v-if="row.error" class="error">{{ row.error }}</span>
          <span v-else class="muted">{{ row.note }}</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <template #empty><el-empty description="没有书" /></template>
    </el-table>

    <BookDetail :book-id="openId" @close="openId = null" @changed="refreshStatus" />
  </div>
</template>

<style scoped>
.gap {
  margin-bottom: 12px;
}
.error {
  color: #f56c6c;
  font-size: 13px;
}
</style>
