# 底数速报 · 编辑页「AI帮写」接口自动化清单

依据当前代码整理（2026-11-19），给接口/UI 自动化用。路径以现网实现为准。

旧文档 `spec/一期功能/页面截图/底数速报调整后/底数速报后端接口清单.md` 里的 `/api/v1/mobile/ai-assist/generate`（一次出三套方案）没有落地，不要按那份写用例。

页面：移动端底数速报编辑页底部「AI帮写」。弹层里是推荐主题、篇幅（50 / 100 / 200 / 自定义）、文风（正式公文 / 精炼简报 / 通俗通报）、写作要求、语音、生成内容。采纳只改本机草稿，点编辑页「完成」才落库。

---

## 1. 测通这一块要打哪些接口

分三档。接口自动化跑「主链路 + 分支」即可宣称 AI 帮写测通。UI 自动化还要让「页面加载」里的接口可用，否则进不了编辑页。

### 1.1 主链路（每次都跑）

| 序号 | 方法 | 路径 | 作用 |
| --- | --- | --- | --- |
| 0 | POST | `/oauth/auth/login` | 换统一认证 token。不在 BI 后端上 |
| 1 | GET | `/api/v1/mobile/brief-report/scenes` | 取页签编码 `tabCode` |
| 2 | GET | `/api/v1/mobile/brief-report/current` | 打开速报，拿到 `id`、`revision`、截止日、正文 |
| 3 | GET | `/api/v1/mobile/brief-report/metrics` | 推荐主题（要点胶囊，已填数） |
| 4 | POST | `/api/v1/mobile/brief-report/ai-generate` | 调模型生成段落 |
| 5 | POST | `/api/v1/mobile/brief-report/complete` | 把采纳后的正文存成新版本 |
| 6 | GET | `/api/v1/mobile/brief-report/current` | 再读一遍，确认正文已保存 |

### 1.2 弹层分支（覆盖截图上的全部操作）

| 序号 | 方法 | 路径 | 何时必须打 |
| --- | --- | --- | --- |
| 7 | POST | `/api/v1/mobile/brief-report/voice-transcribe` | 测弹层里的语音输入 |
| 8 | GET | `/api/v1/mobile/system-config` | 测开关：AI 关、语音关、模型未配置 |

`ai-generate` 本身要覆盖：三种文风、三种固定篇幅、自定义字数、选中主题、不选主题自由写、带 `draftText` 的改写。见第 6 节。

### 1.3 建议抽一条做「模型真的被调用了」

生成成功体里有 `traceId`。用它核对网关日志，避免只断言 HTTP 200、内容却是空壳。

| 序号 | 方法 | 路径 |
| --- | --- | --- |
| 9 | GET | `/api/v1/modelgateway/runtime/logs/trace/{traceId}` |
| 10 | GET | `/api/v1/modelgateway/runtime/logs/detail/{logId}` |

### 1.4 只有 UI 自动化会顺带打到

编辑页 `loadReportFn` 在生成之前就会请求这些。接口脚本如果已经自己准备好 `orgCode` / `tabCode`，可以不调用。

| 方法 | 路径 | 页面何时调用 |
| --- | --- | --- |
| GET | `/api/v1/mobile/brief-templates/system` | 每次进速报/编辑页 |
| GET | `/api/v1/mobile/brief-report/subscription` | 当前速报带了 `templateId` 时 |
| GET | `/api/v1/mobile/system-config?keys=brief.voice.enabled` | 进编辑页，决定语音按钮显隐 |
| GET | `/api/v1/mobile/brief-report/banner-summary` | 速报列表 URL 没带 `reportTab` 时，用来决定默认页签 |

没有现成机构编码时，用看板辖区树拿 `orgCode`（`options[].value`）：

| 方法 | 路径 |
| --- | --- |
| GET | `/api/bi/data/reader/boards` |
| GET | `/api/bi/data/reader/boards/{boardId}/regions` |

### 1.5 不要放进本模块脚本

管理端配置（组织层级、页签绑定、胶囊保存、模板发布、提示词、业务配置增改）是环境准备，不是 AI 帮写运行时接口。环境缺数据时生成仍可能 200，但推荐主题为空、数字全是「待核实」。

运维登录 `POST /api/v1/ops-auth/login` 签发的是运维 JWT。底数速报从统一认证用户取 `username`。请求若带 `X-BI-Ops-Token`，会走进运维安全链，C 端接口会 401「未登录或令牌失效」。自动化账号用第 0 步的统一认证 token。

---

## 2. 调用约定

### 2.1 基地址（测试环境 83）

| 用途 | 基地址 |
| --- | --- |
| BI 业务接口 | `http://172.25.181.83/jcfn/biz` |
| 统一认证换票 | `http://172.25.181.83/oauth/` |
| 直连后端（需放行 8080，路径不再加 `/jcfn/biz`） | `http://172.25.181.83:8080` |

下文路径都写成后端路径。经 80 端口访问时，前面加上 `/jcfn/biz`。例如生成接口的完整地址是：

`POST http://172.25.181.83/jcfn/biz/api/v1/mobile/brief-report/ai-generate`

### 2.2 登录与请求头

业务接口成功壳：

```json
{ "status": "200", "message": "...", "data": { } }
```

自动化只在 `status == "200"` 时读取 `data`。前端也是这样拆包的。

业务请求头：

```http
Authorization: Bearer {access_token}
Content-Type: application/json
```

`Authorization` 的值是换票结果里的 `token_type + 空格 + access_token`，一般就是 `Bearer xxxxx`。不要传 `userId`，服务端只认登录用户。当前租户在服务端固定为 `"1"`，脚本不用传租户来切换数据。

失败有两种形态，断言时都要认：

- HTTP 200，但 `status` 不是 `"200"`：读 `message`。登录失效常见壳码会让前端重新登录。
- HTTP 4xx/5xx：`ResponseStatusException`。Spring 默认是 ProblemDetail，业务原因在 `detail`，例如 `"AI帮写未开启"`。若现场被包装成 ApiResult，则看 `message`。用例以 **HTTP 状态码 + detail/message 文案** 为准。

| HTTP | detail | 含义 |
| --- | --- | --- |
| 401 | 未登录或令牌失效 | 没带统一认证 token，或带了运维 token |
| 403 | AI帮写未开启 | `brief.ai.enabled` 的 `enabled` 为 false |
| 403 | 语音输入未开启 | `brief.voice.enabled` 的 `enabled` 为 false |
| 503 | AI模型未配置（brief.ai.model-code 或 bi.brief.ai.model-code） | 配置和 yml 都没有模型编码 |
| 503 | 语音模型未配置（brief.voice.model-code 或 bi.brief.voice.model-code） | 同上，语音 |
| 502 | 生成失败，请重试 | 模型网关无响应、调用失败或内容为空 |
| 502 | 转换失败，请重试 | 语音网关失败 |
| 400 | 录音文件为空 / 录音读取失败 | 语音上传 |
| 404 | 基于的速报不存在 | `complete` 的 `basedReportId` 无效 |
| 409 | 速报已被更新，请重新加载后编辑 | `expectedRevision` 与库中修订号不一致 |

### 2.3 两个关键入参从哪来

- `orgCode`：编辑页地址栏 `region`。接口自动化直接传机构编码。前端只对四个演示名称做了映射（五里店街道 → `ORG_110106008` 等），真实编码原样传递。测试环境用辖区接口返回的 `value`，不要写死演示编码。
- `tabCode`：`scenes` 返回的 `id`，也是地址栏 `reportTab`。截图里的「推荐主题」不是页签，是第 3 个接口的胶囊。

`GET current` 在没有定时稿时会现场生成一版。第一条 current 可能较慢，并产生一条速报记录。

### 2.4 前端有一条路径不调用生成接口

同时满足下面四条时，点「生成内容」**不会**请求 `ai-generate`，直接采用第 3 个接口里该主题的 `suggestion`：

1. 选中了一个推荐主题（`metricId` 非空）
2. 文风是正式公文（`formal`）
3. 篇幅是 50
4. 该主题还没有生成过结果，且不是「重新生成」

UI 自动化对「点主题 + 50 字 + 正式公文 + 第一次生成」应断言：**没有** `ai-generate` 请求，结果正文等于 `metrics[].suggestion`。  
接口自动化若直接 POST `ai-generate`（即使也是 formal + 50 + metricId），服务端仍会调模型。两条不要混成同一个断言。

「重新生成 / 换一换」：上一次结果来自大模型（页面标记 `source=ai`）时，前端把该段纯文本放进 `draftText` 再调生成接口，这是改写。上一次是本地直出时，`draftText` 为空，走全新生成。

采纳不调接口。生成结果追加到草稿末尾。只有 `complete` 写库。

自定义篇幅：页面只允许正整数，上限 1000。服务端只把空或 `<= 0` 改成 50，不拦 1000 以上。UI 用例按 1000 封顶，接口用例可另测 0 和负数被抬成 50。

---

## 3. 接口明细

### 0. 换票

`POST /oauth/auth/login`

这是统一认证，不走 `/jcfn/biz`。测试环境完整地址：`http://172.25.181.83/oauth/auth/login`。

请求头：

```http
Authorization: Basic {base64(客户端ID:客户端密钥)}
Content-Type: application/json
```

测试环境客户端 ID 是 `grassroots-dashboard`，密钥用该环境前端构建配置，不要写进用例仓库。`appName` 用 `grassroots-dashboard`（与客户端 ID 在测试环境碰巧相同，别的环境不一定相同）。

uid 联调（接口自动化推荐，不依赖京办 App）：

```json
{
  "loginWay": "uid",
  "scope": "openid profile",
  "endpoint": "h5",
  "appName": "grassroots-dashboard",
  "data": { "uid": "平台用户uid" }
}
```

可用 uid 见《测试环境速查》：街道领导、社区领导各一个。街道和社区看到的胶囊主体层级不同（街道 3、社区 4），建议两套账号都留。

京办免登是同一地址，`loginWay` 改为 `jingban`，`data` 改为 `{ "code": "京办免登码" }`。

成功 `data`（换票响应若本身没有套 `status/data`，按统一认证原文读顶层字段）：

| 字段 | 说明 |
| --- | --- |
| access_token | 访问令牌 |
| token_type | 一般为 `Bearer` |
| expires_in | 秒 |
| refresh_token | 刷新用。本模块用例不必测刷新 |

后续业务头：`Authorization: {token_type} {access_token}`。

---

### 1. 速报页签列表

`GET /api/v1/mobile/brief-report/scenes`

无查询参数。返回当前租户已启用页签。

`data`：数组。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 页签编码，后面所有接口的 `tabCode` |
| label | string | 页签名称，编辑页顶上的分类 |

```json
{
  "status": "200",
  "data": [
    { "id": "DAILY_COMP", "label": "综合底数" }
  ]
}
```

断言：数组非空；记下第一条或用例指定页签的 `id`。空数组表示该租户没启用页签，后面接口没有合法 `tabCode`。

---

### 2. 读取当前速报

`GET /api/v1/mobile/brief-report/current`

| 查询参数 | 必填 | 说明 |
| --- | --- | --- |
| orgCode | 是 | 机构编码 |
| tabCode | 是 | 页签编码 |
| statDate | 否 | `yyyy-MM-dd`。空则服务端自己解析截止日（一般为 T+1 口径的昨天） |

`data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 记录 ID。`complete.basedReportId` 用它，按数字传，不要加引号进 SQL，JSON 里是字符串以免精度丢失 |
| document | string | 正文，ProseMirror JSON **字符串**，要再 `JSON.parse` |
| statisticsDate | string | 数据截止日 `yyyy-MM-dd`。保存时原样回传 |
| effectiveDate | string | 服务端当天日期 |
| revision | number | 乐观锁。保存必须原样回传 |
| displayed | boolean | 是否默认显示主题 |
| versionNo | number | 业务版本号。用户每完成一次编辑 +1 |
| reportKind | string | `SCHEDULED_GEN` 定时稿，`USER_EDIT` 用户编辑稿 |
| reportTitle | string | 标题。截图顶部那一行 |
| originalDocument | string | 初始定时稿 JSON 字符串，恢复原文用 |
| unverifiedCount | number | 正文里「【待核实】」个数 |
| handModifiedCount | number | 手改数字个数 |
| dataChanges | array | 相对保存快照的底数变动。无变动为 `[]` |
| dataChanges[].id | string | 指标占位符 |
| dataChanges[].label | string | 显示名，读取接口会加上辖区前缀 |
| dataChanges[].before | string | 快照值（含单位） |
| dataChanges[].after | string | 最新值（含单位） |
| templateId | string | 模板 ID。订阅查询用。可能为 null |

断言：`id`、`revision`、`statisticsDate`、`document` 都有值。把 `id`、`revision`、`statisticsDate`、`document` 存下来给第 5 步。

---

### 3. 推荐主题（要点胶囊）

`GET /api/v1/mobile/brief-report/metrics?orgCode={orgCode}&tabCode={tabCode}`

弹层打开时页面用进入编辑页时已经拿到的这份列表，不会为了打开弹层再请求一次。接口自动化在生成前单独打这一下，用来拿 `metricId` 和本地直出对照文本。

`data`：数组，顺序即弹层「推荐主题」从左到右、从上到下。截图中的「社区人口与户数」「人户分离台账」等是配置出来的胶囊标题，不是写死的五个名字。没配过该页签+该主体时，回退内置目录（标题会变成「人口基本盘」这类）。配过但全部停用则返回 `[]`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 胶囊编码。生成入参 `metricId` |
| label | string | 主题标题，对应按钮文案 |
| referenceText | string | 已填数纯文本。生成时作为「辖区真实底数」塞进提示词 |
| suggestion | string | 已填数段落，ProseMirror JSON **字符串**。正式公文 + 50 字 + 首次生成时，页面直接用它，不调模型 |

填数规则：占位符能取到数则显示「数值+单位」；取不到是「【待核实】」，不会编一个数。统计日是服务端昨天。

断言：

- 记录每条 `id`、`label`。
- `referenceText` 非空（允许含「【待核实】」）。
- `suggestion` 能解析成 `{ "type": "doc", "content": [ ... ] }`。
- 若本环境应有截图那组主题，断言 `label` 集合包含预期标题；标题以环境配置为准，不要把截图五条写死成唯一正确集。

---

### 4. AI 帮写生成

`POST /api/v1/mobile/brief-report/ai-generate`

`Content-Type: application/json`

请求体（与前端实际提交一致；`promptCode` 前端不传，调试可以传）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| orgCode | string | 建议填 | 辖区机构编码。用来解析辖区名、主体层级、取数 |
| tabCode | string | 建议填 | 页签编码。用来解析主题名和主模板上的提示词 |
| requirement | string | 自由写时需要 | 写作要求纯文本。选了主题时，页面把主题引用展开成的文字也放这里 |
| metricId | string | 否 | 胶囊 `id`。空字符串表示自由写作。空或对不上时，数据上下文用该页签第一个胶囊的 `referenceText` |
| targetLength | number | 建议填 | 目标字数。50 / 100 / 200 或自定义正整数。null 或 ≤0 时服务端按 50 |
| style | string | 建议填 | `formal` 正式公文，`brief` 精炼简报，`plain` 通俗通报。空或未知按 `formal` |
| promptCode | string | 否 | 空则走「该页签+该主体的主模板绑定编码」，再没有则 `brief_ai_generate`。精炼简报先试 `{编码}_brief`，通俗通报先试 `{编码}_plain`，没有再退回绑定编码 |
| draftText | string | 否 | 当前底稿纯文本。有内容就是改写：只许改句式和篇幅，提示词会追加「严禁改数字」。空就是全新生成 |

页面实际提交示例（选中主题、100 字、精炼简报、无底稿）：

```json
{
  "orgCode": "从第2步同一辖区",
  "tabCode": "从第1步",
  "requirement": "社区人口与户数相关的写作要求纯文本",
  "metricId": "从第3步该主题的 id",
  "targetLength": 100,
  "style": "brief",
  "draftText": ""
}
```

改写示例：`draftText` 为上一轮结果的纯文本，其余字段保持用户当前选择。

`data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | `ai-` 加 UUID。每次成功都是新的 |
| document | string | 生成段落，ProseMirror JSON **字符串** |
| targetLength | number | 回传请求里的目标字数（请求 ≤0 或 null 时，回传的仍是原值，服务端内部按 50 写提示词） |
| traceId | string | 本次模型调用的链路号，给第 9 步 |

`document` 解析后的形状：

```json
{
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        { "type": "text", "text": "辖区总人口" },
        {
          "type": "text",
          "text": "8016人",
          "marks": [{ "type": "reportMetric" }]
        }
      ]
    }
  ]
}
```

服务端按行切段，空行丢掉。数字加单位（人、户、套、%，允许千分位和小数）会带 `reportMetric` 标记。

断言：

- HTTP 200 且 `status` 为 `"200"`。
- `data.id` 以 `ai-` 开头。
- `data.traceId` 非空。
- `data.targetLength` 等于请求值（请求是 50/100/200 时）。
- `JSON.parse(data.document)` 后 `type === "doc"`，至少一段非空文本。
- 改写用例：底稿里的原始数字仍出现在新正文里（红线是提示词约束，模型偶发改数字时应记缺陷，不要把「数字绝对不变」写成不稳定的硬失败，除非产品要求卡死；至少要人工或抽检能对上 `traceId`）。
- 负面：`brief.ai.enabled={"enabled":false}` 时期望 HTTP 403，`detail` 含「AI帮写未开启」。测完把开关打开。
- 负面：模型编码配空且 yml 也空时 HTTP 503。测试环境默认 yml 有 `Qwen3.8-27B-Capinfo`，不要为了测 503 去清生产配置。

超时：这是同步调模型，脚本超时建议 ≥ 60 秒。失败是 502「生成失败，请重试」，没有轮询接口。

---

### 5. 完成编辑保存

`POST /api/v1/mobile/brief-report/complete`

采纳本身无接口。要证明「生成内容进了正文」，把第 2 步的 `document` 与第 4 步的 `document` 在客户端拼成一篇（页面是追加到文末），再调用本接口。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| basedReportId | number | 是 | 第 2 步 `id` 转成数字 |
| expectedRevision | number | 是 | 第 2 步 `revision`。不一致则 409 |
| clientRequestId | string | 强烈建议 | 幂等键。同一租户重复提交返回已存在的那条，不会再加版本。每次新保存换新键 |
| orgCode | string | 是 | 与 current 相同 |
| orgName | string | 建议 | 辖区名称。页面用地址栏 `regionLabel` |
| tabCode | string | 是 | 与 current 相同 |
| statDate | string | 建议 | 第 2 步 `statisticsDate`。空则服务端再解析 |
| reportTitle | string | 否 | 空则沿用原标题 |
| documentJson | string | 是 | 采纳后的全文，ProseMirror JSON 字符串 |
| plainText | string | 是 | 全文纯文本。空白时服务端丢弃本次正文，回退成原定时稿 |
| operationsJson | string | 否 | 操作轨迹。页面当前不传 |

```json
{
  "basedReportId": 123456789012345,
  "expectedRevision": 1,
  "clientRequestId": "auto-ai-write-20261119-001",
  "orgCode": "与 current 相同",
  "orgName": "测试社区",
  "tabCode": "与 current 相同",
  "statDate": "2026-11-18",
  "documentJson": "{\"type\":\"doc\",\"content\":[...]}",
  "plainText": "原正文……\n生成出来的段落……"
}
```

`data` 与第 2 步同一结构。关注：

| 字段 | 期望 |
| --- | --- |
| id | 新 ID，不等于 basedReportId |
| reportKind | `USER_EDIT` |
| versionNo | 比保存前大 1 |
| revision | 新纪录自己的修订号 |
| document | 与提交的 `documentJson` 一致（读取接口有时会按最新指标刷新正文里的数；若刷新导致不完全相等，再读 `plainText` 是否包含生成段落里的非数字句子） |

同一 `clientRequestId` 再 POST 一次：返回第一次那条，`versionNo` 不再增加。

---

### 6. 保存后再读

再调第 2 步 `GET current`，同一 `orgCode`、`tabCode`。

断言：`reportKind` 为 `USER_EDIT`，`versionNo` 为刚保存的版本，正文能找到本次生成段落里一句不含数字的原句（数字可能被「打开时刷新指标」改掉）。

---

### 7. 语音转写（弹层写作要求）

`POST /api/v1/mobile/brief-report/voice-transcribe`

`Content-Type: multipart/form-data`。不要手写 boundary 错误的 JSON。

| 表单字段 | 必填 | 说明 |
| --- | --- | --- |
| file | 是 | 录音文件。页面文件名 `voice.wav`。空文件 HTTP 400「录音文件为空」 |
| orgCode | 是 | 当前辖区。页面取 context 的 region，映射规则与速报相同 |
| sceneCode | 是 | 页面传的是页签 `tabCode`，不是固定词 |

`data`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| transcribeSessionId | string | UUID。不落速报库 |
| recognizedText | string | 识别原文 |
| formattedText | string | 当前与 recognizedText 相同。页面只用这个字段插入写作要求 |

断言：`formattedText` 去空白后非空。识别文本进入写作要求后，再走第 4 步，此时 `requirement` 应包含这段文字。语音失败不影响已经生成的段落。

开关关闭时期望 HTTP 403「语音输入未开启」。编辑页在 `brief.voice.enabled` 缺失时默认显示语音按钮；只有配置存在且 `enabled: false` 才隐藏。

---

### 8. 系统配置（开关预检）

`GET /api/v1/mobile/system-config?keys=brief.ai.enabled,brief.ai.model-code,brief.voice.enabled,brief.voice.model-code`

`keys` 逗号分隔，最多 50 个。不存在或已停用的 key **不出现**在数组里，前端当默认值：AI 开、语音开。

`data[]`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| key | string | 配置项 |
| value | object | JSON 原样 |

值的形状：

| key | value 示例 | 缺省 |
| --- | --- | --- |
| brief.ai.enabled | `{ "enabled": true }` | 当开启 |
| brief.ai.model-code | `{ "modelCode": "Qwen3.8-27B-Capinfo" }` | 空白则用 yml `bi.brief.ai.model-code` |
| brief.voice.enabled | `{ "enabled": true }` | 当开启。编辑页只拉这一项 |
| brief.voice.model-code | `{ "modelCode": "..." }` | 空白则用 yml |

用例开始时先打这一下：`brief.ai.enabled` 未返回或 `enabled` 不是 false，才继续第 4 步。否则生成必 403，不应算模型故障。

---

### 9. 按 traceId 查网关日志

`GET /api/v1/modelgateway/runtime/logs/trace/{traceId}`

`traceId` 用第 4 步返回值。同一请求头。

`data`：日志数组（可能短暂为空，生成返回后立刻查建议重试 2～3 次，间隔 1 秒）。命中后取第一条的 `logId`。

关注字段：

| 字段 | AI 帮写期望 |
| --- | --- |
| traceId | 与生成出参一致 |
| sceneCode | `brief_ai_generate` |
| modelType | `LLM` |
| status | `SUCCESS` |
| promptCode | 正式公文为绑定编码或 `brief_ai_generate`；精炼简报可能是 `{编码}_brief`；通俗通报可能是 `{编码}_plain` |
| logId | 给详情接口 |

语音日志的 `sceneCode` 是上传时的 `sceneCode`（页签编码），`modelType` 为 `ASR`，用途在库里是 `VOICE_TRANSCRIBE`。列表接口不返回发给模型的正文。

---

### 10. 日志详情

`GET /api/v1/modelgateway/runtime/logs/detail/{logId}`

`data.promptPayload` 为发给模型的内容（LLM 是 messages 全文）。可断言其中包含：辖区名或机构编码、页签名、`referenceText` 里的一句底数、`style` 对应文风名（正式公文 / 精炼简报 / 通俗通报）、目标字数。改写时还应包含「待改写底稿」和「严禁修改」。

没有日志详情也能完成功能测试；这条用来区分「接口 200」和「提示词没带上底数」。

---

### 11. 页面加载附带接口（UI 自动化）

#### 系统模板列表

`GET /api/v1/mobile/brief-templates/system?subjectLevel={3或4}&orgCode={orgCode}`

| 查询参数 | 说明 |
| --- | --- |
| subjectLevel | 街道 3，社区 4。对不上辖区时生成逻辑按 3 |
| orgCode | 机构编码 |

`data[]`：`id`、`type`（页签名称）、`label`、`description`、`document`（已填数 ProseMirror JSON 字符串）、`subscription`（未订阅为 null）。

AI 弹层不读这个列表。进编辑页失败时先看它是不是 401/500。

#### 订阅状态

`GET /api/v1/mobile/brief-report/subscription?orgCode=&tabCode=&templateId=`

`templateId` 用 current 的 `templateId`。无模板时页面不调用。

`data`：`enabled`、`frequency`（`workday` / `daily` / `weekly` / `monthly`）、`sendTime`、`timeMode`（`preset` / `custom`）、`nextPushTime`、`jingbanBound`。

与 AI 帮写无关。失败时页面按未订阅处理，不挡住生成。

#### 横幅（只在列表页、且 URL 没有 reportTab）

`GET /api/v1/mobile/brief-report/banner-summary?orgCode={orgCode}`

`data.sceneCode` 是默认页签编码，`data.summary` 是摘要。编辑页如果 URL 已带 `reportTab`，不会打这个接口。

#### 辖区树（没有 orgCode 时）

`GET /api/bi/data/reader/boards`

`data[]` 里拿一个已发布看板的 `id`。

`GET /api/bi/data/reader/boards/{id}/regions`

`data.options[]`：`value` 机构编码，`label` 名称，`levelName` 层级名，`children` 下级。街道、社区的 `value` 才能作为 `orgCode`。`data.month` 是月份。

---

## 4. 推荐脚本顺序

1. uid 换票，保存 `Authorization`。
2. `system-config` 预检 AI 开关与模型编码。
3. `scenes` 取 `tabCode`。没有 orgCode 则 `reader/boards` → `regions`。
4. `current` 保存 `id`、`revision`、`statisticsDate`、原文 `document`。
5. `metrics` 保存主题列表。
6. 按第 6 节矩阵调用 `ai-generate`。每条成功都解析 `document`，并抽一条用 `traceId` 查日志。
7. 选一条生成结果，拼进原文，`complete`（新的 `clientRequestId`）。
8. 再 `current`，断言新版本正文。
9. 用同一 `clientRequestId` 再 `complete` 一次，断言版本号不变。
10. 语音用例单独：上传样例 wav → `formattedText` 非空 → 把文本放进 `requirement` 再生成一次。

不要在断言失败时反复用同一个 `clientRequestId` 重试保存，否则会一直读到第一次的结果。

---

## 5. 页面操作和接口的对照

| 用户操作 | 实际请求 |
| --- | --- |
| 进入编辑页 | `scenes` + `current` + `metrics` + `brief-templates/system` + 可能的 `subscription` + `system-config?keys=brief.voice.enabled` |
| 打开 AI 帮写 | 无。主题用第 3 步缓存 |
| 点一个推荐主题 | 无。只把该胶囊插进写作要求 |
| 50 字 + 正式公文 + 已选主题 + 第一次生成 | 无。用 `suggestion` |
| 100/200/自定义，或精炼简报/通俗通报，或未选主题，或对该主题再生成 | `POST ai-generate`，`draftText` 为空 |
| 对「大模型结果」点重新生成 | `POST ai-generate`，`draftText` 为上一段纯文本 |
| 弹层里按住说话 | `POST voice-transcribe`，文本追加到写作要求，不直接生成 |
| 点采纳 | 无。草稿末尾追加 `document` |
| 编辑页完成 | `POST complete` |

---

## 6. 生成接口用例矩阵

每行都是一次 `POST ai-generate`。`orgCode`、`tabCode` 固定用第 2 步同一对。

| 编号 | style | targetLength | metricId | draftText | requirement | 期望 |
| --- | --- | --- | --- | --- | --- | --- |
| G1 | formal | 50 | 第一条胶囊 id | 空 | 该主题 referenceText 或标题 | 200，document 可解析，trace 场景 `brief_ai_generate` |
| G2 | formal | 100 | 同上 | 空 | 同一要求 | 200，`targetLength=100` |
| G3 | formal | 200 | 同上 | 空 | 同一要求 | 200 |
| G4 | brief | 100 | 同上 | 空 | 同一要求 | 200。日志 `promptCode` 可能带 `_brief` |
| G5 | plain | 100 | 同上 | 空 | 同一要求 | 200。日志 `promptCode` 可能带 `_plain` |
| G6 | formal | 80 | 同上 | 空 | 同一要求 | 自定义篇幅。200，`targetLength=80` |
| G7 | formal | 100 | `""` | 空 | 一段不选主题的要求，例如「写一段人口概况」 | 自由写作。200。数据上下文仍会带上第一个胶囊的底数 |
| G8 | brief | 100 | 同上 | G4 返回正文的纯文本 | 与 G4 相同 | 改写。200，`draftText` 中的数字尽量仍在新正文里 |
| G9 | formal | 0 | 同上 | 空 | 任意 | 服务端按 50 字写提示词。HTTP 仍 200 |
| G10 | 不传或 `unknown` | 50 | 同上 | 空 | 任意 | 按正式公文。200 |
| N1 | formal | 50 | 任意 | 空 | 任意 | 先把 `brief.ai.enabled` 设为 false。HTTP 403 |
| N2 | — | — | — | — | — | 不带 Authorization。HTTP 401 |

G1 在 **UI** 上第一次点击不会发请求，见第 2.4 节。接口矩阵里的 G1 是直接打 API，应当 200。

UI 另补两条：

| 编号 | 操作 | 期望 |
| --- | --- | --- |
| U1 | 选主题、50 字、正式公文、第一次点生成 | 无 `ai-generate`；展示文本等于该主题 `suggestion` 的纯文本 |
| U2 | 在 U1 结果上点重新生成 | 出现 `ai-generate`，且 `draftText` 为空（本地直出不做改写原料） |

---

## 7. 环境前提（不写进脚本主流程）

生成要成功，环境里需要同时有：

- 该用户能登录，且 `brief.ai.enabled` 未关闭。
- 模型编码能在模型网关解析（配置 `brief.ai.model-code`，或 yml `bi.brief.ai.model-code`）。
- 该 `orgCode` 在辖区清单里，否则辖区名会退回编码本身，生成仍会继续。
- 页签已启用。主模板若绑了提示词编码，文风路由以它为基准。
- 要点胶囊按页签 + 主体层级配好，推荐主题才和截图一致；取数依赖 ADS，缺数显示「【待核实】」，生成接口不会因此失败。

语音另要 `brief.voice.enabled` 未关闭，以及 ASR 模型编码。
