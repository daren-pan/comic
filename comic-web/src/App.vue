<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { backendAlive, getCategories, isLoggedIn, currentUser, clearAuth } from './api'

const route = useRoute()
const router = useRouter()

const categories = ref<{ name: string; count: number }[]>([])
const keyword = ref('')
const showMenu = ref(false)
const backend = ref<boolean | null>(null)
const logged = ref(isLoggedIn())
const user = ref(currentUser())

onMounted(async () => {
  categories.value = await getCategories()
  backend.value = await backendAlive()
})

function onSearch() {
  const k = keyword.value.trim()
  router.push({ path: '/search', query: k ? { keyword: k } : {} })
  keyword.value = ''
  showMenu.value = false
}

function onLogout() {
  clearAuth()
  refreshAuth()
  router.push('/')
}

// 登录/退出后刷新导航登录态：路由切换时重新读取（注册/登录在子组件发生，App 不会重建）
function refreshAuth() {
  logged.value = isLoggedIn()
  user.value = currentUser()
}

// 详情页路由切换时刷新导航高亮
watch(() => route.path, () => {
  showMenu.value = false
  refreshAuth()
})
</script>

<template>
  <header class="nav">
    <div class="container nav-inner">
      <RouterLink to="/" class="logo">
        <span class="logo-mark">漫</span>
        <span class="logo-text">漫阅<em>COMIC</em></span>
      </RouterLink>

      <nav class="nav-links">
        <RouterLink to="/" :class="{ on: route.path === '/' }">首页</RouterLink>
        <RouterLink
          v-for="c in categories.filter((x) => x.name !== '全部').slice(0, 5)"
          :key="c.name"
          :to="{ path: '/search', query: { category: c.name } }"
          :class="{ on: route.path === '/search' && route.query.category === c.name }"
        >{{ c.name }}</RouterLink>
        <RouterLink to="/me" :class="{ on: route.path === '/me' }">我的</RouterLink>
      </nav>

      <div class="nav-right">
        <form class="search-box" @submit.prevent="onSearch">
          <input v-model="keyword" type="text" placeholder="搜索漫画 / 作者 / 标签" />
          <button type="submit" aria-label="搜索">🔍</button>
        </form>
        <template v-if="logged">
          <button class="user-chip" @click="router.push('/me')" title="我的书架">
            <span class="avatar">{{ (user?.nickname || '我').slice(0, 1) }}</span>
            {{ user?.nickname || user?.username }}
          </button>
          <button class="logout" @click="onLogout">退出</button>
        </template>
        <RouterLink v-else to="/login" class="login-link">登录</RouterLink>
        <button class="menu-btn" @click="showMenu = !showMenu" aria-label="菜单">☰</button>
      </div>
    </div>

    <!-- 移动端菜单 -->
    <div v-if="showMenu" class="mobile-menu">
      <RouterLink to="/" @click="showMenu = false">首页</RouterLink>
      <RouterLink v-for="c in categories" :key="c.name" :to="{ path: '/search', query: { category: c.name } }" @click="showMenu = false">
        {{ c.name }}<span>{{ c.count }}</span>
      </RouterLink>
      <RouterLink to="/me" @click="showMenu = false">我的收藏与历史</RouterLink>
      <RouterLink v-if="!logged" to="/login" @click="showMenu = false">登录</RouterLink>
      <a v-else href="#" @click.prevent="onLogout(); showMenu = false">退出登录</a>
    </div>
  </header>

  <main class="container page">
    <RouterView />
  </main>

  <footer class="footer">
    <div class="container">
      <p>漫阅 Comic — 漫画聚合阅读平台
        <span v-if="backend === true" class="src-tag real">● 已连接采集服务（真实数据）</span>
        <span v-else class="src-tag">● 演示模式（本地 mock 数据）</span>
      </p>
      <p class="tip">仅收录已授权 / 开放版权 / 公共领域内容 · 尊重版权，支持正版</p>
    </div>
  </footer>
</template>

<style scoped>
.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: #fff;
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.nav-inner {
  display: flex;
  align-items: center;
  gap: 24px;
  height: 60px;
}
.logo { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.logo-mark {
  width: 34px; height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-weight: 800;
  font-size: 19px;
  display: flex; align-items: center; justify-content: center;
}
.logo-text { font-weight: 800; font-size: 19px; }
.logo-text em { font-style: normal; font-size: 11px; color: var(--primary); margin-left: 4px; letter-spacing: 1px; }

.nav-links { display: flex; gap: 4px; flex: 1; }
.nav-links a {
  padding: 6px 12px;
  border-radius: 8px;
  font-weight: 600;
  color: var(--text-2);
  transition: all 0.15s;
}
.nav-links a:hover { color: var(--primary); background: var(--primary-soft); }
.nav-links a.on { color: var(--primary); background: var(--primary-soft); }

.nav-right { display: flex; align-items: center; gap: 10px; }
.search-box { display: flex; align-items: center; background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 0 4px 0 14px; height: 36px; width: 230px; transition: border 0.15s; }
.search-box:focus-within { border-color: var(--primary); background: #fff; }
.search-box input { border: none; outline: none; background: transparent; flex: 1; font-size: 13px; color: var(--text); }
.search-box button { border: none; background: var(--primary); color: #fff; width: 28px; height: 28px; border-radius: 999px; cursor: pointer; font-size: 12px; }

.menu-btn { display: none; border: none; background: none; font-size: 20px; cursor: pointer; color: var(--text); }

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 999px;
  padding: 4px 12px 4px 4px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  color: var(--text);
  max-width: 140px;
}
.user-chip:hover { border-color: var(--primary); color: var(--primary); }
.avatar {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-size: 13px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.user-chip span:last-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.logout {
  border: none;
  background: none;
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
  padding: 4px 6px;
}
.logout:hover { color: #e23; }
.login-link {
  padding: 6px 16px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
.login-link:hover { background: var(--primary-dark); }

.mobile-menu {
  display: none;
  padding: 8px 16px 14px;
  border-top: 1px solid var(--border);
  background: #fff;
  flex-direction: column;
}
.mobile-menu a { padding: 10px 8px; border-radius: 8px; font-weight: 600; color: var(--text-2); display: flex; justify-content: space-between; }
.mobile-menu a.on { color: var(--primary); background: var(--primary-soft); }
.mobile-menu span { color: #bbb; font-size: 13px; }

.footer {
  border-top: 1px solid var(--border);
  background: #fff;
  padding: 22px 0 30px;
  text-align: center;
  color: var(--text-2);
  font-size: 13px;
}
.footer .tip { margin-top: 4px; font-size: 12px; color: #b5aca2; }
.src-tag { margin-left: 8px; font-size: 12px; color: var(--text-2); background: var(--bg); border: 1px solid var(--border); border-radius: 999px; padding: 2px 10px; }
.src-tag.real { color: #0a7d3a; background: #e9f7ee; border-color: #b7e5c8; }

@media (max-width: 860px) {
  .nav-links, .search-box { display: none; }
  .menu-btn { display: block; }
  .mobile-menu { display: flex; }
}
</style>
