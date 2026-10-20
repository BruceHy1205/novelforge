<script setup lang="ts">
import {
  Collection,
  DataBoard,
  Delete,
  Document,
  Notebook,
  Reading,
  Setting,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api'
import { loadGenres, refreshStatus, startPolling, store } from './store'

const route = useRoute()
const toggling = ref(false)

const counts = computed(() => store.status?.counts)
const running = computed(() => store.status?.running ?? false)

onMounted(() => {
  startPolling()
  void loadGenres()
})

async function toggle(): Promise<void> {
  const status = store.status
  if (!status) return
  if (!status.running && !status.dry_run && !status.model_key.set) {
    ElMessage.error(`没有设置环境变量 ${status.model_key.env}，无法调用模型。可以先在设置里打开演练模式。`)
    return
  }
  if (!status.running && !status.dry_run) {
    try {
      await ElMessageBox.confirm(
        '开始后会按题材和数量上限持续调用模型生成大纲和正文，会产生费用。确定开始？',
        '开始批量生产',
        { type: 'warning', confirmButtonText: '开始', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  toggling.value = true
  try {
    await api.control(status.running ? 'pause' : 'start')
    await refreshStatus()
  } finally {
    toggling.value = false
  }
}
</script>

<template>
  <el-container class="shell">
    <el-aside width="228px" class="aside">
      <div class="brand">
        <i class="seal">坊</i>
        <div>
          <strong>NovelForge</strong>
          <span>批量生产台</span>
        </div>
      </div>
      <el-menu :default-active="route.path" router class="menu">
        <el-menu-item index="/">
          <el-icon><DataBoard /></el-icon>总览
        </el-menu-item>
        <el-menu-item index="/topics">
          <el-icon><Collection /></el-icon>题材批次
        </el-menu-item>
        <el-menu-item index="/review/outline">
          <el-icon><Document /></el-icon>大纲审核
          <el-badge v-if="counts?.outline_review" :value="counts.outline_review" class="badge" />
        </el-menu-item>
        <el-menu-item index="/review/trial">
          <el-icon><Reading /></el-icon>试读审核
          <el-badge v-if="counts?.trial_review" :value="counts.trial_review" class="badge" />
        </el-menu-item>
        <el-menu-item index="/library">
          <el-icon><Notebook /></el-icon>书库
        </el-menu-item>
        <el-menu-item index="/trash">
          <el-icon><Delete /></el-icon>回收站
          <el-badge v-if="counts?.trashed" :value="counts.trashed" type="info" class="badge" />
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>设置
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container class="stage">
      <el-header class="header">
        <div class="toolbar">
          <span class="pulse" :class="{ on: running }" />
          <el-tag :type="running ? 'success' : 'info'" effect="dark" round>
            {{ running ? '生产中' : '已暂停' }}
          </el-tag>
          <el-tag v-if="store.status?.dry_run" type="warning" effect="plain" round>演练</el-tag>
          <span v-if="store.status" class="status-line">
            未完成 <b>{{ store.status.active }}</b> / {{ store.status.settings.max_total }}
            <span class="dot">·</span>
            在写 <b>{{ store.status.busy.length }}</b> / {{ store.status.settings.concurrency }}
          </span>
          <span v-if="store.error" class="error">后端：{{ store.error }}</span>
        </div>
        <el-button
          :type="running ? 'warning' : 'primary'"
          :loading="toggling"
          :disabled="!store.status"
          @click="toggle"
        >
          {{ running ? '暂停生产' : '开始生产' }}
        </el-button>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.shell {
  height: 100%;
  padding: 14px;
  gap: 14px;
  box-sizing: border-box;
  background: transparent;
}
.aside {
  border-radius: 24px;
  background: linear-gradient(180deg, #2c241e 0%, #171310 100%);
  overflow: hidden;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 18px 14px;
  color: #f6efe4;
}
.seal {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-style: normal;
  font-family: Fraunces, 'Songti SC', Palatino, serif;
  font-size: 20px;
  color: #fff8f2;
  background: #c4513a;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
}
.brand strong {
  display: block;
  font-family: Fraunces, Palatino, serif;
  font-weight: 560;
  font-size: 18px;
  letter-spacing: 0.01em;
}
.brand span {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: rgba(246, 239, 228, 0.55);
}
.menu {
  border-right: none;
  background: transparent;
  padding: 6px 10px 16px;
}
.menu :deep(.el-menu-item) {
  height: 42px;
  margin: 2px 0;
  border-radius: 12px;
  color: rgba(246, 239, 228, 0.72);
}
.menu :deep(.el-menu-item:hover) {
  background: rgba(255, 248, 236, 0.06);
  color: #fff8f0;
}
.menu :deep(.el-menu-item.is-active) {
  background: #c4513a;
  color: #fff8f2;
}
.badge {
  margin-left: auto;
  display: inline-flex;
}
.header {
  height: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 2px;
  padding: 10px 12px 10px 16px;
  background: rgba(255, 253, 248, 0.82);
  border: 1px solid rgba(36, 28, 22, 0.06);
  border-radius: 18px;
  box-shadow: 0 10px 28px rgba(48, 32, 16, 0.05);
  backdrop-filter: blur(10px);
}
.status-line {
  color: #5c534a;
  font-size: 13px;
}
.status-line b {
  color: #241c16;
  font-variant-numeric: tabular-nums;
}
.dot {
  margin: 0 6px;
  color: #c4b8a8;
}
.pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #b7aea4;
}
.pulse.on {
  background: #3d6b58;
  box-shadow: 0 0 0 4px rgba(61, 107, 88, 0.18);
}
.error {
  color: #b42318;
  font-size: 13px;
}
.stage {
  min-width: 0;
  min-height: 0;
}
:deep(.el-main) {
  padding: 16px 4px 28px;
  overflow: auto;
}
</style>
