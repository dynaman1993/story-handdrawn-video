# Prompt 配方

## 三段式结构

每场 prompt 由脚本自动拼成：

```
<STYLE_HEADER>        ← 固定，所有场复用
<SCENE_BODY>          ← 来自 visual_plan[id]，或自动生成
<MOTION_FOOTER>       ← 固定，所有场复用
```

`negative_prompt` 也是固定字符串。**不要**在 visual_plan 里重复这些固定段，
脚本会自动拼接，重复会让模型注意力分散。

## STYLE_HEADER（固定）

```
modern Q-version hand-drawn crayon illustration, vertical 9:16, solid warm-white
canvas background with exact base color #F8F6EF, only extremely subtle low-contrast
paper grain, thick imperfect black hand-drawn marker/crayon outlines, bold flat
wax-crayon blocks in sunflower yellow, saturated cobalt blue, vivid tomato red
with a small muted-green accent, natural restrained Q-version proportions, simple
hand-drawn composition, 2-4 large readable visual groups, generous breathing room,
no glossy rendering, no realistic lighting, no 3D, no watermark
```

## MOTION_FOOTER（固定）

```
locked flat frontal camera, rigid paper cutouts, tactile 10-12 fps paper stop-motion,
one or two small object bounces or a short hinge-like hand movement, no zoom, no
parallax, no camera drift, no liquid morphing, no lip sync, no new characters,
no added logos or text, settle and hold the final composition naturally
```

## NEGATIVE（固定）

```
text, letters, subtitles, captions, Chinese characters, English words, numbers,
watermark, logo, signature, border frame, photorealistic, 3D render, gradient
background, vignette, black background, glossy, neon
```

## SCENE_BODY 怎么写

### 有 visual_plan 时

直接写英文的场景动作，一句话。包含：
- 主体（谁/什么）
- 动作（在做什么）
- 场景关键道具/环境
- 必要时构图提示（close-up / from behind / wide shot）

例：
```json
{
  "01": "A seven-year-old girl in a yellow raincoat crouching to offer half a bun to a skinny orange stray cat under a shop eave, rain puddles in the foreground, close-up on hands and cat, no faces filling the frame",
  "07": "A kitchen table seen from above at night, two bowls of instant noodles, one bowl tucked under a small folded blanket, a man's hand reaching toward the blanket, no faces"
}
```

注意：
- 用 `close-up` / `from behind` / `over the shoulder` 等具体视角词，比抽象情绪有用。
- 不想让模型画脸就写 `no faces visible` / `from behind` / `silhouette`。
- 医疗、暴力、敏感场面用 CLOSE-UP 道具/背影/剪影，不要正面全景。

### 没 visual_plan 时

脚本直接把中文原句作为 scene body 塞进 prompt。Agnes Video 是中国公司模型，
能理解中文语义；`negative_prompt` 已强制排除画面文字，一般不会把中文字画出来。
质量约 60–70%，70% 原则下能用。如果某段真的出乱码文字，单删那一段 mp4 重跑
（或补 visual_plan 用英文 scene body，质量更高、无乱码风险）。
题材敏感时，**强烈建议**写 visual_plan。

### 写 visual_plan 的硬规则

- 用英文写（Agnes Video 能理解中文，但英文 scene body 更稳、无乱码风险）。
- **不写像素坐标、百分比、`y=510`、`10%`** —— 模型会把这些数字 literally 画上去。
- 不写「不要画 XX」长串负面词 —— 会触发负面偏见，模型反而画出来。真要避免，用构图绕开（close-up / from behind）。
- 不重复 STYLE_HEADER / MOTION_FOOTER 里已有的词。
- 一场一个核心动作，不要堆 5 个动作。

## 视觉隐喻速查

口播是抽象概念时，用具象隐喻：

| 口播 | 画面 |
|---|---|
| 竞争/落后 | 跑道、接力棒、两个人一前一后 |
| 成本/花钱 | 漏水的桶、硬币掉落、存钱罐 |
| 验证/检查 | 放大镜、体检单、对勾 |
| 选择/分歧 | 岔路、两扇门、天平 |
| 风险/警告 | 摇晃的积木、裂缝、三角警示牌 |
| 时间/等待 | 沙漏、日历翻页、时钟 |
| 想法/灵感 | 灯泡、云朵上的小气泡 |

## 不同题材的构图建议

- **亲情/家庭**：中景 + 背影 / 手部特写，避免正面对视（容易训练先验污染）
- **童话/动物**：Q 版全身，主体占画面 60%，背景留白
- **知识口播 B-roll**：物件为主，人物只做引导（一只手指向、一只手托着）
- **历史/真实人物**：非写实 Q 版 caricature，用发型/眼镜/服装/道具锚定身份，**不要**追求肖像还原
- **医疗/打针/手术**：CLOSE-UP 道具（听诊器、药瓶、绷带卷），不画病人正脸

## textbook 模式（英语教学）

`--style textbook` 用不同的 STYLE_HEADER / MOTION_FOOTER：

```
STYLE_HEADER_TEXTBOOK = clean educational textbook illustration for adult English
learners, vertical 9:16, soft warm-white background, a narrative scene that clearly
illustrates the meaning of the sentence, simple colorful flat illustration in the
style of an Oxford English textbook, soft bright educational palette (cobalt blue,
warm red, mustard yellow, sage green), clean confident outlines, clear readable
subject and action, tasteful simple setting or landscape where the scene needs it,
no text, no letters, no words, no numbers anywhere in the image, no realistic
shading, no paper texture, no 3D, no watermark, no crayon texture, no painterly
brush strokes

MOTION_FOOTER_TEXTBOOK = locked steady camera, gentle but visible motion that
supports the sentence meaning (a ship sailing, a quill writing, figures walking
or gesturing, a flag waving, pages turning, light shifting), smooth 12-15 fps
animation, no zoom, no parallax, no camera drift, no morphing, no lip sync,
no new characters, no added logos or text, hold the final composition clearly
```

### textbook visual 写法（CQ001 试错出来的硬规则）

每场 visual 是 `teaching_content.json` 里的 `visual` 字段，不是 `visual_plan.json`。

**必须包含**：
- **谁**（a colonial farmer / two delegates / a teacher's hand）
- **在哪**（in a sunlit classroom / on a colonial coastline / at a wooden desk）
- **做什么**（unrolling a parchment / pointing at a scroll / walking toward a building）
- **能见的动作**（写一个能动的元素：手 unrolling、船 sailing、人 walking、烛光 flickering）
- 调色板和风格尾：`Oxford textbook illustration, no text or letters anywhere`

**禁止**：
- `pure white background` —— Agnes 会画居中图标 + 左右大白边，视频成窄条，被左右奶白色"夹杀"
- 抽象词：`icon` / `diagram` / `exploded-view` / `thought bubble` / `puzzle pieces` / `balance scale in center`
- 装饰来"补充意义"：`floating arrows` / `radiating lines` / `floating stars`
- 「same scene as X」之类引用

判断标准：**visual 文字读起来像不像一幅能讲故事的插画**。像图标 logo / 教学示意图 / 抽象概念图就重写。

### CQ001 实例（27 场的成功 visual）

参考模板自带的 `templates/remotion-project/examples/teaching_content.example.json`（CQ 系列前三场示例）：

| 关键词 | 句意 | visual（前 80 字） |
|---|---|---|
| exist | 1787 年美国还不像今天存在 | American coastline around 1787: wooden sailing ship anchored near a wild forested shore, scattered colonial houses... |
| problem | 但他们遇到很多问题 | Two worried colonial-era men in long coats beside a rough wooden table covered with scattered papers, an empty coin pouch... |
| convention | 在费城召开的制宪会议 | Independence Hall, a simple brick colonial building with a tall steeple and cupola, on a bright summer day with a blue sky... |
| resolve | 用宪法来解决问题 | Two colonial men sitting across a wooden table in a tavern, a large parchment scroll between them emitting soft warm light... |

每场都是「谁 + 在哪 + 做什么」三要素齐备的叙事场景，不是图标。

