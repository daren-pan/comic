// 三种检索模式的说明 —— 页面各处共用这一份，避免不同页签写出不同口径。
//
// 名称统一用中文：**语义检索 / 字面检索 / 混合检索**。英文键（vector / lexical / hybrid）
// 只用于调用后端接口，界面上不出现。

export const MODES = [
  {
    key: 'vector',
    label: '语义检索',
    short: '只看语义相似度：把问题编码成向量，找最近的 chunk',
    detail:
      '分数 = 余弦相似度 + 三种加权（标题命中 +0.12、模块命中 +0.08、正文命中），' +
      '低于 min_score(0.45) 的直接丢弃。',
    good: '口语、同义改写、概念性问题',
    bad: '型号、报错码、函数名、专有名词',
    score: 'score = 余弦 + 加权，0~1（看这一列最直观）',
  },
  {
    key: 'lexical',
    label: '字面检索',
    short: '只看字面匹配：问题与 chunk 切词后按 BM25 打分',
    detail:
      '按「词的稀有度 × 词频 × 长度折扣」求和，分数无上界（实测 0~20）。' +
      '注意：它仍会先跑语义那一路，只是不用其排序 —— 所以并不比混合检索快。',
    good: '标识符、报错码、精确术语（require_admin、X-Service-Token）',
    bad: '同义改写（问“角色几档”而文档写“三档角色”可能对不上）',
    score: 'score = BM25 原始分（无上界，不能当 0~1 用）',
  },
  {
    key: 'hybrid',
    label: '混合检索',
    short: '两路各出候选，按名次融合：谁在两路都靠前，谁就赢',
    detail:
      '每条得分 = Σ 1/(60 + 它在那一路的名次)。只出现在一路的记 1/61≈0.016；' +
      '两路都靠前的会叠加（1/61 + 1/64 ≈ 0.032，明显更高）。' +
      '平局按 doc_id 字典序排 —— 这是「只合并不裁决」的已知短板。',
    good: '生产默认：兼顾语义与字面',
    bad: '字面噪音会挤进前排（案例：文档里讲过的专有名词反而抢第一）',
    score: 'score = RRF 分，量级约 0.016（不是相似度，别拿 0.45 去卡）',
  },
]

export const MODE_BY_KEY = Object.fromEntries(MODES.map((m) => [m.key, m]))

export const MODE_OPTIONS = MODES.map((m) => ({ key: m.key, label: m.label }))

// 命中来源：后端在 `sources` 里给的是 `vector` / `lexical`，界面上要显示中文。
export const SOURCE_LABELS = {
  vector: '语义',
  lexical: '字面',
}

export const sourceLabel = (key) => SOURCE_LABELS[key] ?? key
