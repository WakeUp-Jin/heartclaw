# PineClaw 飞书工具封装设计

> 本文档详细定义所有飞书 API 封装为 Agent 工具的设计方案。  
> 每个工具注册到 `ToolManager`，以 OpenAI function calling 格式提供给 LLM。  
> LLM 在推理过程中自主决定何时调用哪些工具。  
> 总体架构见 [architecture.md](architecture.md)

---

## 目录

1. [基础层：FeishuClient](#1-基础层feishuclient)
2. [IM 消息工具（3 个）](#2-im-消息工具)
3. [云文档工具（5 个）](#3-云文档工具)
4. [多维表格工具（7 个）](#4-多维表格工具)
5. [云空间工具（4 个）](#5-云空间工具)
6. [任务工具（4 个）](#6-任务工具)
7. [导出工具（1 个，第二期）](#7-导出工具)
8. [权限清单](#8-权限清单)
9. [工具注册与 ToolManager 集成](#9-工具注册与-toolmanager-集成)
10. [工具总览表](#10-工具总览表)

---

## 1. 基础层：FeishuClient

**文件**: `core/tool/feishu/client.py`

所有飞书工具共享一个 `FeishuClient` 实例，职责：

| 职责 | 说明 |
|------|------|
| Token 管理 | 自动获取和刷新 `tenant_access_token`，使用 lark-oapi 内置能力 |
| 请求封装 | 统一 HTTP 请求，自动携带 Authorization header |
| 错误处理 | 解析飞书 API 错误码（code != 0），转换为可读错误信息返回给 LLM |
| API 调用计数 | 每次调用自增计数器，供 Token 统计模块消费 |

```python
import lark_oapi as lark

class FeishuClient:
    def __init__(self, app_id: str, app_secret: str):
        self.client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .build()
        self.api_call_count = 0

    async def request(self, method, path, **kwargs) -> dict:
        self.api_call_count += 1
        # ... lark-oapi SDK 调用
        # 错误码检查：if resp.code != 0: return error message

    def reset_api_count(self) -> int:
        count = self.api_call_count
        self.api_call_count = 0
        return count
```

---

## 2. IM 消息工具

**文件**: `core/tool/feishu/message.py`

核心入口交互：用户 -> 飞书机器人 -> Agent 处理 -> 机器人回复。

### 2.1 `feishu_send_message`

向飞书用户或群组发送消息。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/im/v1/messages` |
| 认证 | `tenant_access_token` |
| 频率限制 | 单聊 5 QPS，群组 5 QPS |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| receive_id | string | 是 | 接收者 ID |
| receive_id_type | enum | 是 | `open_id` / `user_id` / `union_id` / `email` / `chat_id` |
| msg_type | enum | 是 | `text` / `post` / `interactive` |
| content | string | 是 | 消息内容，JSON 字符串 |

**返回**: message_id

---

### 2.2 `feishu_reply_message`

回复指定的一条消息（产生引用效果）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/im/v1/messages/{message_id}/reply` |
| 认证 | `tenant_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| message_id | string | 是 | 要回复的消息 ID |
| msg_type | enum | 是 | `text` / `post` / `interactive` |
| content | string | 是 | 回复内容，JSON 字符串 |

**返回**: message_id

---

### 2.3 `feishu_get_message_history`

获取指定会话的历史消息列表。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/im/v1/messages` |
| 认证 | `tenant_access_token` |
| 分页 | 支持，每页最多 50 条 |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| container_id | string | 是 | 会话 ID（chat_id） |
| start_time | string | 否 | 起始时间戳（秒） |
| end_time | string | 否 | 结束时间戳（秒） |
| page_size | integer | 否 | 每页数量，默认 20，最大 50 |

**返回**: 消息列表（sender、content、create_time）

---

## 3. 云文档工具

**文件**: `core/tool/feishu/doc.py`

操作飞书新版文档（docx 格式），提供创建、读取、修改能力。

### 3.1 `feishu_create_document`

在指定文件夹下创建新的飞书文档。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/docx/v1/documents` |
| 认证 | `tenant_access_token` / `user_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| title | string | 是 | 文档标题 |
| folder_token | string | 否 | 目标文件夹 token，留空为根目录 |

**返回**: document_id, title, url（飞书文档链接）

---

### 3.2 `feishu_read_document`

获取文档的纯文本内容（适合 Agent 快速理解文档）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/docx/v1/documents/{document_id}/raw_content` |
| 认证 | `tenant_access_token` / `user_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| document_id | string | 是 | 文档 ID |

**返回**: 纯文本内容字符串

---

### 3.3 `feishu_read_document_blocks`

获取文档的完整块结构（保留格式信息，比纯文本更详细）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/docx/v1/documents/{document_id}/blocks` |
| 认证 | `tenant_access_token` / `user_access_token` |
| 分页 | 支持，每页最多 500 个块 |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| document_id | string | 是 | 文档 ID |
| page_size | integer | 否 | 每页块数量，默认 500 |

**返回**: blocks 列表（block_id, block_type, content）

---

### 3.4 `feishu_update_document`

向文档中追加内容块（段落、标题、列表等）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children` |
| 认证 | `tenant_access_token` / `user_access_token` |
| 频率限制 | 3 QPS |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| document_id | string | 是 | 文档 ID |
| block_id | string | 是 | 父块 ID（传 document_id 表示追加到末尾） |
| content_blocks | array | 是 | 内容块数组 |

每个 `content_block` 的结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| block_type | enum | `paragraph` / `heading1` / `heading2` / `heading3` / `code` / `bullet` / `ordered` |
| content | string | 块的文本内容 |

**实现说明**: 工具内部将简化的 `content_blocks` 转换为飞书 API 要求的 Block 数据结构（TextRun、TextElement 等嵌套结构），对 LLM 暴露简化接口。

---

### 3.5 `feishu_get_document_info`

获取文档的基本信息。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/docx/v1/documents/{document_id}` |
| 认证 | `tenant_access_token` / `user_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| document_id | string | 是 | 文档 ID |

**返回**: title, create_time, update_time, owner

---

## 4. 多维表格工具

**文件**: `core/tool/feishu/bitable.py`

飞书中结构化数据的核心载体。关键概念：

```
多维表格 App (app_token)
  └── 数据表 Table (table_id)
        ├── 字段 Field（列定义：名称 + 类型）
        └── 记录 Record（行数据：record_id + fields）
```

### 4.1 `feishu_create_bitable`

创建一个新的多维表格。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/bitable/v1/apps` |
| 认证 | `tenant_access_token` / `user_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | 多维表格名称 |
| folder_token | string | 否 | 目标文件夹 token |

**返回**: app_token, url

---

### 4.2 `feishu_create_bitable_table`

在多维表格中创建数据表，同时定义字段结构。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/bitable/v1/apps/{app_token}/tables` |
| 认证 | `tenant_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| app_token | string | 是 | 多维表格 app_token |
| name | string | 是 | 数据表名称 |
| fields | array | 是 | 字段定义列表 |

字段类型映射表：

| type 值 | 类型名称 | 说明 |
|---------|---------|------|
| 1 | 文本 | 单行/多行文本 |
| 2 | 数字 | 整数或小数 |
| 3 | 单选 | 下拉单选 |
| 4 | 多选 | 下拉多选 |
| 5 | 日期 | 日期时间 |
| 7 | 复选框 | 布尔值 |
| 11 | 人员 | 飞书用户 |
| 13 | 电话 | 电话号码 |
| 15 | 超链接 | URL |
| 17 | 附件 | 文件附件 |
| 1001 | 创建时间 | 自动填写 |
| 1002 | 修改时间 | 自动填写 |

**返回**: table_id

---

### 4.3 `feishu_list_bitable_records`

查询数据表记录（支持筛选、排序、分页）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records` |
| 认证 | `tenant_access_token` |
| 分页 | 支持，每页最多 500 条 |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| app_token | string | 是 | 多维表格 app_token |
| table_id | string | 是 | 数据表 ID |
| filter | string | 否 | 筛选条件，如 `AND(CurrentValue.[状态]="进行中")` |
| sort | string | 否 | 排序条件 JSON 字符串 |
| page_size | integer | 否 | 每页数量，默认 20，最大 500 |
| page_token | string | 否 | 分页标记 |

**返回**: records 列表（record_id + fields），has_more, page_token

---

### 4.4 `feishu_create_bitable_records`

向数据表批量新增记录。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create` |
| 认证 | `tenant_access_token` |
| 限制 | 单次最多 500 条，10 QPS |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| app_token | string | 是 | 多维表格 app_token |
| table_id | string | 是 | 数据表 ID |
| records | array | 是 | 记录列表，每条 `{"fields": {"字段名": "值"}}` |

**返回**: 创建的 record_id 列表

---

### 4.5 `feishu_update_bitable_record`

更新一条记录。

| 属性 | 值 |
|------|-----|
| 飞书 API | `PUT /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}` |
| 认证 | `tenant_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| app_token | string | 是 | 多维表格 app_token |
| table_id | string | 是 | 数据表 ID |
| record_id | string | 是 | 记录 ID |
| fields | object | 是 | 要更新的字段名到值的映射 |

**返回**: 更新后的 record

---

### 4.6 `feishu_delete_bitable_records`

批量删除记录。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete` |
| 认证 | `tenant_access_token` |
| 限制 | 单次最多 500 条 |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| app_token | string | 是 | 多维表格 app_token |
| table_id | string | 是 | 数据表 ID |
| record_ids | array[string] | 是 | 要删除的记录 ID 列表 |

**返回**: 删除成功/失败的 ID 列表

---

### 4.7 `feishu_list_bitable_fields`

列出数据表的所有字段定义（有哪些列、每列什么类型）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields` |
| 认证 | `tenant_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| app_token | string | 是 | 多维表格 app_token |
| table_id | string | 是 | 数据表 ID |

**返回**: fields 列表（field_id, field_name, type）

---

## 5. 云空间工具

**文件**: `core/tool/feishu/drive.py`

让 Agent 像操作本地文件系统一样浏览飞书云空间。

### 5.1 `feishu_list_files`

列出指定文件夹下的所有文件和子文件夹（类似 `ls`）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/drive/v1/files` |
| 认证 | `tenant_access_token` / `user_access_token` |
| 分页 | 支持，每页最多 200 条 |
| 限制 | 文件夹单层节点上限 1500 个 |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| folder_token | string | 否 | 文件夹 token，留空表示根目录 |
| page_size | integer | 否 | 每页数量，默认 50，最大 200 |
| page_token | string | 否 | 分页标记 |

**返回格式化**（对 LLM 友好的输出格式）：

```
📁 项目文档/          (folder)   token: fldcnXXX
📄 需求说明.docx      (docx)     token: doxcnYYY
📊 数据统计.sheet     (sheet)    token: shtcnZZZ
📋 任务看板.bitable   (bitable)  token: bascnAAA
```

---

### 5.2 `feishu_create_folder`

在指定位置创建新文件夹。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/drive/v1/files/create_folder` |
| 认证 | `tenant_access_token` / `user_access_token` |
| 限制 | 不支持对同一文件夹并发操作 |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | 文件夹名称 |
| folder_token | string | 否 | 父文件夹 token，留空为根目录 |

**返回**: folder_token, url

---

### 5.3 `feishu_get_file_info`

获取单个文件/文件夹的详细信息。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/drive/v1/files/{file_token}` |
| 认证 | `tenant_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| file_token | string | 是 | 文件或文件夹的 token |

**返回**: name, type, size, create_time, modified_time, owner

---

### 5.4 `feishu_get_root_folder`

获取云空间根目录 token（浏览云空间的起点）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/drive/explorer/v2/root_folder/meta` |
| 认证 | `tenant_access_token` |

**参数**: 无

**返回**: root_folder_token

---

## 6. 任务工具

**文件**: `core/tool/feishu/task.py`

操作飞书任务系统（Task v2），用于任务看板管理。

### 6.1 `feishu_create_task`

创建飞书任务。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/task/v2/tasks` |
| 认证 | `tenant_access_token` / `user_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| summary | string | 是 | 任务标题 |
| description | string | 否 | 任务详细描述 |
| due | string | 否 | 截止时间，ISO 8601 格式 |
| members | array[string] | 否 | 执行者 user_id 列表 |
| tasklist_id | string | 否 | 添加到指定任务列表 |

**返回**: task_id

---

### 6.2 `feishu_list_tasks`

查询任务列表。

| 属性 | 值 |
|------|-----|
| 飞书 API | `GET /open-apis/task/v2/tasks` |
| 认证 | `tenant_access_token` / `user_access_token` |
| 分页 | 支持 |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| completed | boolean | 否 | 筛选完成(true)/未完成(false) |
| page_size | integer | 否 | 每页数量，默认 50 |
| page_token | string | 否 | 分页标记 |

**返回**: tasks 列表（task_id, summary, due, completed）

---

### 6.3 `feishu_update_task`

更新任务信息。

| 属性 | 值 |
|------|-----|
| 飞书 API | `PATCH /open-apis/task/v2/tasks/{task_id}` |
| 认证 | `tenant_access_token` / `user_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| task_id | string | 是 | 任务 ID |
| summary | string | 否 | 新标题 |
| description | string | 否 | 新描述 |
| due | string | 否 | 新截止时间 |
| completed | boolean | 否 | 是否标记已完成 |

**返回**: 更新后的 task

---

### 6.4 `feishu_create_tasklist`

创建任务列表（任务看板/分组）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/task/v2/tasklists` |
| 认证 | `tenant_access_token` / `user_access_token` |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | 任务列表名称 |

**返回**: tasklist_id

---

## 7. 导出工具

**文件**: `core/tool/feishu/export.py`

> 第二期实现

### 7.1 `feishu_export_document`

将飞书文档导出为指定格式（异步操作，需轮询结果）。

| 属性 | 值 |
|------|-----|
| 飞书 API | `POST /open-apis/drive/v1/export_tasks` + `GET /open-apis/drive/v1/export_tasks/{ticket}` |
| 支持格式 | docx, pdf, md |

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| file_token | string | 是 | 文档的 file_token |
| type | enum | 是 | `docx` / `pdf` / `md` |

**返回**: 导出文件的下载 URL

---

## 8. 权限清单

飞书开放平台应用需要申请的权限：

### IM 消息

| 权限标识 | 说明 |
|---------|------|
| `im:message` | 获取与发送单聊、群组消息 |
| `im:message:send_as_bot` | 以应用身份发送消息 |
| `im:chat:readonly` | 获取群组信息 |
| `im:message:readonly` | 读取消息 |

### 云文档

| 权限标识 | 说明 |
|---------|------|
| `docs:doc` | 查看、评论和编辑文档 |
| `docs:doc:create` | 创建文档 |
| `docs:doc:readonly` | 查看文档 |
| `docx:document` | 读写新版文档 |
| `docx:document:readonly` | 读取新版文档 |

### 多维表格

| 权限标识 | 说明 |
|---------|------|
| `bitable:app` | 查看、评论、编辑和管理多维表格 |
| `bitable:app:readonly` | 查看多维表格 |

### 云空间

| 权限标识 | 说明 |
|---------|------|
| `drive:drive` | 查看和管理云空间中所有文件 |
| `drive:drive:readonly` | 查看云空间文件 |
| `drive:file` | 上传、下载文件 |

### 任务

| 权限标识 | 说明 |
|---------|------|
| `task:task` | 查看、创建、编辑和删除任务 |
| `task:task:readonly` | 查看任务 |

---

## 9. 工具注册与 ToolManager 集成

### 每个工具文件的内部结构

以 `doc.py` 为例，每个工具文件包含两部分——**定义**和**执行器**：

```python
# core/tool/feishu/doc.py
import json
from core.tool.feishu.client import FeishuClient

# ── 工具定义（OpenAI function calling 格式） ──

feishu_create_document_def = {
    "name": "feishu_create_document",
    "description": "在飞书云空间中创建一个新文档",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "文档标题"},
            "folder_token": {"type": "string", "description": "目标文件夹 token"},
        },
        "required": ["title"],
    },
}

# ── 工具执行器（实际调用飞书 API） ──

async def feishu_create_document_handler(client: FeishuClient, args: dict) -> str:
    title = args["title"]
    folder_token = args.get("folder_token")
    # 使用 lark-oapi SDK 创建文档
    # ...
    return json.dumps({"document_id": doc_id, "title": title, "url": url})
```

### 统一注册

`core/tool/feishu/__init__.py` 中提供 `register_feishu_tools()` 函数，将所有飞书工具一次性注册到 ToolManager：

```python
def register_feishu_tools(tool_manager: ToolManager, feishu_client: FeishuClient):
    tools = [
        # IM 消息
        (feishu_send_message_def, feishu_send_message_handler),
        (feishu_reply_message_def, feishu_reply_message_handler),
        (feishu_get_message_history_def, feishu_get_message_history_handler),
        # 云文档
        (feishu_create_document_def, feishu_create_document_handler),
        (feishu_read_document_def, feishu_read_document_handler),
        (feishu_read_document_blocks_def, feishu_read_document_blocks_handler),
        (feishu_update_document_def, feishu_update_document_handler),
        (feishu_get_document_info_def, feishu_get_document_info_handler),
        # 多维表格
        (feishu_create_bitable_def, feishu_create_bitable_handler),
        (feishu_create_bitable_table_def, feishu_create_bitable_table_handler),
        (feishu_list_bitable_records_def, feishu_list_bitable_records_handler),
        (feishu_create_bitable_records_def, feishu_create_bitable_records_handler),
        (feishu_update_bitable_record_def, feishu_update_bitable_record_handler),
        (feishu_delete_bitable_records_def, feishu_delete_bitable_records_handler),
        (feishu_list_bitable_fields_def, feishu_list_bitable_fields_handler),
        # 云空间
        (feishu_list_files_def, feishu_list_files_handler),
        (feishu_create_folder_def, feishu_create_folder_handler),
        (feishu_get_file_info_def, feishu_get_file_info_handler),
        (feishu_get_root_folder_def, feishu_get_root_folder_handler),
        # 任务
        (feishu_create_task_def, feishu_create_task_handler),
        (feishu_list_tasks_def, feishu_list_tasks_handler),
        (feishu_update_task_def, feishu_update_task_handler),
        (feishu_create_tasklist_def, feishu_create_tasklist_handler),
    ]

    for definition, handler in tools:
        tool_manager.register(
            name=definition["name"],
            definition=definition,
            handler=lambda args, h=handler: h(feishu_client, args),
            category="feishu",
        )
```

---

## 10. 工具总览表

| # | 工具名 | 分类 | 飞书 API | 开发期 |
|---|--------|------|---------|--------|
| 1 | `feishu_send_message` | IM 消息 | `POST /im/v1/messages` | 第一期 |
| 2 | `feishu_reply_message` | IM 消息 | `POST /im/v1/messages/{id}/reply` | 第一期 |
| 3 | `feishu_get_message_history` | IM 消息 | `GET /im/v1/messages` | 第一期 |
| 4 | `feishu_create_document` | 云文档 | `POST /docx/v1/documents` | 第一期 |
| 5 | `feishu_read_document` | 云文档 | `GET /docx/v1/documents/{id}/raw_content` | 第一期 |
| 6 | `feishu_read_document_blocks` | 云文档 | `GET /docx/v1/documents/{id}/blocks` | 第一期 |
| 7 | `feishu_update_document` | 云文档 | `POST /docx/v1/documents/{id}/blocks/{id}/children` | 第一期 |
| 8 | `feishu_get_document_info` | 云文档 | `GET /docx/v1/documents/{id}` | 第一期 |
| 9 | `feishu_create_bitable` | 多维表格 | `POST /bitable/v1/apps` | 第一期 |
| 10 | `feishu_create_bitable_table` | 多维表格 | `POST /bitable/v1/apps/{token}/tables` | 第一期 |
| 11 | `feishu_list_bitable_records` | 多维表格 | `GET /bitable/v1/apps/{token}/tables/{id}/records` | 第一期 |
| 12 | `feishu_create_bitable_records` | 多维表格 | `POST .../records/batch_create` | 第一期 |
| 13 | `feishu_update_bitable_record` | 多维表格 | `PUT .../records/{id}` | 第一期 |
| 14 | `feishu_delete_bitable_records` | 多维表格 | `POST .../records/batch_delete` | 第一期 |
| 15 | `feishu_list_bitable_fields` | 多维表格 | `GET .../tables/{id}/fields` | 第一期 |
| 16 | `feishu_list_files` | 云空间 | `GET /drive/v1/files` | 第一期 |
| 17 | `feishu_create_folder` | 云空间 | `POST /drive/v1/files/create_folder` | 第一期 |
| 18 | `feishu_get_file_info` | 云空间 | `GET /drive/v1/files/{token}` | 第一期 |
| 19 | `feishu_get_root_folder` | 云空间 | `GET /drive/explorer/v2/root_folder/meta` | 第一期 |
| 20 | `feishu_create_task` | 任务 | `POST /task/v2/tasks` | 第一期 |
| 21 | `feishu_list_tasks` | 任务 | `GET /task/v2/tasks` | 第一期 |
| 22 | `feishu_update_task` | 任务 | `PATCH /task/v2/tasks/{id}` | 第一期 |
| 23 | `feishu_create_tasklist` | 任务 | `POST /task/v2/tasklists` | 第一期 |
| 24 | `feishu_export_document` | 导出 | `POST /drive/v1/export_tasks` | 第二期 |

**第一期**: 23 个工具 | **第二期**: 1 个工具 | **总计**: 24 个工具
