// ESLint 扁平配置（ESLint 9，ESM）—— 对应 comic-front/README.md「开发约定」。
//
// ## 为什么要有它
//
// 本项目有三条**写法约定**，此前只写在 README 里、靠人肉 review 执行：
//   ① 模板只用 uni 组件（与 uni 的组件体系/样式归一保持一致）
//   ② CSS 只写类选择器
//   ③ 自定义组件不用 v-model（统一显式写法）
//
// 这份配置把「能被自动检查的部分」变成机器门禁：
//   ① 部分可查（`vue/no-restricted-html-elements` 未启用——uni 的 H5 侧本就允许原生标签，
//      强行拦会误报；仍靠 review）；③ 由 `tests/conventions.test.ts` 兜；
//   ② 纯 CSS 约定，ESLint 看不到，仍靠 review。
//
// ## 三条禁令与它们的"正确出口"
//
// | 禁止 | 原因 | 请改用 |
// |---|---|---|
// | `alert` / `confirm` | 绕过全站统一弹窗出口（样式与交互不一致） | `utils/ui.ts` 的 `showAlert` / `showConfirm` |
// | `localStorage` | 绕过存储适配层（换实现 / 改前缀要全站搜） | `utils/storage.ts` 的 `storage` |
// | `uni.request` | 绕过 token 注入 / 401 处理 / 剥壳 | `api/` 层（唯一出口 `api/request.ts`） |
//
// 例外：`src/api/request.ts` 与 `src/utils/*` 是**兼容层本身** —— 它们就是"允许碰平台 API
// 的地方"（见 README「模块架构」），故在文件末尾单独放行。
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

/** 三条调用点禁令（AST 选择器） */
const BANNED_SYNTAX = [
  {
    selector: "MemberExpression[object.name='uni'][property.name='request']",
    message: '禁止直接调用 uni.request —— 请走 api/ 层（唯一出口是 src/api/request.ts）',
  },
  {
    selector: "MemberExpression[object.name='window'][property.name='alert']",
    message: '禁止 window.alert —— 请用 utils/ui.ts 的 showAlert（统一弹窗出口）',
  },
  {
    selector: "MemberExpression[object.name='window'][property.name='confirm']",
    message: '禁止 window.confirm —— 请用 utils/ui.ts 的 showConfirm（统一弹窗出口）',
  },
]

export default [
  { ignores: ['dist/**', 'node_modules/**', 'src/static/**', 'src/api/generated/**', 'eslint.config.mjs', 'vitest.config.ts'] },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  // ⚠️ 用 `essential` 而**不是** `recommended`：后者会把 `max-attributes-per-line` /
  // `singleline-html-element-content-newline` 这类**排版偏好**全打开，实测在本项目
  // 产生 1400+ 条 warning（全站写法是紧凑内联标签），把真问题淹没在噪声里。
  // 这里只要"正确性"级别：语法错误、未定义变量、危险的 v-for/v-if 组合等。
  ...pluginVue.configs['flat/essential'],

  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        // uni-app 运行时
        uni: 'readonly',
        getCurrentPages: 'readonly',
        // 浏览器侧
        window: 'readonly',
        document: 'readonly',
        location: 'readonly',
        navigator: 'readonly',
        console: 'readonly',
        crypto: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        URLSearchParams: 'readonly',
      },
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      // TS 项目惯例：类型与运行时全局由 TS 自己检查，`no-undef` 在 .vue 里常误报
      // （实测误报 Event / HTMLInputElement / PointerEvent / MouseEvent / KeyboardEvent /
      //  HTMLImageElement / setInterval / clearInterval 共 13 处）
      'no-undef': 'off',
      'no-alert': 'error',
      'no-restricted-syntax': ['error', ...BANNED_SYNTAX],
      'no-restricted-globals': [
        'error',
        {
          name: 'localStorage',
          message: '禁止直用 localStorage —— 请走 utils/storage.ts 的 storage（uni 存储封装）',
        },
        {
          name: 'sessionStorage',
          message: '禁止直用 sessionStorage —— 请走 utils/storage.ts 的 storage',
        },
      ],

      // uni 的 .vue 写法与 Web 惯例不同，放宽几条噪音规则
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },

  // uni 的 App.vue 是**应用级容器、不渲染模板**（各页面独立渲染，见文件内注释），
  // 因此它的 `<template>` 为空是正常写法 —— 放行 `vue/valid-template-root`
  {
    files: ['src/App.vue'],
    rules: { 'vue/valid-template-root': 'off' },
  },

  // ---- 例外：兼容层是"唯一允许碰平台 API 的地方" ----
  {
    files: ['src/api/request.ts', 'src/utils/**'],
    rules: { 'no-restricted-syntax': 'off', 'no-restricted-globals': 'off' },
  },
  // 测试文件跑在 node 下，不受写法约定约束
  {
    files: ['tests/**'],
    languageOptions: { globals: { describe: 'readonly', it: 'readonly', expect: 'readonly' } },
  },
]
