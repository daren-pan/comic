import { createRouter, createWebHashHistory } from 'vue-router'

export const router = createRouter({
  // hash 模式：构建产物可离线双击打开，无需服务器配置
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
    { path: '/search', name: 'search', component: () => import('./views/SearchView.vue') },
    { path: '/latest', name: 'latest', component: () => import('./views/LatestView.vue') },
    { path: '/rank', name: 'rank', component: () => import('./views/RankingView.vue') },
    { path: '/comic/:id', name: 'detail', component: () => import('./views/ComicDetailView.vue') },
    { path: '/reader/:comicId/:chapterId', name: 'reader', component: () => import('./views/ReaderView.vue') },
    { path: '/me', name: 'me', component: () => import('./views/MeView.vue') },
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    { path: '/admin', name: 'admin', component: () => import('./views/AdminView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})
