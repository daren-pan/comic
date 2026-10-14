// ESLint 扁平配置（ESLint 9，ESM）—— 对应 comic-web/README.md「开发约定」。
//
// ## 为什么要有它
//
// 三条写法约定此前只写在文档里、靠人肉 review 执行：
//   ① 模板只用项目既有标签体系（原生 HTML + 自建组件；不引第三方 UI 库）
//   ② CSS 只写类选择器
//   ③ 自定义组件不用 v-model（统一显式写法）
//
// 这份配置把「能被自动检查的部分」变成机器门禁：
//   ① / ② 仍靠 review（ESLint 看不到模板标签与 CSS）；③ 由 `tests/conventions.test.ts` 兜。
//
// ## 两条禁令与它们的"正确出口"
//
// | 禁止 | 原因 | 请改用 |
// |---|---|---|
// | `alert` / `confirm` | 绕过全站统一弹窗出口（样式与交互不一致） | `utils/ui.ts` 的 `showAlert` / `showConfirm` |
// | `localStorage` | 绕过存储适配层（换实现 / 改前缀要全站搜） | `utils/storage.ts` 的 `storage` |
//
// 例外：`src/utils/*` 是**兼容层本身** —— 它们就是"允许碰平台 API 的地方"，故单独放行。
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'public/**', 'src/api/generated/**', 'eslint.config.mjs', 'vitest.config.ts'] },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  // ⚠️ 用 `essential` 而**不是** `recommended`：后者会把 `max-attributes-per-line` /
  // `singleline-html-element-content-newline` 这类**排版偏好**全打开，实测在本项目
  // 产生上千条 warning（全站写法是紧凑内联标签），把真问题淹没在噪声里。
  // 这里只要"正确性"级别：语法错误、未定义变量、危险的 v-for/v-if 组合等。
  ...pluginVue.configs['flat/essential'],

  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
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
      'no-undef': 'off',
      'no-alert': 'error',
      'no-restricted-globals': [
        'error',
        {
          name: 'localStorage',
          message: '禁止直用 localStorage —— 请走 utils/storage.ts 的 storage',
        },
        {
          name: 'sessionStorage',
          message: '禁止直用 sessionStorage —— 请走 utils/storage.ts 的 storage',
        },
      ],

      // .vue 写法与通用惯例不同的地方，放宽几条噪音规则
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },

  // ---- 例外：兼容层是"唯一允许碰平台 API 的地方" ----
  {
    files: ['src/utils/**'],
    rules: { 'no-restricted-globals': 'off' },
  },
  // 测试文件跑在 node 下，不受写法约定约束
  {
    files: ['tests/**'],
    languageOptions: { globals: { describe: 'readonly', it: 'readonly', expect: 'readonly' } },
  },
]
