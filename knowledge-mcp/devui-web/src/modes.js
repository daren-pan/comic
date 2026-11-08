// 三种检索模式的说明 —— 页面各处共用这一份，避免不同页签写出不同口径。
//
// 名称统一用中文：**语义检索 / 字面检索 / 混合检索**。英文键（vector / lexical / hybrid）
// 只用于调用后端接口，界面上不出现。
//
// ⚠️ 这里的公式必须与 `retriever.py` / `config.py` 保持一致；
// 改了检索参数（权重、k、阈值）就要同步改这里，否则界面会"教错人"。

export const MODES = [
  {
    key: 'vector',
    label: '语义检索',
    short: '只看语义相似度：把问题编码成向量，找最近的 chunk',
    detail:
      '分数 = 余弦相似度 + 模块加成（问题命中某模块的线索且 chunk 属于该模块时 +0.06，' +
      '查表结构再 +0.03），低于 min_score(0.45) 的直接丢弃。' +
      '编码模型是 bge-small-zh-v1.5（512 维，余弦）。',
    good: '口语、同义改写、概念性问题',
    bad: '型号、报错码、函数名、专有名词',
    score: 'score = 余弦 + 模块加成，0~1（看这一列最直观）',
  },
  {
    key: 'lexical',
    label: '字面检索',
    short: '只看字面匹配：问题与 chunk 切词后按 BM25 打分',
    detail:
      '按「词的稀有度 × 词频饱和 × 长度归一」求和（k1=1.8、b=0.9），分数无上界（实测 0~20）。' +
      '不设绝对阈值 —— BM25 分随分词器变化，拿固定门槛卡会误伤。',
    good: '标识符、报错码、精确术语（require_admin、X-Service-Token）',
    bad: '同义改写（问“角色几档”而文档写“三档角色”可能对不上）',
    score: 'score = BM25 原始分（无上界，不能当 0~1 用）',
  },
  {
    key: 'hybrid',
    label: '混合检索',
    short: '两路各出候选，按名次融合：谁在两路排得靠前，谁就赢',
    detail:
      '每条得分 = Σ 权重 / (k + 它在那一路的名次)，语义权重 0.75、字面 0.25，k=3。' +
      '只出现在语义一路第 1 名拿 0.75/4 ≈ 0.19；两路都出现的会叠加（分数更高）。' +
      'k 小是刻意的：k 越大，"两路都靠后"越容易压过"单路第一"，字面噪音就会抢第一。',
    good: '生产默认：语义为主，字面负责专有名词兜底',
    bad: '两路都不认的查询（那就只能靠语料补词）',
    score: 'score = RRF 分，量级约 0.19（不是相似度，别拿 0.45 去卡）',
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
