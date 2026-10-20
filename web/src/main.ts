import '@fontsource/fraunces/500.css'
import '@fontsource/fraunces/600.css'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import Dashboard from './views/Dashboard.vue'
import Library from './views/Library.vue'
import Review from './views/Review.vue'
import SettingsView from './views/Settings.vue'
import Topics from './views/Topics.vue'
import Trash from './views/Trash.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Dashboard },
    { path: '/topics', component: Topics },
    { path: '/review/outline', component: Review, props: { kind: 'outline' } },
    { path: '/review/trial', component: Review, props: { kind: 'trial' } },
    { path: '/library', component: Library },
    { path: '/trash', component: Trash },
    { path: '/settings', component: SettingsView },
  ],
})

createApp(App).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
