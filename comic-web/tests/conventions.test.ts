// 约定守卫：**自定义组件上不用 `v-model`** —— 全站统一显式写法（`:prop` + `@update:prop`）。
//
// 与后端 `api-service/tests/test_layering.py` 完全同一思路：
// **把文档里的约定变成会红的断言**，否则它只会慢慢退化成"没人记得的规矩"。
//
// 为什么不用 ESLint 查这条：`v-model` 是 vue 模板的**编译期语法糖**，而
// `no-restricted-syntax` 的 AST 选择器对 vue-eslint-parser 的模板节点支持有限。
// 这里直接扫源码文本 —— 朴素，但对"某个标签上有没有 v-model"足够可靠。
//
// 规则的边界：只查**自定义组件**（标签名首字母大写）。`<input>` / `<select>` 这类
// 原生元素上的 `v-model` 是**正常用法**，不拦。
//
// 例外：`NativeDateInput`（`src/components/DateInput.vue`）—— 它是
// **渲染函数组件**（`h('input', …)` 直接产出原生元素），
// 已在 README「开发约定」里登记为例外。
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('../src', import.meta.url))
const ALLOWED = new Set(['NativeDateInput'])

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) return vueFiles(full)
    return entry.name.endsWith('.vue') ? [full] : []
  })
}

describe('开发约定', () => {
  it('自定义组件上不得使用 v-model（改用 :prop + @update:prop）', () => {
    const offenders: string[] = []
    for (const file of vueFiles(SRC)) {
      const text = readFileSync(file, 'utf8')
      // 匹配"开标签 + 其属性"，属性段用 [^>]* 取（模板属性里几乎不会出现裸 `>`）
      for (const m of text.matchAll(/<([A-Z][A-Za-z0-9]*)\b([^>]*?)\/?>/g)) {
        const [, tag, attrs] = m
        if (ALLOWED.has(tag)) continue
        if (/\bv-model\b/.test(attrs)) {
          offenders.push(`${file.slice(SRC.length + 1)}: <${tag}>`)
        }
      }
    }
    expect(offenders, '这些位置在自定义组件上用了 v-model').toEqual([])
  })
})
