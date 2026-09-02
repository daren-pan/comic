// Mock 数据层 —— 数据结构与后端采集服务（comic/chapter/page 表）完全对应，
// 之后将 api/index.ts 中的实现替换为真实 HTTP 请求即可无缝切换。
import type { Chapter, Comic, PageInfo } from '../types'
import { makeCover, makePageImage } from '../utils/images'

const NOW = Date.now()
const h = (n: number) => new Date(NOW - n * 3600_000).toISOString()

interface ComicSeed {
  title: string
  author: string
  category: string
  status: '连载中' | '已完结'
  description: string
  views: number
  updatedHoursAgo: number
  sources: string[]
  tags: string[]
  chapterTitles: string[]
}

const SEEDS: ComicSeed[] = [
  {
    title: '海贼王', author: '尾田荣一郎', category: '热血', status: '连载中',
    description: '立志成为海贼王的少年路飞，带着草帽一伙驶向伟大航路的传奇冒险。多源聚合示例：本站数据同时来自 demo_source 与 demo_source_b 两个源站，跨站指纹去重后合并为同一作品。',
    views: 986532, updatedHoursAgo: 2, sources: ['demo_source', 'demo_source_b'],
    tags: ['冒险', '少年', '长篇'],
    chapterTitles: ['我要成为海贼王', '草帽海贼团集结', '颠倒山与伟大航路', '阿拉巴斯坦篇·沙之国的公主', '空岛·黄金钟的回响', '司法岛篇·告别梅利号', '顶上战争·白胡子的意志', '和之国篇·光月御田'],
  },
  {
    title: '鬼灭之刃', author: '吾峠呼世晴', category: '热血', status: '已完结',
    description: '家人被鬼杀害的少年炭治郎，为了让变成鬼的妹妹重新变回人类，加入鬼杀队展开战斗。',
    views: 812340, updatedHoursAgo: 5, sources: ['demo_source'],
    tags: ['战斗', '和风', '亲情'],
    chapterTitles: ['残酷的杀意', '紫藤花下的决意', '最终选拔·錆兔与真菰', '那田蜘蛛山', '无限列车·炎之炼狱', '游郭篇·音柱的任务', '锻刀村篇', '无限城决战'],
  },
  {
    title: '火影忍者', author: '岸本齐史', category: '热血', status: '已完结',
    description: '被村子排挤的少年鸣人，为了获得认同、成为火影而不断成长的忍者物语。',
    views: 753214, updatedHoursAgo: 8, sources: ['demo_source'],
    tags: ['忍者', '羁绊', '成长'],
    chapterTitles: ['漩涡鸣人登场', '写轮眼的卡卡西', '波之国·再不斩', '中忍考试开幕', '我爱罗与我', '佐助叛逃', '疾风传·师徒再会', '第四次忍界大战'],
  },
  {
    title: '名侦探柯南', author: '青山刚昌', category: '悬疑', status: '连载中',
    description: '被黑衣组织灌下毒药变小的高中生侦探工藤新一，以江户川柯南的身份破解一个又一个谜案。',
    views: 665412, updatedHoursAgo: 1, sources: ['demo_source'],
    tags: ['推理', '单元剧', '经典'],
    chapterTitles: ['云霄飞车杀人事件', '偶像密室杀人事件', '暗号所透露的杀意', '神秘列车上的推理', '红与黑的碰撞', '基德与怪盗预告函', '黑衣组织现身', 'FBI连续失踪事件'],
  },
  {
    title: '进击的巨人', author: '谏山创', category: '奇幻', status: '已完结',
    description: '高墙之内的人类与巨人的殊死搏斗，以及墙外世界的残酷真相。',
    views: 598741, updatedHoursAgo: 12, sources: ['demo_source'],
    tags: ['黑暗', '政治', '巨人'],
    chapterTitles: ['致两千年后的你', '巨人的袭击', '训练兵团的日常', '罗塞之墙的陷落', '女巨人的真面目', '夺还战·鎧之巨人', '玛利亚之墙夺还', '地鸣与终结'],
  },
  {
    title: '一拳超人', author: 'ONE/村田雄介', category: '搞笑', status: '连载中',
    description: '兴趣使然的英雄埼玉，无论什么怪人都是一拳解决。认真起来的他又强又帅。',
    views: 532687, updatedHoursAgo: 3, sources: ['demo_source'],
    tags: ['搞笑', '战斗', '反套路'],
    chapterTitles: ['最强的男人', '进化之家', '陨石来袭', '深海王', '武道大会', '饿狼篇·怪人协会', '英雄协会的阴影'],
  },
  {
    title: '间谍过家家', author: '远藤达哉', category: '搞笑', status: '连载中',
    description: '间谍父亲、杀手母亲、超能力女儿组成的临时家庭，在相互隐瞒中爆笑又温馨的日常。',
    views: 489325, updatedHoursAgo: 4, sources: ['demo_source', 'demo_source_b'],
    tags: ['家庭', '间谍', '温馨'],
    chapterTitles: ['黄昏的任务', '伪装家庭组建', '入学考试', '入学伊甸学园', '邦德狗登场', '游轮之旅', '东国与西国之间'],
  },
  {
    title: '咒术回战', author: '芥见下下', category: '热血', status: '连载中',
    description: '吞下诅咒之王手指的少年虎杖悠仁，与咒术高专的伙伴们一同对抗咒灵的暗黑物语。',
    views: 456987, updatedHoursAgo: 6, sources: ['demo_source'],
    tags: ['战斗', '咒灵', '少年'],
    chapterTitles: ['两面宿傩', '咒术高专入学', '少年院任务', '交流会篇', '涩谷事变', '死灭回游', '最终决战'],
  },
  {
    title: '电锯人', author: '藤本树', category: '奇幻', status: '已完结',
    description: '与电锯恶魔合体的少年电次，在恶魔猎人的世界中挣扎求生的疯狂物语。',
    views: 431258, updatedHoursAgo: 24, sources: ['demo_source_b'],
    tags: ['黑暗', '恶魔', '荒诞'],
    chapterTitles: ['电锯与狗', '波奇塔的约定', '公安恶魔猎人', '早川秋', '姬野之死', '蕾塞篇·初恋的味道', '枪之恶魔篇'],
  },
  {
    title: '辉夜大小姐想让我告白', author: '赤坂明', category: '恋爱', status: '已完结',
    description: '天才们的恋爱头脑战——谁先告白谁就输了？傲娇天花板之间的极限拉扯。',
    views: 398654, updatedHoursAgo: 16, sources: ['demo_source'],
    tags: ['校园', '恋爱喜剧', '傲娇'],
    chapterTitles: ['谁先告白谁就输', '辉夜与会长', '学生会日常', '烟火大会', '石上优的过去', '告白与毕业'],
  },
  {
    title: '五等分的花嫁', author: '春场葱', category: '恋爱', status: '已完结',
    description: '贫穷高中生成为五胞胎姐妹的家庭教师，与她们的恋爱故事——新娘究竟是谁？',
    views: 356987, updatedHoursAgo: 20, sources: ['demo_source'],
    tags: ['后宫', '校园', '悬疑恋爱'],
    chapterTitles: ['五胞胎姐妹', '家庭教师上任', '期末考试之战', '修学旅行', '中野五月的心意', '选择与婚礼'],
  },
  {
    title: '新世纪福音战士', author: '贞本义行', category: '科幻', status: '已完结',
    description: '少年少女驾驶泛用人型决战兵器 EVA，迎战神秘使徒的宏大叙事。',
    views: 321478, updatedHoursAgo: 30, sources: ['demo_source'],
    tags: ['机甲', '心理', '宗教隐喻'],
    chapterTitles: ['使徒袭来', '绫波丽', '第四适格者', '碇真嗣的迷茫', '明日香登场', '人类补完计划'],
  },
  {
    title: '银魂', author: '空知英秋', category: '搞笑', status: '已完结',
    description: '幕末废柴武士坂田银时与万事屋成员们的无节操搞笑日常，笑中带泪。',
    views: 298741, updatedHoursAgo: 40, sources: ['demo_source'],
    tags: ['恶搞', '武士', '日常'],
    chapterTitles: ['银时与万事屋', '废柴三人组', '登势婆婆的酒馆', '真选组出动', '将军与荞麦面', '最后的大战'],
  },
  {
    title: '葬送的芙莉莲', author: '山田钟人/阿部司', category: '奇幻', status: '连载中',
    description: '勇者一行打倒魔王之后，长寿精灵芙莉莲踏上理解人类、追寻回忆的旅程。',
    views: 265874, updatedHoursAgo: 7, sources: ['demo_source_b'],
    tags: ['治愈', '冒险', '时间'],
    chapterTitles: ['旅途的终点', '精灵的乡愁', '一级魔法使考试', '大陆的魔法', '回忆之旅', '人类与魔族的战争'],
  },
  {
    title: '蓝色监狱', author: '金城宗幸/野村优介', category: '运动', status: '连载中',
    description: '为了培养日本最强前锋，300 名高中生被关进「蓝色监狱」展开残酷的自我进化。',
    views: 234569, updatedHoursAgo: 9, sources: ['demo_source'],
    tags: ['足球', '竞争', '心理战'],
    chapterTitles: ['蓝色监狱计划', '第一轮选拔', '洁世一的觉醒', '流星队 VS 战队', 'U-20 日本代表战', '新英雄大战'],
  },
]

export function buildMockData(): { comics: Comic[]; chapters: Chapter[] } {
  const comics: Comic[] = []
  const chapters: Chapter[] = []
  SEEDS.forEach((seed, i) => {
    const id = i + 1
    const chapterTitles = seed.chapterTitles.slice(0, 6 + (i % 10))
    const chapterCount = chapterTitles.length
    comics.push({
      id,
      title: seed.title,
      author: seed.author,
      category: seed.category,
      status: seed.status,
      description: seed.description,
      cover: makeCover(seed.title, seed.author, seed.title),
      latestChapterTitle: chapterTitles[chapterTitles.length - 1],
      chapterCount,
      views: seed.views,
      updatedAt: h(seed.updatedHoursAgo),
      sources: seed.sources,
      tags: seed.tags,
    })
    chapterTitles.forEach((title, ci) => {
      const pageCount = 8 + ((id * 7 + ci * 3) % 8) // 8~15 页
      chapters.push({
        id: id * 1000 + ci + 1,
        comicId: id,
        title,
        pageCount,
        orderNo: ci + 1,
        createdAt: h(seed.updatedHoursAgo + (chapterTitles.length - ci) * 2),
      })
    })
  })
  return { comics, chapters }
}

export const MOCK = buildMockData()

export function getChapterPages(comicId: number, chapterId: number): PageInfo[] {
  const ch = MOCK.chapters.find((c) => c.id === chapterId && c.comicId === comicId)
  if (!ch) return []
  const comic = MOCK.comics.find((c) => c.id === comicId)
  const total = ch.pageCount
  return Array.from({ length: total }, (_, i) => ({
    pageNo: i + 1,
    imageUrl: makePageImage(comic?.title ?? '漫画', ch.title, i + 1, total),
    width: 720,
    height: 1020,
  }))
}
