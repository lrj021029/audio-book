# 听书平台业务数据
## 业务概述
听书平台面向用户、主播、版权机构和平台运营团队提供有声内容服务，覆盖内容供给、专辑上架、音频播放、用户互动、会员权益、订单支付和运营推荐等完整业务链路。

平台覆盖的核心业务对象：

- 用户、会员账户、钱包账户、收听偏好、关注关系、收藏书架、站内消息等用户主体
- 主播、创作者、作者、版权机构、制作团队等内容供给主体
- 有声书、主播节目、播客、评书、戏曲、儿童内容、睡眠内容等音频专辑
- 音频章节、音频文件、上传任务、审核记录、试看规则、定价规则、会员权益等内容资产
- 播放记录、收听进度、评论、评分、点赞、分享、动态、反馈等行为记录
- VIP 套餐、内容订单、支付流水、退款单、充值订单、钱包流水等交易对象
- 榜单、推荐位、专题、搜索词、搜索明细等运营对象

平台核心业务能力：

- 内容供给管理：维护主播、创作者、作者、版权机构、专辑、章节、音频文件、上传任务和审核记录等主数据。
- 分类与标签管理：维护内容分类、内容标签、适听年龄、语言和版权类型等基础维度。
- 用户与会员管理：维护用户账号、画像、会员权益、钱包、关注、收藏、站内消息和收听偏好。
- 播放与互动管理：记录播放进度、播放会话、评论评分、点赞分享和举报处理。
- 交易与权益管理：支持 VIP 套餐、单本购买、章节购买、账户充值、支付、退款和权益核销。
- 运营推荐管理：维护榜单、推荐位、专题聚合、搜索明细和搜索热词。

平台主链路：

- 浏览分类或榜单
- 搜索专辑或主播
- 查看专辑详情
- 试听章节
- 开通会员或购买内容
- 连续播放章节
- 收藏、订阅、评论和评分
- 查看播放历史和书架

## 快速开始
启动 MySQL 数据库

配置数据库连接参数 [`.env`](./.env)

```bash
uv sync  # 安装依赖

uv run init_db.py  # 初始化数据库
uv run -m generate.main --profile full  # 生成数据

uv run -m app.main  # 启动服务
```

服务启动后访问 FastAPI 文档：

- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

## 数据定义
### 基础维度
本域用于维护全平台共享的内容分类、标签、渠道、语言和币种等基础主数据。

表说明：

- `dim_audio_category`：音频内容分类维表，维护有声小说、评书、戏曲、儿童、播客等分类层级。
- `dim_content_tag`：内容标签维表，维护悬疑推理、玄幻奇幻、历史幻想、都市传说等标签。
- `dim_channel`：渠道维表，维护 App、Web、小程序、车载端等访问和下单渠道。
- `dim_language`：语言维表，维护普通话、粤语、英语等音频语言。
- `dim_currency`：币种维表，维护订单支付和结算使用的币种。

依赖关系说明：

- `dim_audio_category` 通过 `parent_id` 自关联形成分类树。
- `dim_content_tag` 可通过 `parent_id` 自关联形成标签组和标签项。

#### `dim_audio_category`
音频内容分类维表，定义听书平台的频道、一级分类和二级分类。

- `id`：主键 ID。
- `parent_id`：父分类 ID，关联 `dim_audio_category.id`，顶级分类为空。
- `category_code`：分类编码，业务唯一标识。
- `category_name`：分类名称。
- `category_level`：分类层级。枚举值：
  - `1`：频道
  - `2`：一级分类
  - `3`：二级分类
- `category_type`：分类类型。枚举值：
  - `audiobook`：有声书分类
  - `program`：主播节目分类
  - `podcast`：播客分类
  - `radio`：音频电台分类
  - `course`：知识课程分类
- `sort_no`：排序号。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_dim_audio_category_code (category_code)`
- 外键约束：
  - `fk_dim_audio_category_parent (parent_id -> dim_audio_category.id)`
- 业务约束：
  - 顶级分类 `category_level = 1` 时 `parent_id` 必须为空。
  - 非顶级分类 `category_level > 1` 时 `parent_id` 必须不为空。
  - 子分类的 `category_level` 必须等于父分类的 `category_level + 1`。
  - 子分类的 `category_type` 必须与父分类的 `category_type` 一致。
  - 同一父分类下启用状态为 `yn = 1` 的 `category_name` 不允许重复。
  - 已被 `audio_album.category_id` 引用的分类不得物理删除，只能将 `yn` 置为 `0`。
  - 分类启停状态必须自上而下一致：启用分类的所有祖先分类必须均为启用状态；存在启用子分类时，父分类不得置为 `yn = 0`。
  - `sort_no` 在同一父分类下从小到大展示，允许不连续但不得为空。
  - 分类树最大深度固定为 3，禁止出现 `category_level > 3` 的记录。
  - `updated_at >= created_at`

#### `dim_content_tag`
内容标签维表，定义专辑和章节可复用的内容标签。

- `id`：主键 ID。
- `parent_id`：父标签 ID，关联 `dim_content_tag.id`，标签组为空。
- `tag_code`：标签编码，业务唯一标识。
- `tag_name`：标签名称。
- `tag_type`：标签类型。枚举值：
  - `genre`：题材
  - `style`：风格
  - `scene`：收听场景
  - `audience`：适听人群
  - `topic`：专题主题
- `sort_no`：排序号。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_dim_content_tag_code (tag_code)`
- 外键约束：
  - `fk_dim_content_tag_parent (parent_id -> dim_content_tag.id)`
- 业务约束：
  - 顶级标签组 `parent_id` 为空，标签项 `parent_id` 不为空。
  - 子标签的 `tag_type` 必须与父标签的 `tag_type` 一致。
  - 同一父标签下启用状态为 `yn = 1` 的 `tag_name` 不允许重复。
  - 已被 `album_tag_rel.tag_id` 或 `user_preference.tag_id` 引用的标签不得物理删除，只能将 `yn` 置为 `0`。
  - 存在启用子标签时，父标签不得置为 `yn = 0`。
  - 启用标签的所有祖先标签必须均为启用状态。
  - `tag_type = audience` 的标签用于适听人群，不能同时作为 `tag_type = genre` 的题材标签使用。
  - `sort_no` 在同一父标签下从小到大展示，允许不连续但不得为空。
  - `updated_at >= created_at`

#### `dim_channel`
渠道维表，定义用户访问、播放、下单和支付来源。

- `id`：主键 ID。
- `channel_code`：渠道编码，业务唯一标识。
- `channel_name`：渠道名称。
- `channel_type`：渠道类型。枚举值：
  - `app`：移动 App
  - `web`：网站
  - `mini_program`：小程序
  - `vehicle`：车载端
  - `partner`：合作渠道
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_dim_channel_code (channel_code)`
- 外键约束：
  - 无
- 业务约束：
  - 启用渠道 `yn = 1` 才能用于注册、播放、下单、支付和搜索统计。
  - 已被业务数据引用的渠道不得物理删除，只能将 `yn` 置为 `0`。
  - `channel_type = partner` 的渠道编码必须能区分合作方来源。
  - 同一 `channel_type` 下启用状态为 `yn = 1` 的 `channel_name` 不允许重复。
  - 渠道停用后只影响新增业务写入，不影响历史订单、播放和统计记录查询。
  - `updated_at >= created_at`

#### `dim_language`
语言维表，定义专辑和章节使用的语言。

- `id`：主键 ID。
- `language_code`：语言编码，业务唯一标识。
- `language_name`：语言名称。
- `sort_no`：排序号。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_dim_language_code (language_code)`
- 外键约束：
  - 无
- 业务约束：
  - 启用语言 `yn = 1` 才能被新建专辑引用。
  - 已被 `audio_album.language_id` 引用的语言不得物理删除，只能将 `yn` 置为 `0`。
  - 同一 `language_code` 只能对应一种展示名称。
  - 同一语言名称启用状态下不允许重复。
  - `sort_no` 用于前端语言筛选展示，允许不连续但不得为空。
  - `updated_at >= created_at`

#### `dim_currency`
币种维表，定义交易金额、结算金额和退款金额使用的币种。

- `id`：主键 ID。
- `currency_code`：币种代码，业务唯一标识。
- `currency_name`：币种名称。
- `symbol`：币种符号。
- `precision_scale`：金额精度位数。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_dim_currency_code (currency_code)`
- 外键约束：
  - 无
- 业务约束：
  - 启用币种 `yn = 1` 才能用于新建价格规则、订单、支付和退款。
  - 已被价格、订单、支付或退款数据引用的币种不得物理删除，只能将 `yn` 置为 `0`。
  - `precision_scale` 必须大于等于 `0`，人民币等常规法币使用 `2` 位小数。
  - 所有使用该币种的金额字段必须按照 `precision_scale` 保留小数位。
  - 同一币种代码只能对应一个币种名称和一个币种符号。
  - `updated_at >= created_at`

### 用户会员域
本域用于维护平台用户、用户画像、会员账户、关注关系、收藏书架和收听偏好。

表说明：

- `user_account`：用户账号主表，维护登录身份和基础资料。
- `user_profile`：用户画像表，维护性别、生日、地区和收听偏好。
- `member_account`：会员账户表，维护会员状态、等级、有效期和积分余额。
- `user_follow`：关注关系表，维护用户对主播、作者和机构的关注关系。
- `user_bookshelf`：用户书架表，维护收藏、订阅、追更和完播状态。
- `user_preference`：用户偏好表，维护分类、标签和播放设置。
- `user_message`：用户消息表，维护私信、系统通知、审核通知和交易通知。

依赖关系说明：

- `user_account -> user_profile`：一个用户最多对应一条画像记录。
- `user_account -> member_account`：一个用户最多对应一个会员账户。
- `user_account -> user_follow`：一个用户可关注多个主体。
- `user_account -> user_bookshelf`：一个用户可收藏或订阅多个专辑。
- `user_preference` 依赖 `user_account`，并可关联分类和标签。
- `user_account -> user_message`：一个用户可接收多条站内消息。

#### `user_account`
用户账号主表，存储昵称、手机号、邮箱、注册渠道和账号状态。

- `id`：主键 ID。
- `user_no`：用户编号，业务唯一标识。
- `nickname`：用户昵称。
- `avatar_url`：头像地址。
- `mobile`：手机号。
- `email`：邮箱。
- `register_channel_id`：注册渠道 ID，关联 `dim_channel.id`。
- `account_status`：账号状态。枚举值：
  - `normal`：正常
  - `muted`：禁言
  - `disabled`：停用
  - `cancelled`：已注销
- `last_login_at`：最后登录时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_account_no (user_no)`
  - `uk_user_account_mobile (mobile)`
  - `uk_user_account_email (email)`
- 外键约束：
  - `fk_user_account_register_channel (register_channel_id -> dim_channel.id)`
- 业务约束：
  - `register_channel_id` 必须指向启用状态 `yn = 1` 的渠道。
  - `mobile` 和 `email` 至少填写一个，用于账号找回和通知触达。
  - `mobile` 不为空时必须符合手机号格式，`email` 不为空时必须符合邮箱格式。
  - `account_status = normal` 的用户允许登录、播放、下单和互动。
  - `account_status = muted` 的用户允许登录、播放和下单，但不得新增评论、评分、举报和公开互动。
  - `account_status = disabled` 的用户不得登录、播放、下单或新增互动。
  - `account_status = cancelled` 的用户不得产生新增业务数据，历史订单、支付、播放和权益记录保留。
  - 注销账号的 `mobile`、`email` 是否释放由平台账号策略决定，同一批模拟数据内不复用。
  - `last_login_at` 只能在账号未注销时更新。
  - `updated_at >= created_at`
  - `last_login_at` 不为空时，`last_login_at >= created_at`

#### `user_profile`
用户画像表，与用户账号一对一，存储基础画像和内容偏好摘要。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `gender`：性别。枚举值：
  - `male`：男
  - `female`：女
  - `unknown`：未知
- `birthday`：生日。
- `province`：省。
- `city`：市。
- `occupation`：职业。
- `listening_scene_payload`：常用收听场景，JSON 数组格式。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_profile_user (user_id)`
- 外键约束：
  - `fk_user_profile_user (user_id -> user_account.id)`
- 业务约束：
  - 每个用户最多维护一条画像记录，画像记录必须晚于或等于账号创建时间。
  - `birthday` 不为空时必须早于 `created_at`。
  - `province` 不为空时 `city` 可以为空，`city` 不为空时 `province` 必须不为空。
  - `gender` 未采集时统一写入 `unknown`。
  - `listening_scene_payload` 必须为 JSON 数组，元素来自固定场景集合，如 `commute`、`sleep`、`study`、`family`、`driving`。
  - 同一数组内收听场景不得重复。
  - 画像只记录偏好摘要，具体分类和标签偏好以 `user_preference` 为准。
  - `created_at >= user_account.created_at`
  - `updated_at >= created_at`

#### `member_account`
会员账户表，维护用户 VIP 状态、会员等级、有效期和积分。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `member_level`：会员等级。枚举值：
  - `normal`：普通用户
  - `vip`：VIP 会员
  - `svip`：超级会员
- `member_status`：会员状态。枚举值：
  - `inactive`：未开通
  - `active`：生效中
  - `expired`：已过期
  - `frozen`：冻结
- `valid_from`：会员生效时间。
- `valid_to`：会员失效时间。
- `points_balance`：积分余额。
- `growth_value`：成长值。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_member_account_user (user_id)`
- 外键约束：
  - `fk_member_account_user (user_id -> user_account.id)`
- 业务约束：
  - `created_at >= user_account.created_at`
  - `points_balance >= 0`
  - `growth_value >= 0`
  - `member_level = normal` 时 `member_status` 只能为 `inactive` 或 `expired`。
  - `member_level in (vip, svip)` 且 `member_status = active` 时，`valid_from` 和 `valid_to` 必须不为空。
  - `member_status = active` 时 `valid_from <= 当前时间 < valid_to`。
  - `member_status = inactive` 时 `valid_from` 和 `valid_to` 可以为空。
  - `member_status = expired` 时 `valid_to <= 当前时间`。
  - `member_status = frozen` 时会员有效期保留，权益使用由业务服务拦截。
  - `svip` 用户同时拥有 `vip` 基础权益，权益判断以最高会员等级为准。
  - `valid_to` 不为空时，`valid_to > valid_from`
  - `updated_at >= created_at`

#### `user_follow`
关注关系表，维护用户关注主播、作者、版权机构等主体的关系。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `target_type`：关注对象类型。枚举值：
  - `narrator`：主播
  - `author`：作者
  - `organization`：版权机构
- `target_id`：关注对象 ID。
- `follow_status`：关注状态。枚举值：
  - `following`：关注中
  - `cancelled`：已取消
- `followed_at`：关注时间。
- `cancelled_at`：取消关注时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_follow_target (user_id, target_type, target_id)`
- 外键约束：
  - `fk_user_follow_user (user_id -> user_account.id)`
- 业务约束：
  - `target_type = narrator` 时 `target_id` 必须指向 `content_narrator.id`。
  - `target_type = author` 时 `target_id` 必须指向 `content_author.id`。
  - `target_type = organization` 时 `target_id` 必须指向 `content_organization.id`。
  - 被关注对象必须处于启用状态。
  - 用户不能关注已注销或停用的主体账号。
  - 同一用户对同一对象只能保留一条关注关系，重复关注更新 `follow_status` 和时间字段。
  - `followed_at >= user_account.created_at`
  - `follow_status = following` 时 `cancelled_at` 为空。
  - `follow_status = cancelled` 时 `cancelled_at >= followed_at`
  - 取消关注后再次关注时，`followed_at` 更新为最新关注时间，`cancelled_at` 清空。
  - `updated_at >= created_at`

#### `user_bookshelf`
用户书架表，维护用户对专辑的收藏、订阅、追更和完播状态。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `shelf_status`：书架状态。枚举值：
  - `favorited`：已收藏
  - `subscribed`：已订阅
  - `finished`：已完播
  - `removed`：已移除
- `last_track_id`：最近收听章节 ID，关联 `audio_track.id`。
- `last_position_seconds`：最近收听进度秒数。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_bookshelf_album (user_id, album_id)`
- 外键约束：
  - `fk_user_bookshelf_user (user_id -> user_account.id)`
  - `fk_user_bookshelf_album (album_id -> audio_album.id)`
  - `fk_user_bookshelf_last_track (last_track_id -> audio_track.id)`
- 业务约束：
  - `album_id` 必须指向未物理删除的专辑。
  - `shelf_status in (favorited, subscribed, finished)` 时专辑必须允许在用户侧展示。
  - `shelf_status = removed` 表示用户移出书架，历史记录保留。
  - 同一用户同一专辑只能有一条书架记录，重复收藏或订阅更新状态和时间。
  - `last_track_id` 为空时 `last_position_seconds` 必须为 `0` 或空。
  - `last_track_id` 不为空时，章节必须属于当前 `album_id`。
  - `last_position_seconds` 不得超过 `last_track_id` 对应章节的 `duration_seconds`。
  - `shelf_status = finished` 时，该专辑已发布章节在 `listening_progress` 中应均达到完播口径。
  - `created_at >= user_account.created_at`
  - `last_position_seconds >= 0`
  - `updated_at >= created_at`

#### `user_preference`
用户偏好表，维护用户偏好的分类、标签和播放设置。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `category_id`：偏好分类 ID，关联 `dim_audio_category.id`。
- `tag_id`：偏好标签 ID，关联 `dim_content_tag.id`。
- `preference_type`：偏好类型。枚举值：
  - `category`：分类偏好
  - `tag`：标签偏好
  - `play_setting`：播放设置
- `preference_payload`：偏好内容，JSON 格式。
- `weight_score`：偏好权重分。
- `preference_target_key`：偏好对象归一化键，由数据库生成，用于规避可空列唯一键失效。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_preference_key (user_id, preference_type, preference_target_key)`
- 外键约束：
  - `fk_user_preference_user (user_id -> user_account.id)`
  - `fk_user_preference_category (category_id -> dim_audio_category.id)`
  - `fk_user_preference_tag (tag_id -> dim_content_tag.id)`
- 业务约束：
  - `preference_type = category` 时 `category_id` 不为空。
  - `preference_type = category` 时 `tag_id` 为空。
  - `preference_type = tag` 时 `tag_id` 不为空。
  - `preference_type = tag` 时 `category_id` 为空。
  - `preference_type = play_setting` 时 `category_id` 和 `tag_id` 均为空，具体配置写入 `preference_payload`。
  - `category_id` 不为空时必须指向启用分类。
  - `tag_id` 不为空时必须指向启用标签。
  - `preference_payload` 必须为合法 JSON；播放设置可包含倍速、定时关闭、跳过片头片尾等配置。
  - `weight_score >= 0`
  - `preference_target_key` 由 `preference_type`、`category_id` 和 `tag_id` 生成，不允许业务侧手动写入。
  - `weight_score` 越大表示偏好越强，同一用户同一 `preference_type` 下用于推荐排序。
  - 同一用户的分类偏好和标签偏好可并存，但同一分类或标签只能保留一条记录。
  - `updated_at >= created_at`

#### `user_message`
用户消息表，维护私信、系统通知、审核通知、交易通知和活动通知。

- `id`：主键 ID。
- `message_no`：消息编号，业务唯一标识。
- `sender_user_id`：发送用户 ID，关联 `user_account.id`，系统消息为空。
- `receiver_user_id`：接收用户 ID，关联 `user_account.id`。
- `message_type`：消息类型。枚举值：
  - `private`：私信
  - `system`：系统通知
  - `audit`：审核通知
  - `trade`：交易通知
  - `activity`：活动通知
- `target_type`：关联对象类型。枚举值：
  - `none`：无关联对象
  - `album`：专辑
  - `track`：章节
  - `comment`：评论
  - `content_order`：内容订单
  - `recharge_order`：充值订单
  - `upload_task`：上传任务
  - `support_ticket`：反馈工单
- `target_id`：关联对象 ID。
- `message_title`：消息标题。
- `message_content`：消息内容。
- `read_status`：阅读状态。枚举值：
  - `unread`：未读
  - `read`：已读
  - `deleted`：已删除
- `sent_at`：发送时间。
- `read_at`：阅读时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_message_no (message_no)`
- 外键约束：
  - `fk_user_message_sender (sender_user_id -> user_account.id)`
  - `fk_user_message_receiver (receiver_user_id -> user_account.id)`
- 业务约束：
  - `receiver_user_id` 必须指向未注销用户。
  - `message_type = private` 时 `sender_user_id` 必须不为空。
  - `message_type != private` 时 `sender_user_id` 可以为空，表示平台系统发送。
  - `target_type = none` 时 `target_id` 必须为空。
  - `target_type != none` 时 `target_id` 必须不为空，并按对象类型指向对应业务表。
  - `message_title` 和 `message_content` 至少填写一个。
  - `read_status = unread` 时 `read_at` 必须为空。
  - `read_status = read` 时 `read_at` 必须不为空。
  - `read_status = deleted` 表示用户侧删除，后台消息记录保留。
  - `sent_at >= created_at`
  - `read_at` 不为空时，`read_at >= sent_at`
  - `updated_at >= created_at`

### 内容供给域
本域用于维护主播、作者、机构、专辑、章节、音频文件、版权和价格规则。

表说明：

- `content_organization`：内容机构表，维护版权方、出版方、制作方和 MCN 机构。
- `content_author`：作者表，维护原著作者、编剧和栏目作者。
- `content_narrator`：主播表，维护主播账号、签约类型和主页资料。
- `creator_profile`：创作者档案表，维护用户入驻听书号后的创作者身份。
- `creator_apply_record`：创作者入驻申请表，维护主播招募、认证主播和机构账号的申请审核。
- `audio_album`：音频专辑表，维护有声书、主播节目、播客等内容主档。
- `album_organization_rel`：专辑机构关系表，维护专辑与版权方、出品方、制作方、发行方等多角色关系。
- `album_author_rel`：专辑作者关系表，维护专辑与作者的多对多关系。
- `album_narrator_rel`：专辑主播关系表，维护专辑与主播的多对多关系。
- `album_tag_rel`：专辑标签关系表，维护专辑与标签的多对多关系。
- `audio_track`：音频章节表，维护专辑下的分集、章节和节目单集。
- `track_audio_file`：章节音频文件表，维护音频地址、码率、时长和审核状态。
- `content_upload_task`：内容上传任务表，维护创作者上传书籍、节目、章节和音频文件的处理过程。
- `content_audit_record`：内容审核记录表，维护专辑、章节、音频文件、上传任务的审核结果。
- `album_update_record`：专辑更新记录表，维护专辑最后更新、发布新书、发布章节等更新事件。
- `album_price_rule`：专辑价格规则表，维护免费、会员免费、单本购买和章节购买规则。

依赖关系说明：

- `creator_profile` 依赖 `user_account`，一个用户最多对应一个当前创作者档案。
- `creator_apply_record` 依赖 `user_account`、`content_organization` 和 `creator_profile`。
- `audio_album` 依赖 `dim_audio_category`、`dim_language` 和 `content_organization`。
- `audio_album` 与 `content_organization` 通过 `album_organization_rel` 形成多角色关系。
- `audio_album -> audio_track -> track_audio_file` 构成内容资产主线。
- `audio_album` 与 `content_author`、`content_narrator`、`dim_content_tag` 通过关系表形成多对多关系。
- `content_upload_task` 依赖创作者、专辑、章节和音频文件。
- `content_audit_record` 依赖审核对象，并可关联上传任务。
- `album_update_record` 依赖专辑，并可关联章节和创作者。
- `album_price_rule` 依赖 `audio_album`，用于定义专辑维度的售卖和试看规则。

#### `content_organization`
内容机构表，维护版权机构、出版机构、制作团队和主播 MCN。

- `id`：主键 ID。
- `organization_code`：机构编码，业务唯一标识。
- `organization_name`：机构名称。
- `organization_type`：机构类型。枚举值：
  - `copyright_owner`：版权方
  - `publisher`：出版方
  - `production`：制作方
  - `mcn`：主播机构
  - `platform`：平台自营
- `contact_name`：联系人姓名。
- `contact_info`：联系人联系方式，可填写手机号、邮箱、座机或即时通讯账号。
- `intro`：机构简介。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_organization_code (organization_code)`
- 外键约束：
  - 无
- 业务约束：
  - `organization_type = platform` 表示平台自营机构，通常只能有一条主记录或按业务线拆分。
  - `organization_type = mcn` 的机构可关联多个主播。
  - `organization_type in (copyright_owner, publisher, production, platform)` 的机构可作为专辑 `organization_id`。
  - 启用机构 `yn = 1` 才能被新建主播和专辑引用。
  - 已被主播、专辑或订单权益间接引用的机构不得物理删除，只能将 `yn` 置为 `0`。
  - `contact_info` 不为空时应为可触达的联系方式。
  - 停用机构后，其已上架专辑不自动下架，是否下架由内容运营流程处理。
  - `updated_at >= created_at`

#### `content_author`
作者表，维护原著作者、编剧、栏目作者等创作者资料。

- `id`：主键 ID。
- `author_code`：作者编码，业务唯一标识。
- `author_name`：作者名称。
- `author_type`：作者类型。枚举值：
  - `original`：原著作者
  - `screenwriter`：编剧
  - `columnist`：栏目作者
  - `anonymous`：佚名
- `intro`：作者简介。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_author_code (author_code)`
- 外键约束：
  - 无
- 业务约束：
  - `author_type = anonymous` 时 `author_name` 固定使用“佚名”或平台约定的匿名展示名。
  - 启用作者 `yn = 1` 才能被新增专辑作者关系引用。
  - 已被 `album_author_rel.author_id` 引用的作者不得物理删除，只能将 `yn` 置为 `0`。
  - 同一启用作者名称和作者类型组合不允许重复。
  - 作者停用后不影响历史专辑展示，新增专辑不得继续绑定该作者。
  - `intro` 为空时前端展示可使用默认简介，不影响专辑上架。
  - `updated_at >= created_at`

#### `content_narrator`
主播表，维护主播展示资料、签约状态和统计摘要。

- `id`：主键 ID。
- `narrator_code`：主播编码，业务唯一标识。
- `narrator_name`：主播名称。
- `avatar_url`：主播头像地址。
- `organization_id`：所属机构 ID，关联 `content_organization.id`。
- `contract_type`：签约类型。枚举值：
  - `exclusive`：独家签约
  - `signed`：签约
  - `open`：开放入驻
  - `official`：官方账号
- `intro`：主播简介。
- `follower_count`：关注人数。
- `album_count`：专辑数量。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_narrator_code (narrator_code)`
- 外键约束：
  - `fk_content_narrator_organization (organization_id -> content_organization.id)`
- 业务约束：
  - `organization_id` 不为空时必须指向启用机构。
  - `contract_type = exclusive` 的主播在平台内标记为独家签约主播。
  - `contract_type = official` 的主播通常对应平台或机构官方账号。
  - 启用主播 `yn = 1` 才能被新增专辑主播关系引用。
  - 已被 `album_narrator_rel.narrator_id` 或 `user_follow.target_id` 引用的主播不得物理删除，只能将 `yn` 置为 `0`。
  - `follower_count >= 0`
  - `album_count >= 0`
  - `follower_count` 应等于 `user_follow` 中当前关注状态为 `following` 的记录数，允许作为冗余统计字段异步更新。
  - `album_count` 应等于 `album_narrator_rel` 中该主播关联且专辑未下架的专辑数，允许作为冗余统计字段异步更新。
  - 停用主播后不影响历史播放、订单、评论和榜单记录查询。
  - `updated_at >= created_at`

#### `creator_profile`
创作者档案表，维护用户入驻听书号后的创作者身份、认证状态和创作主页信息。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `creator_no`：创作者编号，业务唯一标识。
- `creator_name`：创作者展示名称。
- `creator_type`：创作者类型。枚举值：
  - `individual`：个人创作者
  - `studio`：工作室
  - `organization`：机构账号
  - `official`：官方账号
- `narrator_id`：关联主播 ID，关联 `content_narrator.id`。
- `organization_id`：关联机构 ID，关联 `content_organization.id`。
- `certification_status`：认证状态。枚举值：
  - `uncertified`：未认证
  - `pending`：认证中
  - `certified`：已认证
  - `rejected`：认证失败
  - `revoked`：认证撤销
- `creator_intro`：创作者简介。
- `homepage_url`：创作者主页地址。
- `settled_at`：入驻时间。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_creator_profile_no (creator_no)`
  - `uk_creator_profile_user (user_id)`
- 外键约束：
  - `fk_creator_profile_user (user_id -> user_account.id)`
  - `fk_creator_profile_narrator (narrator_id -> content_narrator.id)`
  - `fk_creator_profile_organization (organization_id -> content_organization.id)`
- 业务约束：
  - `user_id` 必须指向正常或禁言状态的用户，停用和注销用户不得入驻。
  - `creator_type in (individual, studio, official)` 时 `narrator_id` 必须不为空。
  - `creator_type = organization` 时 `organization_id` 必须不为空。
  - `certification_status = certified` 时 `settled_at` 必须不为空。
  - `certification_status in (rejected, revoked)` 时不得新增上传任务。
  - 启用创作者 `yn = 1` 才能上传书籍、节目、章节和音频文件。
  - `creator_name` 应与关联主播或机构展示名称保持一致，允许后台单独维护展示别名。
  - `settled_at` 不为空时，`settled_at >= user_account.created_at`
  - `updated_at >= created_at`

#### `creator_apply_record`
创作者入驻申请表，维护主播招募、认证主播、机构账号和听书号入驻的申请审核。

- `id`：主键 ID。
- `apply_no`：申请编号，业务唯一标识。
- `user_id`：申请用户 ID，关联 `user_account.id`。
- `creator_id`：创作者 ID，关联 `creator_profile.id`，首次入驻申请可为空。
- `organization_id`：申请关联机构 ID，关联 `content_organization.id`。
- `apply_type`：申请类型。枚举值：
  - `creator_settle`：创作者入驻
  - `narrator_certification`：主播认证
  - `organization_certification`：机构认证
  - `contract_upgrade`：签约升级
- `apply_payload`：申请材料，JSON 格式。
- `apply_status`：申请状态。枚举值：
  - `submitted`：已提交
  - `reviewing`：审核中
  - `approved`：已通过
  - `rejected`：已拒绝
  - `cancelled`：已取消
- `reject_reason`：拒绝原因。
- `submitted_at`：提交时间。
- `reviewed_at`：审核时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_creator_apply_record_no (apply_no)`
- 外键约束：
  - `fk_creator_apply_record_user (user_id -> user_account.id)`
  - `fk_creator_apply_record_creator (creator_id -> creator_profile.id)`
  - `fk_creator_apply_record_organization (organization_id -> content_organization.id)`
- 业务约束：
  - `user_id` 必须指向正常或禁言状态的用户。
  - `creator_id` 不为空时必须属于当前 `user_id`。
  - 同一用户同一 `apply_type` 同一时间只能存在一条未完结申请。
  - `apply_payload` 必须为合法 JSON，并记录身份材料、样音、作品链接、机构证明等申请资料。
  - `apply_type = creator_settle` 时 `creator_id` 可为空，审核通过后创建新的 `creator_profile`。
  - `apply_type in (narrator_certification, organization_certification, contract_upgrade)` 且申请基于已有创作者身份发起时，`creator_id` 必须不为空。
  - `apply_status in (submitted, reviewing)` 时 `reviewed_at` 必须为空。
  - `apply_status = approved` 时 `reviewed_at` 必须不为空，审核通过后应创建或更新 `creator_profile`。
  - `apply_status = rejected` 时 `reviewed_at` 和 `reject_reason` 必须不为空。
  - `apply_status = cancelled` 时不得继续审核。
  - `apply_type = organization_certification` 时 `organization_id` 必须不为空。
  - `submitted_at >= user_account.created_at`
  - `reviewed_at` 不为空时，`reviewed_at >= submitted_at`
  - `updated_at >= created_at`

#### `audio_album`
音频专辑表，维护有声书、主播节目、播客、评书、戏曲等内容主档。

- `id`：主键 ID。
- `album_code`：专辑编码，业务唯一标识。
- `album_title`：专辑标题。
- `album_type`：专辑类型。枚举值：
  - `audiobook`：有声书
  - `program`：主播节目
  - `podcast`：播客
  - `radio`：电台
  - `course`：知识课程
- `category_id`：分类 ID，关联 `dim_audio_category.id`。
- `language_id`：语言 ID，关联 `dim_language.id`。
- `organization_id`：版权或制作机构 ID，关联 `content_organization.id`。
- `cover_url`：封面地址。
- `summary`：专辑简介。
- `album_status`：专辑状态。枚举值：
  - `draft`：草稿
  - `reviewing`：审核中
  - `published`：已上架
  - `paused`：暂停更新
  - `offline`：已下架
- `publish_status`：更新状态。枚举值：
  - `serializing`：连载中
  - `completed`：已完结
  - `unknown`：未知
- `age_rating`：适听年龄。枚举值：
  - `all`：全年龄
  - `children`：儿童
  - `teen`：青少年
  - `adult`：成人
- `track_count`：章节总数。
- `total_duration_seconds`：总时长秒数。
- `play_count`：播放次数。
- `favorite_count`：收藏次数。
- `rating_score`：评分，取值范围 `0-10`。
- `published_at`：上架时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_audio_album_code (album_code)`
- 外键约束：
  - `fk_audio_album_category (category_id -> dim_audio_category.id)`
  - `fk_audio_album_language (language_id -> dim_language.id)`
  - `fk_audio_album_organization (organization_id -> content_organization.id)`
- 业务约束：
  - `category_id` 必须指向启用分类，且分类类型应与 `album_type` 匹配。
  - `language_id` 必须指向启用语言。
  - `organization_id` 不为空时必须指向启用机构。
  - `album_status = draft` 时允许缺少章节、主播和价格规则。
  - `album_status = reviewing` 时必须至少配置一个主播关系和基础专辑信息。
  - `album_status = published` 时必须至少存在一条 `track_status = published` 的章节。
  - `album_status = published` 时必须至少存在一条主讲主播关系，且主讲主播处于启用状态。
  - `album_status = published` 时 `cover_url`、`summary`、`category_id`、`language_id` 不得为空。
  - `album_status = paused` 表示暂停新增章节，已上架章节仍可播放。
  - `album_status = offline` 表示用户侧不可新购和新增播放，历史订单、权益和播放记录保留。
  - `publish_status = completed` 时不再新增正篇章节，允许新增番外或修订章节。
  - `publish_status = serializing` 时允许继续新增章节。
  - `track_count >= 0`
  - `track_count` 应等于当前专辑下未删除章节数量，允许作为冗余统计字段异步更新。
  - `total_duration_seconds >= 0`
  - `total_duration_seconds` 应等于当前专辑下已发布章节时长总和，允许作为冗余统计字段异步更新。
  - `play_count >= 0`
  - `favorite_count >= 0`
  - `favorite_count` 应等于 `user_bookshelf` 中收藏或订阅该专辑的有效记录数，允许作为冗余统计字段异步更新。
  - `rating_score >= 0 and rating_score <= 10`
  - `rating_score` 应由 `content_rating` 的有效评分聚合生成，未评分专辑可为 `0`。
  - `album_status = published` 时 `published_at` 不为空。
  - `published_at` 不为空时，`published_at >= created_at`
  - 已产生订单、权益或播放记录的专辑不得物理删除，只能调整 `album_status`。
  - `updated_at >= created_at`

#### `album_organization_rel`
专辑机构关系表，维护专辑与版权方、出品方、制作方、发行方和内容来源方的多角色关系。

- `id`：主键 ID。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `organization_id`：机构 ID，关联 `content_organization.id`。
- `organization_role`：机构角色。枚举值：
  - `copyright_owner`：版权方
  - `publisher`：出版方
  - `producer`：出品方
  - `production`：制作方
  - `distributor`：发行方
  - `source_platform`：内容来源平台
  - `mcn`：主播机构
- `authorization_status`：授权状态。枚举值：
  - `valid`：有效
  - `pending`：待确认
  - `expired`：已过期
  - `terminated`：已终止
- `effective_from`：授权生效时间。
- `effective_to`：授权失效时间。
- `sort_no`：排序号。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_album_organization_rel (album_id, organization_id, organization_role)`
- 外键约束：
  - `fk_album_organization_rel_album (album_id -> audio_album.id)`
  - `fk_album_organization_rel_organization (organization_id -> content_organization.id)`
- 业务约束：
  - `album_id` 必须指向未物理删除的专辑。
  - `organization_id` 必须指向启用机构。
  - 已上架专辑至少应存在一个有效的版权方、出品方、制作方或平台自营机构关系。
  - 同一专辑同一机构可承担多个角色，但同一角色只能保留一条当前关系。
  - `authorization_status = valid` 时当前时间必须落在授权有效期内，永久授权 `effective_to` 可为空。
  - `authorization_status in (expired, terminated)` 时不得用于新上架或新销售授权。
  - `effective_to` 不为空时，`effective_to > effective_from`
  - `sort_no` 用于机构展示顺序，允许不连续但不得为空。
  - `created_at >= audio_album.created_at`
  - `updated_at >= created_at`

#### `album_update_record`
专辑更新记录表，维护专辑发布新书、发布章节、恢复更新、完结和下架等更新事件。

- `id`：主键 ID。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `track_id`：章节 ID，关联 `audio_track.id`。
- `creator_id`：创作者 ID，关联 `creator_profile.id`。
- `update_type`：更新类型。枚举值：
  - `album_published`：专辑上架
  - `track_published`：章节发布
  - `batch_tracks_published`：批量章节发布
  - `resume_update`：恢复更新
  - `pause_update`：暂停更新
  - `completed`：专辑完结
  - `offline`：专辑下架
- `update_title`：更新标题。
- `update_summary`：更新摘要。
- `track_count_delta`：本次新增章节数。
- `duration_delta_seconds`：本次新增时长秒数。
- `updated_at_event`：业务更新时间。
- `created_at`：创建时间。

- 唯一性约束：
  - 无
- 外键约束：
  - `fk_album_update_record_album (album_id -> audio_album.id)`
  - `fk_album_update_record_track (track_id -> audio_track.id)`
  - `fk_album_update_record_creator (creator_id -> creator_profile.id)`
- 业务约束：
  - `album_id` 必须指向未物理删除的专辑。
  - `track_id` 不为空时，章节必须属于当前 `album_id`。
  - `update_type = track_published` 时 `track_id` 必须不为空，`track_count_delta = 1`。
  - `update_type = batch_tracks_published` 时 `track_count_delta > 1`。
  - `update_type in (album_published, resume_update, pause_update, completed, offline)` 时 `track_id` 可以为空。
  - `track_count_delta >= 0`
  - `duration_delta_seconds >= 0`
  - `updated_at_event >= audio_album.created_at`
  - 专辑详情页的“最后更新”可取该专辑最近一条有效更新记录的 `updated_at_event`。
  - 主播主页的“近期动态”可由该表写入或同步生成 `user_activity_feed`。

#### `album_author_rel`
专辑作者关系表，维护专辑与作者的多对多关系。

- `id`：主键 ID。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `author_id`：作者 ID，关联 `content_author.id`。
- `author_role`：作者角色。枚举值：
  - `original_author`：原著作者
  - `screenwriter`：编剧
  - `translator`：译者
  - `editor`：编辑
- `sort_no`：排序号。
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_album_author_rel (album_id, author_id, author_role)`
- 外键约束：
  - `fk_album_author_rel_album (album_id -> audio_album.id)`
  - `fk_album_author_rel_author (author_id -> content_author.id)`
- 业务约束：
  - `album_id` 必须指向未物理删除的专辑。
  - `author_id` 必须指向启用作者。
  - 同一专辑至少应有一个 `author_role = original_author` 的作者；节目类和播客类专辑可按业务规则豁免。
  - 同一专辑可配置多名作者，`sort_no` 用于前端署名顺序。
  - `sort_no` 在同一专辑同一角色下不得重复。
  - 已发布专辑的作者关系变更应保留审计记录，当前表只保存最新有效关系。
  - `created_at >= audio_album.created_at`
  - `created_at >= content_author.created_at`

#### `album_narrator_rel`
专辑主播关系表，维护专辑与主播的多对多关系。

- `id`：主键 ID。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `narrator_id`：主播 ID，关联 `content_narrator.id`。
- `narrator_role`：主播角色。枚举值：
  - `main`：主讲
  - `cast`：参演
  - `host`：主持
  - `guest`：嘉宾
- `sort_no`：排序号。
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_album_narrator_rel (album_id, narrator_id, narrator_role)`
- 外键约束：
  - `fk_album_narrator_rel_album (album_id -> audio_album.id)`
  - `fk_album_narrator_rel_narrator (narrator_id -> content_narrator.id)`
- 业务约束：
  - `album_id` 必须指向未物理删除的专辑。
  - `narrator_id` 必须指向启用主播。
  - 已上架专辑必须至少存在一名 `narrator_role = main` 或 `narrator_role = host` 的主播。
  - 同一专辑可以配置多个 `cast` 主播，`sort_no` 用于演员表展示顺序。
  - `sort_no` 在同一专辑同一角色下不得重复。
  - 主播停用后不得新增关系，已有关系是否展示由专辑状态和运营规则决定。
  - `created_at >= audio_album.created_at`
  - `created_at >= content_narrator.created_at`

#### `album_tag_rel`
专辑标签关系表，维护专辑与标签的多对多关系。

- `id`：主键 ID。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `tag_id`：标签 ID，关联 `dim_content_tag.id`。
- `sort_no`：排序号。
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_album_tag_rel (album_id, tag_id)`
- 外键约束：
  - `fk_album_tag_rel_album (album_id -> audio_album.id)`
  - `fk_album_tag_rel_tag (tag_id -> dim_content_tag.id)`
- 业务约束：
  - `album_id` 必须指向未物理删除的专辑。
  - `tag_id` 必须指向启用标签。
  - 同一专辑的启用标签数量建议控制在运营配置上限内。
  - 同一专辑下相同标签只能出现一次。
  - `sort_no` 用于标签展示顺序，允许不连续但不得为空。
  - 专辑下架后标签关系保留，用于历史统计和再次上架。
  - `created_at >= audio_album.created_at`

#### `audio_track`
音频章节表，维护专辑下的章节、分集和节目单集。

- `id`：主键 ID。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `track_no`：章节序号。
- `track_title`：章节标题。
- `track_type`：章节类型。枚举值：
  - `normal`：正篇
  - `trailer`：预告
  - `bonus`：番外
  - `live_record`：直播回放
- `duration_seconds`：章节时长秒数。
- `free_flag`：是否免费，`1` 表示免费，`0` 表示付费。
- `trial_seconds`：可试看秒数。
- `track_status`：章节状态。枚举值：
  - `draft`：草稿
  - `reviewing`：审核中
  - `published`：已上架
  - `offline`：已下架
- `play_count`：播放次数。
- `published_at`：发布时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_audio_track_no (album_id, track_no)`
- 外键约束：
  - `fk_audio_track_album (album_id -> audio_album.id)`
- 业务约束：
  - `track_no > 0`
  - 同一专辑下 `track_no` 必须唯一，章节展示按 `track_no` 升序排列。
  - 正篇章节 `track_type = normal` 应使用连续章节序号；预告、番外、直播回放可穿插但不得与正篇冲突。
  - `duration_seconds >= 0`
  - `track_status = published` 时 `duration_seconds > 0`。
  - `trial_seconds >= 0`
  - `trial_seconds <= duration_seconds`
  - `free_flag = 1` 时用户无需会员或购买权益即可完整播放该章节。
  - `free_flag = 0` 时用户必须满足会员权益、专辑权益、章节权益或试看规则。
  - `free_flag = 1` 时 `trial_seconds` 可等于 `duration_seconds`。
  - `free_flag = 0` 时 `trial_seconds` 表示未购用户可试听时长。
  - `play_count >= 0`
  - `play_count` 应由 `play_session` 聚合生成，允许作为冗余统计字段异步更新。
  - `track_status = draft` 时不得存在可用音频文件对用户侧开放。
  - `track_status = reviewing` 时可存在音频文件，但不得对普通用户开放播放。
  - `track_status = published` 时 `published_at` 不为空。
  - `track_status = published` 时必须至少存在一条 `file_status = available` 的音频文件。
  - `track_status = offline` 时不得新增播放会话，历史播放进度保留。
  - `created_at >= audio_album.created_at`
  - `published_at` 不为空时，`published_at >= created_at`
  - `updated_at >= created_at`

#### `track_audio_file`
章节音频文件表，维护章节的不同码率、格式和存储地址。

- `id`：主键 ID。
- `track_id`：章节 ID，关联 `audio_track.id`。
- `file_code`：音频文件编码，业务唯一标识。
- `file_url`：音频文件地址。
- `file_format`：文件格式。枚举值：
  - `mp3`
  - `m4a`
  - `aac`
- `bitrate_kbps`：码率。
- `sample_rate_hz`：采样率。
- `file_size_bytes`：文件大小。
- `duration_seconds`：文件时长秒数。
- `version_no`：文件版本号，同一章节同一格式同一码率下从 `1` 开始递增。
- `is_current`：是否当前生效文件，`1` 表示当前文件，`0` 表示历史文件。
- `file_status`：文件状态。枚举值：
  - `available`：可用
  - `processing`：转码中
  - `failed`：转码失败
  - `deleted`：已删除
- `current_quality_key`：当前文件质量归一化键，由数据库生成，用于限制同一章节同一格式同一码率只能有一个当前文件。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_track_audio_file_code (file_code)`
  - `uk_track_audio_file_version (track_id, file_format, bitrate_kbps, version_no)`
  - `uk_track_audio_file_current_quality (current_quality_key)`
- 外键约束：
  - `fk_track_audio_file_track (track_id -> audio_track.id)`
- 业务约束：
  - 同一章节同一格式同一码率只能存在一条 `is_current = 1` 的当前文件。
  - 历史失败、删除或替换文件必须保留不同 `version_no`。
  - `is_current` 只能取 `0` 或 `1`。
  - `file_url` 必须为平台可访问的对象存储地址或 CDN 地址。
  - `file_status = available` 时 `file_url`、`file_size_bytes`、`duration_seconds` 必须有效。
  - `file_status = processing` 时允许文件大小和时长暂未完成回填。
  - `file_status = failed` 时不得被播放服务选用。
  - `file_status = deleted` 时不得被播放服务选用，但记录保留用于审计。
  - `bitrate_kbps > 0`
  - `sample_rate_hz > 0`
  - `file_size_bytes > 0`
  - `duration_seconds >= 0`
  - 可用音频文件的 `duration_seconds` 应与 `audio_track.duration_seconds` 保持一致，允许存在转码误差。
  - 同一章节可存在多个码率文件，播放服务按网络状态和会员权益选择文件。
  - `created_at >= audio_track.created_at`
  - `updated_at >= created_at`

#### `content_upload_task`
内容上传任务表，维护创作者上传书籍、节目、章节和音频文件的处理过程。

- `id`：主键 ID。
- `upload_no`：上传任务编号，业务唯一标识。
- `creator_id`：创作者 ID，关联 `creator_profile.id`。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `track_id`：章节 ID，关联 `audio_track.id`。
- `file_id`：音频文件 ID，关联 `track_audio_file.id`。
- `upload_type`：上传类型。枚举值：
  - `album`：专辑资料
  - `track`：章节资料
  - `audio_file`：音频文件
  - `cover`：封面图片
  - `batch_tracks`：批量章节
- `source_file_name`：源文件名称。
- `source_file_url`：源文件地址。
- `file_size_bytes`：源文件大小。
- `process_status`：处理状态。枚举值：
  - `submitted`：已提交
  - `uploading`：上传中
  - `uploaded`：上传完成
  - `processing`：处理中
  - `processed`：处理完成
  - `failed`：处理失败
  - `cancelled`：已取消
- `failure_reason`：失败原因。
- `submitted_at`：提交时间。
- `processed_at`：处理完成时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_upload_task_no (upload_no)`
- 外键约束：
  - `fk_content_upload_task_creator (creator_id -> creator_profile.id)`
  - `fk_content_upload_task_album (album_id -> audio_album.id)`
  - `fk_content_upload_task_track (track_id -> audio_track.id)`
  - `fk_content_upload_task_file (file_id -> track_audio_file.id)`
- 业务约束：
  - `creator_id` 必须指向启用且认证通过的创作者。
  - `upload_type = album` 时 `album_id` 可以为空，处理完成后应创建或关联专辑。
  - `upload_type in (track, audio_file, cover, batch_tracks)` 时 `album_id` 必须不为空。
  - `upload_type in (track, audio_file)` 时 `track_id` 可以为空，处理完成后应创建或关联章节。
  - `upload_type = audio_file` 且处理完成后必须关联 `file_id`。
  - `source_file_url` 必须为平台可访问的临时上传地址或对象存储地址。
  - `file_size_bytes` 不为空时必须大于 `0`。
  - `process_status in (submitted, uploading, uploaded, processing)` 时 `processed_at` 必须为空。
  - `process_status = processed` 时 `processed_at` 必须不为空。
  - `process_status = failed` 时 `failure_reason` 必须不为空。
  - `process_status = cancelled` 时不得继续进入审核。
  - `submitted_at >= creator_profile.created_at`
  - `processed_at` 不为空时，`processed_at >= submitted_at`
  - `updated_at >= created_at`

#### `content_audit_record`
内容审核记录表，维护专辑、章节、音频文件、上传任务、评论和创作者资料的审核过程。

- `id`：主键 ID。
- `audit_no`：审核编号，业务唯一标识。
- `upload_task_id`：上传任务 ID，关联 `content_upload_task.id`。
- `target_type`：审核对象类型。枚举值：
  - `album`：专辑
  - `track`：章节
  - `audio_file`：音频文件
  - `upload_task`：上传任务
  - `comment`：评论
  - `creator_profile`：创作者档案
- `target_id`：审核对象 ID。
- `audit_type`：审核类型。枚举值：
  - `machine`：机审
  - `manual`：人工审核
  - `appeal`：申诉复核
- `audit_status`：审核状态。枚举值：
  - `pending`：待审核
  - `approved`：已通过
  - `rejected`：已拒绝
  - `need_modify`：需修改
  - `blocked`：封禁
- `audit_reason`：审核原因。
- `audit_payload`：审核明细，JSON 格式。
- `auditor_name`：审核人名称。
- `audited_at`：审核时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_audit_record_no (audit_no)`
- 外键约束：
  - `fk_content_audit_record_upload_task (upload_task_id -> content_upload_task.id)`
- 业务约束：
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`。
  - `target_type = track` 时 `target_id` 必须指向 `audio_track.id`。
  - `target_type = audio_file` 时 `target_id` 必须指向 `track_audio_file.id`。
  - `target_type = upload_task` 时 `target_id` 必须指向 `content_upload_task.id`。
  - `target_type = comment` 时 `target_id` 必须指向 `content_comment.id`。
  - `target_type = creator_profile` 时 `target_id` 必须指向 `creator_profile.id`。
  - `audit_status = pending` 时 `audited_at` 必须为空。
  - `audit_status in (approved, rejected, need_modify, blocked)` 时 `audited_at` 必须不为空。
  - `audit_status in (rejected, need_modify, blocked)` 时 `audit_reason` 必须不为空。
  - `audit_type = machine` 时 `auditor_name` 可以为空。
  - 审核通过后应同步更新审核对象的业务状态。
  - 审核拒绝或封禁后不得对用户侧展示对应内容。
  - `audited_at` 不为空时，`audited_at >= created_at`
  - `updated_at >= created_at`

#### `album_price_rule`
专辑价格规则表，维护专辑售卖、会员免费、章节购买和试看规则。

- `id`：主键 ID。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `price_type`：价格类型。枚举值：
  - `free`：全本免费
  - `vip_free`：会员免费
  - `album_paid`：整本付费
  - `track_paid`：章节付费
  - `limited_free`：限时免费
- `currency_code`：币种编码，关联 `dim_currency.currency_code`。
- `album_price_amount`：整本价格。
- `track_price_amount`：单章价格。
- `free_track_count`：免费章节数。
- `effective_from`：生效时间。
- `effective_to`：失效时间。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_album_price_rule_period (album_id, price_type, effective_from)`
- 外键约束：
  - `fk_album_price_rule_album (album_id -> audio_album.id)`
  - `fk_album_price_rule_currency (currency_code -> dim_currency.currency_code)`
- 业务约束：
  - `currency_code` 必须指向启用币种。
  - 同一专辑同一时间点只能有一条启用价格规则生效。
  - 启用价格规则的有效期不得与同一专辑其他启用价格规则重叠。
  - `price_type = free` 时 `album_price_amount = 0`，`track_price_amount = 0`。
  - `price_type = vip_free` 时普通用户按试看规则播放，会员用户可完整播放。
  - `price_type = album_paid` 时 `album_price_amount > 0`，`track_price_amount` 可为空或为 `0`。
  - `price_type = track_paid` 时 `track_price_amount > 0`，`album_price_amount` 可为空或为整本打包价。
  - `price_type = limited_free` 时 `effective_to` 必须不为空。
  - `album_price_amount >= 0`
  - `track_price_amount >= 0`
  - `free_track_count >= 0`
  - `free_track_count` 不得大于专辑 `track_count`。
  - 免费章节通常从 `track_no` 最小的正篇章节开始计算。
  - 金额字段必须符合 `dim_currency.precision_scale` 的精度要求。
  - 停用价格规则 `yn = 0` 不参与新增订单定价，但历史订单保留原成交价。
  - `effective_to` 不为空时，`effective_to > effective_from`
  - `created_at >= audio_album.created_at`
  - `updated_at >= created_at`

### 播放互动域
本域用于维护用户播放会话、收听进度、评论、评分、点赞、分享和举报。

表说明：

- `play_session`：播放会话表，记录一次连续播放行为。
- `listening_progress`：收听进度表，维护用户在章节上的最新进度。
- `content_comment`：内容评论表，维护专辑和章节评论。
- `content_rating`：内容评分表，维护用户对专辑的评分。
- `user_reaction`：用户互动表，维护点赞、点踩、分享等轻互动。
- `content_report`：内容举报表，维护用户举报和平台处理结果。
- `user_activity_feed`：用户动态表，维护主播主页近期动态、发布新书、发布节目和内容删除提示。
- `support_ticket`：反馈工单表，维护功能建议、使用反馈、版权投诉和客服处理过程。

依赖关系说明：

- `play_session` 依赖用户、专辑、章节和渠道。
- `listening_progress` 依赖用户、专辑和章节。
- `content_comment`、`content_rating`、`user_reaction` 和 `content_report` 依赖用户以及被互动对象。
- `user_activity_feed` 依赖发布主体，并可关联专辑、章节、节目或动态资源。
- `support_ticket` 依赖用户，并可关联内容举报、订单或上传任务。

#### `play_session`
播放会话表，记录用户一次连续播放章节的行为。

- `id`：主键 ID。
- `session_no`：播放会话编号，业务唯一标识。
- `user_id`：用户 ID，关联 `user_account.id`。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `track_id`：章节 ID，关联 `audio_track.id`。
- `channel_id`：渠道 ID，关联 `dim_channel.id`。
- `start_position_seconds`：开始播放位置秒数。
- `end_position_seconds`：结束播放位置秒数。
- `played_seconds`：本次实际播放秒数。
- `play_start_at`：播放开始时间。
- `play_end_at`：播放结束时间。
- `play_status`：播放状态。枚举值：
  - `completed`：正常结束
  - `interrupted`：中断
  - `failed`：失败
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_play_session_no (session_no)`
- 外键约束：
  - `fk_play_session_user (user_id -> user_account.id)`
  - `fk_play_session_album (album_id -> audio_album.id)`
  - `fk_play_session_track (track_id -> audio_track.id)`
  - `fk_play_session_channel (channel_id -> dim_channel.id)`
- 业务约束：
  - `user_id` 必须指向未注销用户。
  - `album_id` 必须指向未物理删除的专辑。
  - `track_id` 必须属于当前 `album_id`。
  - `track_id` 必须指向 `track_status = published` 的章节，历史补录数据除外。
  - `channel_id` 必须指向启用渠道。
  - 付费章节播放前必须校验 `entitlement_record`、`member_account` 或 `album_price_rule` 的试看规则。
  - `start_position_seconds >= 0`
  - `end_position_seconds >= 0`
  - `start_position_seconds` 和 `end_position_seconds` 不得超过章节 `duration_seconds`。
  - `play_status = completed` 时 `play_end_at` 必须不为空。
  - `play_status = failed` 时 `played_seconds` 可以为 `0`。
  - `play_status in (completed, interrupted)` 时 `played_seconds` 应大于 `0`。
  - `played_seconds >= 0`
  - `played_seconds` 不得大于 `play_end_at - play_start_at` 对应秒数。
  - `play_end_at` 不为空时，`play_end_at >= play_start_at`
  - 同一用户同一时间允许存在多个播放会话，但同一设备并发播放由业务服务限制。
  - 播放会话创建后不可物理删除，可用于重算播放量和收听时长。

#### `listening_progress`
收听进度表，维护用户在每个章节上的最新进度和完播状态。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `track_id`：章节 ID，关联 `audio_track.id`。
- `position_seconds`：当前收听位置秒数。
- `duration_seconds`：章节总时长秒数。
- `finished_flag`：是否完播，`1` 表示完播，`0` 表示未完播。
- `last_played_at`：最后播放时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_listening_progress_track (user_id, track_id)`
- 外键约束：
  - `fk_listening_progress_user (user_id -> user_account.id)`
  - `fk_listening_progress_album (album_id -> audio_album.id)`
  - `fk_listening_progress_track (track_id -> audio_track.id)`
- 业务约束：
  - `album_id` 必须指向未物理删除的专辑。
  - `track_id` 必须属于当前 `album_id`。
  - 每个用户每个章节只保留一条最新进度记录。
  - 新播放会话结束后应更新对应章节的最新进度。
  - `position_seconds >= 0`
  - `position_seconds <= duration_seconds`
  - `duration_seconds >= 0`
  - `duration_seconds` 应与 `audio_track.duration_seconds` 保持一致，章节时长修订时允许同步更新。
  - `finished_flag = 1` 时 `position_seconds >= duration_seconds * 0.95`
  - `finished_flag = 0` 时 `position_seconds < duration_seconds * 0.95`
  - `last_played_at >= created_at`
  - `last_played_at` 不得早于用户账号创建时间。
  - 章节下架后进度记录保留，但不得继续产生新进度，补录数据除外。
  - `updated_at >= created_at`

#### `content_comment`
内容评论表，维护用户对专辑或章节发布的评论。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `target_type`：评论对象类型。枚举值：
  - `album`：专辑
  - `track`：章节
- `target_id`：评论对象 ID。
- `parent_comment_id`：父评论 ID，关联 `content_comment.id`。
- `comment_text`：评论内容。
- `audit_status`：审核状态。枚举值：
  - `pending`：待审核
  - `approved`：已通过
  - `rejected`：已拒绝
- `like_count`：点赞数。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - 无
- 外键约束：
  - `fk_content_comment_user (user_id -> user_account.id)`
  - `fk_content_comment_parent (parent_comment_id -> content_comment.id)`
- 业务约束：
  - `user_id` 必须指向状态允许评论的用户。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`。
  - `target_type = track` 时 `target_id` 必须指向 `audio_track.id`。
  - `target_type = track` 时该章节必须属于可展示专辑。
  - `comment_text` 不得为空，且长度必须符合平台评论长度限制。
  - 新增评论默认 `audit_status = pending` 或按审核策略直接进入 `approved`。
  - `audit_status = approved` 的评论才允许在用户侧公开展示。
  - `audit_status = rejected` 的评论不参与公开展示和互动计数。
  - `like_count >= 0`
  - `like_count` 应由 `user_reaction` 中有效点赞记录聚合生成，允许作为冗余统计字段异步更新。
  - `parent_comment_id` 不为空时，父评论与当前评论的 `target_type`、`target_id` 一致。
  - 父评论不得指向当前评论自身，且不得形成循环回复链。
  - 已被回复的评论不得物理删除，可通过审核状态或软删除策略隐藏。
  - `updated_at >= created_at`

#### `content_rating`
内容评分表，维护用户对专辑的评分。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `rating_score`：评分，取值范围 `1-10`。
- `rating_text`：评分短评。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_rating_user_album (user_id, album_id)`
- 外键约束：
  - `fk_content_rating_user (user_id -> user_account.id)`
  - `fk_content_rating_album (album_id -> audio_album.id)`
- 业务约束：
  - `user_id` 必须指向状态允许评分的用户。
  - `album_id` 必须指向未物理删除且用户侧可见的专辑。
  - 同一用户对同一专辑只能保留一条评分记录，重复评分更新原记录。
  - 用户评分前应至少产生过播放、收藏、订阅、购买或会员可听记录之一。
  - `rating_score >= 1 and rating_score <= 10`
  - `rating_text` 为空时表示仅评分不评论。
  - 评分更新后应触发 `audio_album.rating_score` 的聚合重算。
  - `created_at >= user_account.created_at`
  - `updated_at >= created_at`

#### `user_reaction`
用户互动表，维护点赞、点踩、分享和转发等轻互动。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `target_type`：互动对象类型。枚举值：
  - `album`：专辑
  - `track`：章节
  - `comment`：评论
  - `narrator`：主播
- `target_id`：互动对象 ID。
- `reaction_type`：互动类型。枚举值：
  - `like`：点赞
  - `dislike`：点踩
  - `share`：分享
  - `forward`：转发
- `reaction_status`：互动状态。枚举值：
  - `active`：有效
  - `cancelled`：已取消
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_reaction_key (user_id, target_type, target_id, reaction_type)`
- 外键约束：
  - `fk_user_reaction_user (user_id -> user_account.id)`
- 业务约束：
  - `user_id` 必须指向状态允许互动的用户。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`。
  - `target_type = track` 时 `target_id` 必须指向 `audio_track.id`。
  - `target_type = comment` 时 `target_id` 必须指向 `content_comment.id`。
  - `target_type = narrator` 时 `target_id` 必须指向 `content_narrator.id`。
  - `reaction_type in (like, dislike)` 时同一用户对同一对象只能保持一个有效态。
  - `reaction_type in (share, forward)` 可记录用户最近一次动作，次数统计由行为日志或统计表扩展。
  - `reaction_status = cancelled` 时该记录不计入点赞、点踩、分享等展示计数。
  - 被互动对象下架或审核拒绝后不得新增有效互动。
  - `updated_at >= created_at`

#### `content_report`
内容举报表，维护用户对专辑、章节、评论和主播的举报记录。

- `id`：主键 ID。
- `report_no`：举报编号，业务唯一标识。
- `user_id`：举报用户 ID，关联 `user_account.id`。
- `target_type`：举报对象类型。枚举值：
  - `album`：专辑
  - `track`：章节
  - `comment`：评论
  - `narrator`：主播
- `target_id`：举报对象 ID。
- `report_reason`：举报原因。枚举值：
  - `copyright`：版权问题
  - `illegal`：违法违规
  - `violent`：暴恐内容
  - `pornographic`：低俗色情
  - `spam`：垃圾广告
  - `other`：其他
- `report_text`：举报说明。
- `handle_status`：处理状态。枚举值：
  - `pending`：待处理
  - `accepted`：已受理
  - `rejected`：已驳回
  - `closed`：已关闭
- `handled_at`：处理时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_report_no (report_no)`
- 外键约束：
  - `fk_content_report_user (user_id -> user_account.id)`
- 业务约束：
  - `user_id` 必须指向状态允许举报的用户。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`。
  - `target_type = track` 时 `target_id` 必须指向 `audio_track.id`。
  - `target_type = comment` 时 `target_id` 必须指向 `content_comment.id`。
  - `target_type = narrator` 时 `target_id` 必须指向 `content_narrator.id`。
  - 同一用户对同一对象同一举报原因在未处理完成前不得重复提交。
  - `report_reason = other` 时 `report_text` 必须填写。
  - `handle_status = pending` 时 `handled_at` 必须为空。
  - `handle_status in (accepted, rejected, closed)` 时 `handled_at` 不为空。
  - `handle_status = accepted` 表示举报成立，后续可触发内容下架、评论隐藏或账号处理。
  - `handle_status = rejected` 表示举报不成立，不影响被举报对象状态。
  - `handle_status = closed` 表示无需进一步处理或已合并到其他工单。
  - `handled_at` 不为空时，`handled_at >= created_at`
  - `updated_at >= created_at`

#### `user_activity_feed`
用户动态表，维护主播主页、创作者主页和用户个人主页中的近期动态。

- `id`：主键 ID。
- `feed_no`：动态编号，业务唯一标识。
- `actor_user_id`：动态主体用户 ID，关联 `user_account.id`。
- `creator_id`：动态主体创作者 ID，关联 `creator_profile.id`。
- `feed_type`：动态类型。枚举值：
  - `publish_album`：发布新书
  - `publish_program`：发布节目
  - `publish_track`：发布章节
  - `update_album`：更新专辑
  - `delete_resource`：资源删除
  - `follow`：关注
  - `system_notice`：系统动态
- `target_type`：动态对象类型。枚举值：
  - `none`：无对象
  - `album`：专辑
  - `track`：章节
  - `narrator`：主播
  - `organization`：机构
  - `topic`：专题
- `target_id`：动态对象 ID。
- `feed_title`：动态标题。
- `feed_content`：动态内容。
- `visibility`：可见范围。枚举值：
  - `public`：公开
  - `followers`：粉丝可见
  - `private`：仅自己可见
  - `deleted`：已删除
- `published_at`：动态发布时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_user_activity_feed_no (feed_no)`
- 外键约束：
  - `fk_user_activity_feed_actor (actor_user_id -> user_account.id)`
  - `fk_user_activity_feed_creator (creator_id -> creator_profile.id)`
- 业务约束：
  - `actor_user_id` 和 `creator_id` 至少填写一个。
  - `creator_id` 不为空时，动态主体应与该创作者关联用户一致。
  - `target_type = none` 时 `target_id` 必须为空。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`。
  - `target_type = track` 时 `target_id` 必须指向 `audio_track.id`。
  - `target_type = narrator` 时 `target_id` 必须指向 `content_narrator.id`。
  - `target_type = organization` 时 `target_id` 必须指向 `content_organization.id`。
  - `target_type = topic` 时 `target_id` 必须指向 `content_topic.id`。
  - `feed_type = publish_album` 时 `target_type = album`。
  - `feed_type = publish_track` 时 `target_type = track`。
  - `visibility = deleted` 的动态不在用户侧展示，但保留历史记录。
  - `published_at >= created_at`
  - `updated_at >= created_at`

#### `support_ticket`
反馈工单表，维护功能建议、使用反馈、版权投诉、支付问题和客服处理过程。

- `id`：主键 ID。
- `ticket_no`：工单编号，业务唯一标识。
- `user_id`：提交用户 ID，关联 `user_account.id`，未登录用户提交时为空。
- `ticket_type`：工单类型。枚举值：
  - `feature_feedback`：功能建议
  - `usage_feedback`：使用反馈
  - `copyright_complaint`：版权投诉
  - `payment_issue`：支付问题
  - `account_issue`：账号问题
  - `content_issue`：内容问题
  - `other`：其他问题
- `related_type`：关联对象类型。枚举值：
  - `none`：无关联对象
  - `album`：专辑
  - `track`：章节
  - `content_order`：内容订单
  - `recharge_order`：充值订单
  - `payment`：支付流水
  - `refund`：退款单
  - `upload_task`：上传任务
  - `report`：举报记录
- `related_id`：关联对象 ID。
- `ticket_title`：工单标题。
- `ticket_content`：工单内容。
- `contact_mobile`：联系手机号。
- `contact_email`：联系邮箱。
- `ticket_status`：工单状态。枚举值：
  - `submitted`：已提交
  - `processing`：处理中
  - `waiting_user`：等待用户补充
  - `resolved`：已解决
  - `rejected`：已驳回
  - `closed`：已关闭
- `handle_result`：处理结果。
- `submitted_at`：提交时间。
- `handled_at`：处理时间。
- `closed_at`：关闭时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_support_ticket_no (ticket_no)`
- 外键约束：
  - `fk_support_ticket_user (user_id -> user_account.id)`
- 业务约束：
  - `user_id` 为空时表示未登录用户提交的公开反馈，`contact_mobile` 和 `contact_email` 至少填写一个。
  - `user_id` 不为空时必须指向未注销用户。
  - `contact_mobile` 不为空时必须符合手机号格式。
  - `contact_email` 不为空时必须符合邮箱格式。
  - `related_type = none` 时 `related_id` 必须为空。
  - `related_type != none` 时 `related_id` 必须不为空，并按对象类型指向对应业务表。
  - `ticket_type = copyright_complaint` 时 `ticket_content` 必须包含权利说明或投诉材料摘要。
  - `ticket_type = payment_issue` 时 `related_type` 应为 `content_order`、`recharge_order`、`payment` 或 `refund`。
  - `ticket_status in (submitted, processing, waiting_user)` 时 `closed_at` 必须为空。
  - `ticket_status in (resolved, rejected, closed)` 时 `handled_at` 必须不为空。
  - `ticket_status = closed` 时 `closed_at` 必须不为空。
  - `handle_result` 在已解决、已驳回和已关闭状态下必须不为空。
  - `submitted_at >= created_at`
  - `handled_at` 不为空时，`handled_at >= submitted_at`
  - `closed_at` 不为空时，`closed_at >= handled_at`
  - `updated_at >= created_at`

### 交易权益域
本域用于维护 VIP 套餐、内容订单、支付流水、退款单和权益核销。

表说明：

- `vip_plan`：VIP 套餐表，维护会员套餐、周期、价格和权益配置。
- `wallet_account`：钱包账户表，维护用户余额账户和冻结金额。
- `wallet_ledger`：钱包流水表，维护充值、消费、退款、冻结和解冻流水。
- `recharge_order`：充值订单表，维护账户充值订单、支付和到账状态。
- `content_order`：内容订单表，维护 VIP、专辑和章节购买订单。
- `content_order_item`：内容订单明细表，维护订单购买对象。
- `payment_record`：支付流水表，维护支付渠道、支付金额和支付状态。
- `refund_record`：退款单表，维护退款申请、审核和打款状态。
- `refund_record_item`：退款明细表，维护内容订单按明细退款的对象和金额。
- `entitlement_record`：权益记录表，维护用户获得的会员、专辑和章节权益。

依赖关系说明：

- `wallet_account` 依赖用户和币种，一个用户可按币种维护多个钱包账户。
- `wallet_ledger` 依赖钱包账户，并可关联充值订单、内容订单、支付流水和退款单。
- `recharge_order` 依赖用户、钱包账户、渠道和币种。
- `content_order` 依赖用户、渠道和币种。
- `content_order_item` 依赖订单，并按购买类型关联 VIP 套餐、专辑或章节。
- `payment_record` 依赖内容订单或充值订单，用于统一记录第三方支付、余额支付和抵扣流水。
- `refund_record` 依赖成功支付流水，按退款对象关联内容订单或充值订单。
- `refund_record_item` 依赖退款单和内容订单明细，用于支撑组合订单、部分章节和部分专辑退款。
- `entitlement_record` 依赖用户和订单，用于记录支付成功后的可用权益。

#### `vip_plan`
VIP 套餐表，定义会员周期、价格和权益配置。

- `id`：主键 ID。
- `plan_code`：套餐编码，业务唯一标识。
- `plan_name`：套餐名称。
- `member_level`：会员等级。枚举值：
  - `vip`：VIP 会员
  - `svip`：超级会员
- `duration_days`：会员有效天数。
- `currency_code`：币种编码，关联 `dim_currency.currency_code`。
- `sale_price_amount`：销售价。
- `original_price_amount`：划线价。
- `benefit_payload`：权益配置，JSON 格式。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_vip_plan_code (plan_code)`
- 外键约束：
  - `fk_vip_plan_currency (currency_code -> dim_currency.currency_code)`
- 业务约束：
  - `currency_code` 必须指向启用币种。
  - 启用套餐 `yn = 1` 才能被新增订单引用。
  - 已被订单明细引用的套餐不得物理删除，只能将 `yn` 置为 `0`。
  - `duration_days > 0`
  - `sale_price_amount >= 0`
  - `original_price_amount >= sale_price_amount`
  - 金额字段必须符合 `dim_currency.precision_scale` 的精度要求。
  - `benefit_payload` 必须为合法 JSON，可包含可听范围、免广告、高清音质、会员标识等权益。
  - `member_level = svip` 的套餐权益必须覆盖或高于 `vip` 基础权益。
  - 停用套餐不影响已购买用户的会员有效期和权益。
  - `updated_at >= created_at`

#### `wallet_account`
钱包账户表，维护用户账户余额、冻结金额和可用金额。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `currency_code`：币种编码，关联 `dim_currency.currency_code`。
- `wallet_status`：钱包状态。枚举值：
  - `active`：正常
  - `frozen`：冻结
  - `closed`：已关闭
- `balance_amount`：账户总余额。
- `frozen_amount`：冻结金额。
- `available_amount`：可用余额。
- `opened_at`：开户时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_wallet_account_user_currency (user_id, currency_code)`
- 外键约束：
  - `fk_wallet_account_user (user_id -> user_account.id)`
  - `fk_wallet_account_currency (currency_code -> dim_currency.currency_code)`
- 业务约束：
  - `user_id` 必须指向未注销用户。
  - `currency_code` 必须指向启用币种。
  - 同一用户同一币种只能有一个钱包账户。
  - `balance_amount >= 0`
  - `frozen_amount >= 0`
  - `available_amount >= 0`
  - `available_amount = balance_amount - frozen_amount`
  - `wallet_status = active` 时允许充值、消费、退款入账和提现扩展。
  - `wallet_status = frozen` 时不得消费和提现，但允许退款入账。
  - `wallet_status = closed` 时不得新增钱包流水，历史记录保留。
  - 金额字段必须符合 `dim_currency.precision_scale` 的精度要求。
  - `opened_at >= user_account.created_at`
  - `updated_at >= created_at`

#### `wallet_ledger`
钱包流水表，维护充值入账、消费扣减、退款入账、冻结和解冻记录。

- `id`：主键 ID。
- `ledger_no`：钱包流水号，业务唯一标识。
- `wallet_id`：钱包账户 ID，关联 `wallet_account.id`。
- `user_id`：用户 ID，关联 `user_account.id`。
- `ledger_type`：流水类型。枚举值：
  - `recharge`：充值入账
  - `consume`：消费扣减
  - `refund`：退款入账
  - `freeze`：冻结
  - `unfreeze`：解冻
  - `adjust`：人工调整
- `related_type`：关联对象类型。枚举值：
  - `recharge_order`：充值订单
  - `content_order`：内容订单
  - `payment`：支付流水
  - `refund`：退款单
  - `manual`：人工操作
- `related_id`：关联对象 ID。
- `currency_code`：币种编码，关联 `dim_currency.currency_code`。
- `amount_delta`：余额变动金额，正数为增加，负数为扣减。
- `frozen_delta`：冻结金额变动，正数为冻结，负数为解冻。
- `balance_after`：变动后账户总余额。
- `frozen_after`：变动后冻结金额。
- `available_after`：变动后可用余额。
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_wallet_ledger_no (ledger_no)`
- 外键约束：
  - `fk_wallet_ledger_wallet (wallet_id -> wallet_account.id)`
  - `fk_wallet_ledger_user (user_id -> user_account.id)`
  - `fk_wallet_ledger_currency (currency_code -> dim_currency.currency_code)`
- 业务约束：
  - `wallet_id` 对应的钱包账户必须属于当前 `user_id`。
  - `currency_code` 必须与钱包账户币种一致。
  - `amount_delta` 和 `frozen_delta` 不得同时为 `0`。
  - `ledger_type = recharge` 时 `amount_delta > 0`，`related_type = recharge_order`。
  - `ledger_type = consume` 时 `amount_delta < 0`，`related_type` 应为 `content_order` 或 `payment`。
  - `ledger_type = refund` 时 `amount_delta > 0`，`related_type = refund`。
  - `ledger_type = freeze` 时 `frozen_delta > 0`。
  - `ledger_type = unfreeze` 时 `frozen_delta < 0`。
  - `balance_after >= 0`
  - `frozen_after >= 0`
  - `available_after >= 0`
  - `available_after = balance_after - frozen_after`
  - 按 `wallet_id + created_at + id` 排序后，当前余额应由上一条流水余额和本次变动推导。
  - 金额字段必须符合 `dim_currency.precision_scale` 的精度要求。

#### `recharge_order`
充值订单表，维护用户账户充值、支付和到账状态。

- `id`：主键 ID。
- `recharge_no`：充值订单号，业务唯一标识。
- `user_id`：用户 ID，关联 `user_account.id`。
- `wallet_id`：钱包账户 ID，关联 `wallet_account.id`。
- `channel_id`：充值渠道 ID，关联 `dim_channel.id`。
- `currency_code`：币种编码，关联 `dim_currency.currency_code`。
- `recharge_amount`：充值金额。
- `gift_amount`：赠送金额。
- `payable_amount`：应付金额。
- `recharge_status`：充值状态。枚举值：
  - `created`：已创建
  - `paying`：支付中
  - `paid`：已支付
  - `credited`：已入账
  - `cancelled`：已取消
  - `failed`：充值失败
  - `refunded`：已退款
- `paid_at`：支付完成时间。
- `credited_at`：入账时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_recharge_order_no (recharge_no)`
- 外键约束：
  - `fk_recharge_order_user (user_id -> user_account.id)`
  - `fk_recharge_order_wallet (wallet_id -> wallet_account.id)`
  - `fk_recharge_order_channel (channel_id -> dim_channel.id)`
  - `fk_recharge_order_currency (currency_code -> dim_currency.currency_code)`
- 业务约束：
  - `user_id` 必须指向状态允许充值的用户。
  - `wallet_id` 对应的钱包账户必须属于当前 `user_id`。
  - `currency_code` 必须与钱包账户币种一致。
  - `channel_id` 必须指向启用渠道。
  - `recharge_amount > 0`
  - `gift_amount >= 0`
  - `payable_amount >= 0`
  - `payable_amount` 通常等于 `recharge_amount`，赠送金额只影响入账金额。
  - `recharge_status in (created, paying)` 时 `paid_at` 和 `credited_at` 必须为空。
  - `recharge_status in (paid, credited, refunded)` 时 `paid_at` 必须不为空。
  - `recharge_status = credited` 时 `credited_at` 必须不为空，并生成 `wallet_ledger` 充值流水。
  - `recharge_status in (cancelled, failed)` 时不得生成入账流水。
  - 金额字段必须符合 `dim_currency.precision_scale` 的精度要求。
  - `paid_at` 不为空时，`paid_at >= created_at`
  - `credited_at` 不为空时，`credited_at >= paid_at`
  - `updated_at >= created_at`

#### `content_order`
内容订单表，维护用户购买 VIP、专辑或章节形成的订单主信息。

- `id`：主键 ID。
- `order_no`：订单号，业务唯一标识。
- `user_id`：用户 ID，关联 `user_account.id`。
- `channel_id`：下单渠道 ID，关联 `dim_channel.id`。
- `currency_code`：币种编码，关联 `dim_currency.currency_code`。
- `order_type`：订单类型。枚举值：
  - `vip`：会员订单
  - `album`：专辑订单
  - `track`：章节订单
  - `bundle`：组合订单
- `order_status`：订单状态。枚举值：
  - `created`：已创建
  - `paid`：已支付
  - `cancelled`：已取消
  - `refunding`：退款中
  - `refunded`：已退款
  - `closed`：已关闭
- `total_amount`：订单总金额。
- `discount_amount`：优惠金额。
- `payable_amount`：应付金额。
- `paid_at`：支付完成时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_order_no (order_no)`
- 外键约束：
  - `fk_content_order_user (user_id -> user_account.id)`
  - `fk_content_order_channel (channel_id -> dim_channel.id)`
  - `fk_content_order_currency (currency_code -> dim_currency.currency_code)`
- 业务约束：
  - `user_id` 必须指向状态允许下单的用户。
  - `channel_id` 必须指向启用渠道。
  - `currency_code` 必须指向启用币种。
  - `order_type = vip` 时订单明细必须且只能包含 `vip_plan` 类型明细。
  - `order_type = album` 时订单明细必须且只能包含 `album` 类型明细。
  - `order_type = track` 时订单明细必须且只能包含 `track` 类型明细。
  - `order_type = bundle` 时订单明细可包含多个不同类型明细。
  - `total_amount >= 0`
  - `discount_amount >= 0`
  - `discount_amount <= total_amount`
  - `payable_amount = total_amount - discount_amount`
  - 金额字段必须符合 `dim_currency.precision_scale` 的精度要求。
  - `order_status = created` 时 `paid_at` 必须为空。
  - `order_status = paid` 时 `paid_at` 不为空。
  - `order_status = cancelled` 时不得再新增成功支付流水。
  - `order_status = refunding` 时必须存在未完结退款单。
  - `order_status = refunded` 时退款成功金额应等于已支付金额。
  - `order_status = closed` 表示订单超时、风控关闭或人工关闭，不得继续支付。
  - 订单支付成功后应生成对应 `entitlement_record`。
  - `created_at >= user_account.created_at`
  - `paid_at` 不为空时，`paid_at >= created_at`
  - `updated_at >= created_at`

#### `content_order_item`
内容订单明细表，维护订单下购买的 VIP 套餐、专辑或章节。

- `id`：主键 ID。
- `order_id`：订单 ID，关联 `content_order.id`。
- `item_type`：明细类型。枚举值：
  - `vip_plan`：VIP 套餐
  - `album`：专辑
  - `track`：章节
- `vip_plan_id`：VIP 套餐 ID，关联 `vip_plan.id`。
- `album_id`：专辑 ID，关联 `audio_album.id`。
- `track_id`：章节 ID，关联 `audio_track.id`。
- `item_name`：明细名称。
- `quantity`：数量。
- `unit_price_amount`：单价。
- `discount_amount`：明细优惠金额。
- `payable_amount`：明细应付金额。
- `item_target_key`：订单明细对象归一化键，由数据库生成，用于规避可空列唯一键失效。
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_content_order_item_target (order_id, item_type, item_target_key)`
- 外键约束：
  - `fk_content_order_item_order (order_id -> content_order.id)`
  - `fk_content_order_item_vip_plan (vip_plan_id -> vip_plan.id)`
  - `fk_content_order_item_album (album_id -> audio_album.id)`
  - `fk_content_order_item_track (track_id -> audio_track.id)`
- 业务约束：
  - `quantity > 0`
  - `item_type = vip_plan` 时 `quantity` 固定为 `1`。
  - `item_type in (album, track)` 时 `quantity` 固定为 `1`，重复购买由权益有效性校验拦截。
  - `unit_price_amount >= 0`
  - `discount_amount >= 0`
  - `discount_amount <= quantity * unit_price_amount`
  - `payable_amount = quantity * unit_price_amount - discount_amount`
  - 金额字段必须与订单币种精度一致。
  - `item_target_key` 由 `item_type` 和对应对象 ID 生成，不允许业务侧手动写入。
  - `item_type = vip_plan` 时 `vip_plan_id` 不为空，`album_id` 和 `track_id` 为空。
  - `item_type = vip_plan` 时 `vip_plan_id` 必须指向启用套餐。
  - `item_type = album` 时 `album_id` 不为空，`vip_plan_id` 和 `track_id` 为空。
  - `item_type = album` 时专辑必须处于可购买状态。
  - `item_type = track` 时 `album_id` 和 `track_id` 不为空，`vip_plan_id` 为空。
  - `item_type = track` 时章节必须处于可购买状态。
  - `track_id` 不为空时，章节必须属于当前 `album_id`。
  - 同一订单内不得重复出现同一购买对象。
  - 明细 `payable_amount` 汇总应等于订单 `payable_amount`。
  - `created_at >= content_order.created_at`

#### `payment_record`
支付流水表，维护内容订单和充值订单的支付发起、成功和失败记录。

- `id`：主键 ID。
- `payment_no`：支付流水号，业务唯一标识。
- `pay_subject_type`：支付对象类型。枚举值：
  - `content_order`：内容订单
  - `recharge_order`：充值订单
- `pay_subject_id`：支付对象 ID。
- `payment_channel`：支付渠道。枚举值：
  - `wechat_pay`：微信支付
  - `alipay`：支付宝
  - `apple_pay`：苹果支付
  - `balance`：余额支付
  - `coupon`：优惠券抵扣
- `currency_code`：币种编码，关联 `dim_currency.currency_code`。
- `payment_amount`：支付金额。
- `payment_status`：支付状态。枚举值：
  - `created`：已创建
  - `processing`：处理中
  - `success`：支付成功
  - `failed`：支付失败
  - `closed`：已关闭
- `paid_at`：支付成功时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_payment_record_no (payment_no)`
- 外键约束：
  - `fk_payment_record_currency (currency_code -> dim_currency.currency_code)`
- 业务约束：
  - `pay_subject_type = content_order` 时 `pay_subject_id` 必须指向 `content_order.id`。
  - `pay_subject_type = recharge_order` 时 `pay_subject_id` 必须指向 `recharge_order.id`。
  - `pay_subject_id` 对应支付对象必须处于允许支付状态。
  - `currency_code` 必须与支付对象的 `currency_code` 一致。
  - `payment_amount >= 0`
  - `payment_amount` 不得大于支付对象剩余待支付金额。
  - 金额字段必须符合 `dim_currency.precision_scale` 的精度要求。
  - 同一支付对象允许存在多条支付流水，但最多只能有一条 `payment_status = success` 的现金支付流水。
  - `payment_channel = coupon` 表示优惠抵扣流水，不作为现金支付渠道。
  - `pay_subject_type = recharge_order` 时 `payment_channel` 只能为 `wechat_pay`、`alipay` 或 `apple_pay`。
  - `pay_subject_type = content_order` 时允许使用余额支付和优惠券抵扣组合支付。
  - `payment_status = created` 或 `processing` 时 `paid_at` 必须为空。
  - `payment_status = success` 时 `paid_at` 不为空。
  - `payment_status in (failed, closed)` 时不得生成权益或钱包入账。
  - 内容订单支付成功后应更新 `content_order.order_status = paid`，写入订单 `paid_at`，并生成对应 `entitlement_record`。
  - 充值订单支付成功后应更新 `recharge_order.recharge_status = paid`，写入 `paid_at`，入账完成后再更新为 `credited` 并生成 `wallet_ledger`。
  - `paid_at` 不为空时，`paid_at >= created_at`
  - `created_at >= 支付对象.created_at`
  - `updated_at >= created_at`

#### `refund_record`
退款单表，维护内容订单和充值订单的退款申请、审核和打款结果。

- `id`：主键 ID。
- `refund_no`：退款单号，业务唯一标识。
- `refund_subject_type`：退款对象类型。枚举值：
  - `content_order`：内容订单
  - `recharge_order`：充值订单
- `refund_subject_id`：退款对象 ID。
- `payment_id`：支付流水 ID，关联 `payment_record.id`。
- `refund_reason`：退款原因。
- `refund_amount`：退款金额。
- `refund_status`：退款状态。枚举值：
  - `requested`：已申请
  - `approved`：已通过
  - `rejected`：已拒绝
  - `success`：退款成功
  - `failed`：退款失败
- `requested_at`：申请时间。
- `handled_at`：审核时间。
- `refunded_at`：退款到账时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_refund_record_no (refund_no)`
- 外键约束：
  - `fk_refund_record_payment (payment_id -> payment_record.id)`
- 业务约束：
  - `refund_subject_type = content_order` 时 `refund_subject_id` 必须指向 `content_order.id`。
  - `refund_subject_type = recharge_order` 时 `refund_subject_id` 必须指向 `recharge_order.id`。
  - `refund_subject_id` 对应退款对象必须处于可退款状态。
  - `payment_id` 必须指向 `payment_status = success` 的支付流水。
  - `payment_id` 对应支付对象必须等于当前退款对象。
  - `refund_amount > 0`
  - `refund_amount <= payment_record.payment_amount`
  - 同一支付流水累计退款金额不得超过 `payment_record.payment_amount`。
  - `refund_subject_type = content_order` 时，退款单必须至少存在一条 `refund_record_item` 明细。
  - `refund_subject_type = recharge_order` 时，退款金额不得超过充值订单未消费且可退金额。
  - 金额字段必须符合退款对象币种精度要求。
  - `refund_status = requested` 时 `handled_at` 和 `refunded_at` 必须为空。
  - `refund_status = approved` 时 `handled_at` 必须不为空，`refunded_at` 可为空。
  - `refund_status = rejected` 时 `handled_at` 必须不为空，`refunded_at` 必须为空。
  - `refund_status = success` 时 `handled_at` 和 `refunded_at` 必须不为空。
  - `refund_status = failed` 时 `handled_at` 必须不为空。
  - 内容订单退款成功后应按退款明细撤销或缩短对应 `entitlement_record`。
  - 充值订单退款成功后应生成钱包扣减流水，并更新 `recharge_order.recharge_status = refunded`。
  - `handled_at` 不为空时，`handled_at >= requested_at`
  - `refunded_at` 不为空时，`refunded_at >= handled_at`
  - `requested_at >= 支付对象.paid_at`
  - `created_at >= 退款对象.created_at`
  - `updated_at >= created_at`

#### `refund_record_item`
退款明细表，维护内容订单按订单明细维度发生的退款对象、退款数量和退款金额。

- `id`：主键 ID。
- `refund_id`：退款单 ID，关联 `refund_record.id`。
- `order_item_id`：订单明细 ID，关联 `content_order_item.id`。
- `item_type`：退款明细类型。枚举值：
  - `vip_plan`：VIP 套餐
  - `album`：专辑
  - `track`：章节
- `refund_quantity`：退款数量。
- `refund_amount`：退款金额。
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_refund_record_item_order_item (refund_id, order_item_id)`
- 外键约束：
  - `fk_refund_record_item_refund (refund_id -> refund_record.id)`
  - `fk_refund_record_item_order_item (order_item_id -> content_order_item.id)`
- 业务约束：
  - `refund_id` 必须指向 `refund_subject_type = content_order` 的退款单。
  - `order_item_id` 必须属于当前退款单对应的 `content_order`。
  - `item_type` 必须与 `content_order_item.item_type` 一致。
  - `refund_quantity > 0`
  - `refund_quantity <= content_order_item.quantity`
  - `refund_amount > 0`
  - `refund_amount <= content_order_item.payable_amount`
  - 同一订单明细累计退款金额不得超过该明细实付金额。
  - 同一退款单下退款明细 `refund_amount` 汇总必须等于 `refund_record.refund_amount`。
  - `item_type = vip_plan` 时退款成功后应按会员有效期消耗情况撤销或缩短会员权益。
  - `item_type = album` 时退款成功后应撤销对应专辑权益。
  - `item_type = track` 时退款成功后应撤销对应章节权益。
  - 金额字段必须符合订单币种精度要求。
  - `created_at >= refund_record.created_at`

#### `entitlement_record`
权益记录表，维护用户因会员、购买、赠送获得的专辑或章节权益。

- `id`：主键 ID。
- `user_id`：用户 ID，关联 `user_account.id`。
- `source_type`：权益来源。枚举值：
  - `vip`：会员权益
  - `purchase`：购买
  - `gift`：赠送
  - `promotion`：活动
- `order_id`：订单 ID，关联 `content_order.id`。
- `target_type`：权益对象类型。枚举值：
  - `vip`：会员
  - `album`：专辑
  - `track`：章节
- `target_id`：权益对象 ID。
- `valid_from`：权益生效时间。
- `valid_to`：权益失效时间。
- `entitlement_status`：权益状态。枚举值：
  - `active`：有效
  - `expired`：已过期
  - `revoked`：已撤销
- `source_key`：权益来源归一化键，由数据库生成，用于规避可空列唯一键失效。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_entitlement_record_key (user_id, target_type, target_id, source_type, source_key)`
- 外键约束：
  - `fk_entitlement_record_user (user_id -> user_account.id)`
  - `fk_entitlement_record_order (order_id -> content_order.id)`
- 业务约束：
  - `target_type = vip` 时 `target_id` 必须指向 `vip_plan.id`。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`。
  - `target_type = track` 时 `target_id` 必须指向 `audio_track.id`。
  - `source_type = purchase` 时 `order_id` 必须不为空，且订单状态必须为 `paid`。
  - `source_type in (gift, promotion)` 时 `order_id` 可以为空，但必须保留外部活动或人工发放审计信息。
  - `source_key` 由 `source_type` 和 `order_id` 生成，不允许业务侧手动写入。
  - `source_type = vip` 时权益有效期应与会员账户有效期一致或落在会员有效期内。
  - `valid_from` 必须不为空。
  - `valid_to` 不为空时，`valid_to > valid_from`
  - `entitlement_status = active` 时当前时间必须落在有效期内，永久权益 `valid_to` 可为空。
  - `entitlement_status = expired` 时 `valid_to <= 当前时间`。
  - `entitlement_status = revoked` 表示退款、风控或人工撤销，不得继续用于播放鉴权。
  - 同一用户同一对象存在多条权益时，以有效期覆盖且状态为 `active` 的记录为准。
  - `created_at >= user_account.created_at`
  - `order_id` 不为空时，订单必须属于当前 `user_id`。
  - 退款成功后，对应购买权益必须置为 `revoked` 或调整有效期。
  - `updated_at >= created_at`

### 运营推荐域
本域用于维护榜单、榜单明细、推荐位、专题和搜索词。

表说明：

- `ranking_list`：榜单表，维护热播榜、新书榜、完结榜、主播榜等榜单定义。
- `ranking_item`：榜单明细表，维护榜单周期内的专辑或主播排名。
- `recommend_slot`：推荐位表，维护首页、分类页、详情页等推荐位。
- `recommend_item`：推荐明细表，维护推荐位上的专辑、主播、专题和链接。
- `content_topic`：内容专题表，维护平台运营专题。
- `content_topic_item`：专题明细表，维护专题下聚合的专辑、主播和榜单入口。
- `search_query_log`：搜索明细日志表，维护每一次搜索请求、搜索类型、结果数和点击对象。
- `search_keyword_stat`：搜索词统计表，维护搜索热词和搜索结果点击数据。

依赖关系说明：

- `ranking_item` 依赖 `ranking_list`，并按对象类型关联专辑或主播。
- `recommend_item` 依赖 `recommend_slot`，并按对象类型关联专辑、主播、专题或外部链接。
- `content_topic -> content_topic_item`：一个专题可聚合多个专辑、主播或榜单入口。
- `search_query_log -> search_keyword_stat`：搜索明细按日期、渠道和关键词聚合为搜索词统计。

#### `ranking_list`
榜单表，定义平台榜单类型、统计周期和展示范围。

- `id`：主键 ID。
- `ranking_code`：榜单编码，业务唯一标识。
- `ranking_name`：榜单名称。
- `ranking_type`：榜单类型。枚举值：
  - `hot_album`：热播专辑榜
  - `new_album`：新书榜
  - `completed_album`：完结榜
  - `paid_album`：畅销榜
  - `narrator`：主播榜
- `category_id`：分类 ID，关联 `dim_audio_category.id`。
- `period_type`：周期类型。枚举值：
  - `daily`：日榜
  - `weekly`：周榜
  - `monthly`：月榜
  - `total`：总榜
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_ranking_list_code (ranking_code)`
- 外键约束：
  - `fk_ranking_list_category (category_id -> dim_audio_category.id)`
- 业务约束：
  - `category_id` 为空时表示全站榜单，不为空时表示分类榜单。
  - `category_id` 不为空时必须指向启用分类。
  - 启用榜单 `yn = 1` 才能生成新的榜单明细和在前端展示。
  - 已产生榜单明细的榜单不得物理删除，只能将 `yn` 置为 `0`。
  - 同一 `ranking_type`、`category_id`、`period_type` 下启用榜单不允许重复。
  - `ranking_type = narrator` 时榜单明细的 `target_type` 只能为 `narrator`。
  - `ranking_type in (hot_album, new_album, completed_album, paid_album)` 时榜单明细的 `target_type` 只能为 `album`。
  - 停用榜单后历史榜单明细保留，用于历史页面和分析。
  - `updated_at >= created_at`

#### `ranking_item`
榜单明细表，维护榜单在某个统计周期内的排名对象。

- `id`：主键 ID。
- `ranking_id`：榜单 ID，关联 `ranking_list.id`。
- `stat_date`：统计日期。
- `target_type`：排名对象类型。枚举值：
  - `album`：专辑
  - `narrator`：主播
- `target_id`：排名对象 ID。
- `rank_no`：排名。
- `score_value`：榜单得分。
- `play_count`：统计周期播放次数。
- `favorite_count`：统计周期收藏次数。
- `order_count`：统计周期订单数。
- `created_at`：创建时间。

- 唯一性约束：
  - `uk_ranking_item_rank (ranking_id, stat_date, rank_no)`
  - `uk_ranking_item_target (ranking_id, stat_date, target_type, target_id)`
- 外键约束：
  - `fk_ranking_item_ranking (ranking_id -> ranking_list.id)`
- 业务约束：
  - `ranking_id` 必须指向启用榜单。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`。
  - `target_type = narrator` 时 `target_id` 必须指向 `content_narrator.id`。
  - `target_type` 必须与 `ranking_list.ranking_type` 的对象范围一致。
  - `stat_date` 的统计粒度必须与 `ranking_list.period_type` 对齐。
  - 同一榜单同一统计日期内 `rank_no` 必须从 `1` 开始递增。
  - 同一榜单同一统计日期内同一对象只能出现一次。
  - `rank_no > 0`
  - `score_value >= 0`
  - `play_count >= 0`
  - `favorite_count >= 0`
  - `order_count >= 0`
  - `ranking_type = hot_album` 时 `score_value` 主要由播放次数、完播率、收藏数综合计算。
  - `ranking_type = new_album` 时目标专辑应为近期上架专辑。
  - `ranking_type = completed_album` 时目标专辑的 `publish_status` 应为 `completed`。
  - `ranking_type = paid_album` 时 `order_count` 应参与榜单得分。
  - `order_count` 只统计支付成功且未全额退款的有效成交订单，不统计创建、取消、关闭、退款中和已全额退款订单。

#### `recommend_slot`
推荐位表，定义首页、分类页、详情页和播放页的运营位。

- `id`：主键 ID。
- `slot_code`：推荐位编码，业务唯一标识。
- `slot_name`：推荐位名称。
- `page_code`：页面编码。枚举值：
  - `home`：首页
  - `category`：分类页
  - `album_detail`：专辑详情页
  - `player`：播放页
  - `search`：搜索页
- `slot_type`：推荐位类型。枚举值：
  - `banner`：焦点图
  - `album_list`：专辑列表
  - `narrator_list`：主播列表
  - `topic_list`：专题列表
  - `rank_entry`：榜单入口
- `max_item_count`：最大展示数量。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_recommend_slot_code (slot_code)`
- 外键约束：
  - 无
- 业务约束：
  - 启用推荐位 `yn = 1` 才能新增启用推荐明细。
  - 已被推荐明细引用的推荐位不得物理删除，只能将 `yn` 置为 `0`。
  - 同一页面 `page_code` 下启用状态的 `slot_code` 必须唯一。
  - `slot_type = banner` 时推荐明细应配置 `image_url`。
  - `slot_type = album_list` 时推荐明细的 `target_type` 优先为 `album`。
  - `slot_type = narrator_list` 时推荐明细的 `target_type` 优先为 `narrator`。
  - `slot_type = topic_list` 时推荐明细的 `target_type` 优先为 `topic`。
  - `slot_type = rank_entry` 时推荐明细的 `target_type` 优先为 `ranking`。
  - `max_item_count > 0`
  - `max_item_count` 表示同一推荐位同一时间最多展示的启用明细数。
  - `updated_at >= created_at`

#### `recommend_item`
推荐明细表，维护推荐位中的专辑、主播、专题、榜单或链接。

- `id`：主键 ID。
- `slot_id`：推荐位 ID，关联 `recommend_slot.id`。
- `target_type`：推荐对象类型。枚举值：
  - `album`：专辑
  - `narrator`：主播
  - `topic`：专题
  - `ranking`：榜单
  - `url`：外部链接
- `target_id`：推荐对象 ID。
- `title`：展示标题。
- `image_url`：展示图片地址。
- `jump_url`：跳转地址。
- `sort_no`：排序号。
- `effective_from`：生效时间。
- `effective_to`：失效时间。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_recommend_item_sort (slot_id, sort_no, effective_from)`
- 外键约束：
  - `fk_recommend_item_slot (slot_id -> recommend_slot.id)`
- 业务约束：
  - `slot_id` 必须指向启用推荐位。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`，且专辑应为用户侧可展示状态。
  - `target_type = narrator` 时 `target_id` 必须指向 `content_narrator.id`，且主播应为启用状态。
  - `target_type = topic` 时 `target_id` 必须指向 `content_topic.id`，且专题应为已发布状态。
  - `target_type = ranking` 时 `target_id` 必须指向 `ranking_list.id`，且榜单应为启用状态。
  - `target_type = url` 时 `jump_url` 必须不为空，`target_id` 可为空。
  - `target_type != url` 时 `target_id` 必须不为空。
  - `title` 为空时使用目标对象标题或名称作为默认展示标题。
  - `yn = 1` 时当前时间必须落在 `effective_from` 和 `effective_to` 定义的有效期内，永久投放 `effective_to` 可为空。
  - 同一推荐位同一排序号下，启用推荐明细的有效期不得重叠。
  - `effective_to` 不为空时，`effective_to > effective_from`
  - 同一推荐位同一生效时间段内 `sort_no` 不得重复。
  - 同一推荐位同一生效时间段内启用明细数量不得超过 `recommend_slot.max_item_count`。
  - 推荐明细过期后不得继续展示，但历史记录保留用于投放分析。
  - `updated_at >= created_at`

#### `content_topic`
内容专题表，维护精彩专题、活动专题和频道专题。

- `id`：主键 ID。
- `topic_code`：专题编码，业务唯一标识。
- `topic_title`：专题标题。
- `topic_type`：专题类型。枚举值：
  - `editorial`：编辑推荐
  - `promotion`：营销活动
  - `category`：分类专题
  - `festival`：节日专题
- `cover_url`：封面地址。
- `summary`：专题简介。
- `topic_status`：专题状态。枚举值：
  - `draft`：草稿
  - `published`：已发布
  - `offline`：已下线
- `published_at`：发布时间。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_topic_code (topic_code)`
- 外键约束：
  - 无
- 业务约束：
  - `topic_status = draft` 时专题仅运营后台可见。
  - `topic_status = published` 时 `published_at` 不为空。
  - `topic_status = published` 时必须至少存在一条启用的 `content_topic_item`。
  - `topic_status = offline` 时用户侧不可见，但历史推荐和统计记录保留。
  - `topic_type = category` 时专题内容应围绕同一分类或相邻分类组织。
  - `topic_type = promotion` 时可关联活动投放，当前表只保存专题展示信息。
  - `cover_url` 在专题发布时不得为空。
  - `published_at` 不为空时，`published_at >= created_at`
  - `updated_at >= created_at`

#### `content_topic_item`
专题明细表，维护专题下展示的专辑、主播和榜单入口。

- `id`：主键 ID。
- `topic_id`：专题 ID，关联 `content_topic.id`。
- `target_type`：专题对象类型。枚举值：
  - `album`：专辑
  - `narrator`：主播
  - `ranking`：榜单
- `target_id`：专题对象 ID。
- `title`：展示标题。
- `summary`：展示摘要。
- `image_url`：展示图片地址。
- `sort_no`：排序号。
- `yn`：是否启用，`1` 表示启用，`0` 表示停用。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_content_topic_item_target (topic_id, target_type, target_id)`
  - `uk_content_topic_item_sort (topic_id, sort_no)`
- 外键约束：
  - `fk_content_topic_item_topic (topic_id -> content_topic.id)`
- 业务约束：
  - `topic_id` 必须指向未物理删除的专题。
  - `target_type = album` 时 `target_id` 必须指向 `audio_album.id`，且专辑应为用户侧可展示状态。
  - `target_type = narrator` 时 `target_id` 必须指向 `content_narrator.id`，且主播应为启用状态。
  - `target_type = ranking` 时 `target_id` 必须指向 `ranking_list.id`，且榜单应为启用状态。
  - 同一专题内同一对象只能出现一次。
  - `sort_no > 0`
  - 同一专题内 `sort_no` 不得重复。
  - `yn = 1` 的明细才参与专题前端展示。
  - `title` 为空时使用目标对象标题或名称作为默认展示标题。
  - 专题下线后明细关系保留，用于再次发布和历史分析。
  - `created_at >= content_topic.created_at`
  - `updated_at >= created_at`

#### `search_query_log`
搜索明细日志表，维护每一次搜索请求、搜索类型、结果数量和点击对象。

- `id`：主键 ID。
- `query_no`：搜索请求编号，业务唯一标识。
- `user_id`：用户 ID，关联 `user_account.id`，未登录搜索为空。
- `channel_id`：渠道 ID，关联 `dim_channel.id`。
- `keyword`：搜索词。
- `search_type`：搜索类型。枚举值：
  - `all`：综合搜索
  - `album`：专辑搜索
  - `book`：书籍搜索
  - `program`：节目搜索
  - `track`：章节搜索
  - `narrator`：主播搜索
  - `organization`：机构搜索
  - `topic`：专题搜索
- `result_count`：搜索结果数量。
- `clicked_flag`：是否点击结果，`1` 表示点击，`0` 表示未点击。
- `clicked_target_type`：点击对象类型。枚举值：
  - `none`：未点击
  - `album`：专辑
  - `track`：章节
  - `narrator`：主播
  - `organization`：机构
  - `topic`：专题
- `clicked_target_id`：点击对象 ID。
- `created_at`：创建时间，即搜索发生时间。

- 唯一性约束：
  - `uk_search_query_log_no (query_no)`
- 外键约束：
  - `fk_search_query_log_user (user_id -> user_account.id)`
  - `fk_search_query_log_channel (channel_id -> dim_channel.id)`
- 业务约束：
  - `channel_id` 必须指向启用或历史有效渠道。
  - `keyword` 去除首尾空格后不得为空。
  - `search_type = book` 时搜索结果对象主要为有声书专辑。
  - `search_type = program` 时搜索结果对象主要为主播节目专辑。
  - `search_type = album` 时搜索结果对象主要为专辑。
  - `search_type = track` 时搜索结果对象主要为章节。
  - `search_type = narrator` 时搜索结果对象主要为主播。
  - `search_type = organization` 时搜索结果对象主要为机构。
  - `search_type = topic` 时搜索结果对象主要为专题。
  - `result_count >= 0`
  - `clicked_flag = 0` 时 `clicked_target_type = none`，`clicked_target_id` 为空。
  - `clicked_flag = 1` 时 `clicked_target_type != none`，`clicked_target_id` 不为空。
  - `clicked_target_type = album` 时 `clicked_target_id` 必须指向 `audio_album.id`。
  - `clicked_target_type = track` 时 `clicked_target_id` 必须指向 `audio_track.id`。
  - `clicked_target_type = narrator` 时 `clicked_target_id` 必须指向 `content_narrator.id`。
  - `clicked_target_type = organization` 时 `clicked_target_id` 必须指向 `content_organization.id`。
  - `clicked_target_type = topic` 时 `clicked_target_id` 必须指向 `content_topic.id`。
  - `created_at` 记录搜索发生时间。
  - 搜索明细可按合规要求对敏感词、隐私词进行脱敏或不入库。

#### `search_keyword_stat`
搜索词统计表，按日期、渠道和搜索词沉淀搜索行为结果。

- `id`：主键 ID。
- `stat_date`：统计日期。
- `channel_id`：渠道 ID，关联 `dim_channel.id`。
- `keyword`：搜索词。
- `search_count`：搜索次数。
- `result_click_count`：搜索结果点击次数。
- `album_click_count`：专辑点击次数。
- `narrator_click_count`：主播点击次数。
- `created_at`：创建时间。
- `updated_at`：更新时间。

- 唯一性约束：
  - `uk_search_keyword_stat_key (stat_date, channel_id, keyword)`
- 外键约束：
  - `fk_search_keyword_stat_channel (channel_id -> dim_channel.id)`
- 业务约束：
  - `channel_id` 必须指向启用或历史有效渠道。
  - `keyword` 去除首尾空格后不得为空。
  - 同一统计日期、渠道、搜索词只能保留一条统计记录。
  - `search_count >= 0`
  - `result_click_count >= 0`
  - `album_click_count >= 0`
  - `narrator_click_count >= 0`
  - `result_click_count <= search_count`
  - `album_click_count` 只聚合 `clicked_target_type = album` 的搜索点击。
  - `narrator_click_count` 只聚合 `clicked_target_type = narrator` 的搜索点击。
  - `clicked_target_type in (track, organization, topic)` 的搜索点击只计入 `result_click_count`，不计入专辑或主播点击数。
  - `album_click_count + narrator_click_count <= result_click_count`
  - `stat_date` 不得晚于数据生成日期。
  - 搜索词大小写、全半角和繁简归一规则由搜索服务统一处理。
  - 低频、敏感或隐私搜索词可按合规规则脱敏、归并或不入库。
  - 当天统计可被重复刷新，历史封账日期的数据不再修改。
  - `updated_at >= created_at`

## 数据生成
### 生成原则
- 分层顺序固定为 `Layer1 -> Layer2 -> Layer3 -> Layer4 -> Layer5 -> Layer6 -> Layer7`，后层只能依赖前层已落库数据。
- 基础维度、内容主体和用户主体优先保证“稳定可回放”，优先从 `seeds` 导入或按固定枚举生成，不在不同批次之间漂移编码口径。
- 所有编码类字段统一使用稳定规则生成，例如 `CAT000001`、`TAG000001`、`USR0000000001`、`ALB0000000001`、`TRK0000000001`、`ORD0000000001`、`PAY0000000001`，保证重复跑批时便于排查。
- 时间字段统一遵循“主表先、子表后；创建时间先、更新时间后；业务发生时间不早于创建时间”的原则，保证外键和业务约束同时成立。
- 内容供给链路必须从机构、作者、主播和创作者主体反推，不生成无版权主体、无主播关系、无可用音频文件却已上架的专辑。
- 播放、互动、收藏、评分、搜索、榜单和推荐数据必须建立在用户侧可展示内容之上，不允许脱离 `audio_album`、`audio_track` 和 `content_narrator` 独立生成。
- 交易权益链路必须从价格规则和可购买内容反推，不生成无法定价、无法支付、无法退款或无法鉴权播放的孤立订单。
- 冗余统计字段由明细数据聚合生成或按明细口径回填，允许模拟异步延迟，但不得与明细数据产生方向性冲突。

### 时间跨度口径
- 时间基准：以脚本运行环境的本地时间为准，取执行当天当前日期为基准日 `T`，不使用数据库服务器时间作为生成基准。
- 种子维度表：如果字段直接来自 `seeds`，则保持种子中的业务编码、排序号和基础时间口径；程序只补齐目标格式，不改写业务含义。
- 基础主体域：`content_organization`、`content_author`、`content_narrator`、`user_account` 的创建时间统一覆盖 `T-1460` 到 `T-30`。
- 内容供给域：`audio_album`、`audio_track`、`track_audio_file`、内容关系表和价格规则的创建时间统一覆盖 `T-1095` 到 `T`，已发布内容的发布时间不得晚于 `T`。
- 用户会员域：`user_profile`、`member_account`、`user_follow`、`user_bookshelf`、`user_preference` 的创建时间统一覆盖 `T-730` 到 `T`，且不得早于对应用户创建时间。
- 交易权益域：充值、内容订单、支付、退款、权益和钱包流水统一覆盖 `T-365` 到 `T`，支付时间不得早于订单创建时间，退款时间不得早于支付成功时间。
- 播放互动域：播放、进度、评论、评分、举报、动态、工单和站内消息数据统一覆盖 `T-365` 到 `T`，只能引用在业务发生时间已创建且用户侧可见的内容、有效权益或真实交易对象。
- 运营推荐域：专题、推荐位、榜单和搜索数据统一覆盖 `T-180` 到 `T`；推荐投放和价格规则允许存在 `effective_to > T` 的未来失效时间，但记录创建时间和更新时间不得晚于 `T`。
- 所有程序生成的 `updated_at` 都必须满足 `created_at <= updated_at <= T`；业务结束时间为空表示仍在有效期或未完结，不使用未来时间伪造终态。

### 时间生成规则
- 全量数据必须按真实业务发生顺序生成时间，不允许把大量业务明细统一写为批次当前时间。
- 每条记录的业务发生时间必须落在其依赖对象已存在且可用之后；例如用户行为不得早于用户注册和内容上架，支付不得早于订单创建，退款不得早于支付成功，权益不得早于支付成功或发放审批完成。
- `created_at` 表示记录在业务系统中首次落库的时间，应接近对应业务事件发生时间；`updated_at` 表示最近一次状态或统计回写时间，应晚于或等于 `created_at`，且不得晚于 `T`。
- 主数据创建时间应呈长期缓慢累积分布；内容上架、章节更新、用户注册、充值、下单、播放、搜索等明细时间应呈周期性和热点分布，不得完全均匀或集中在同一天。
- 用户注册时间应早于该用户的画像、会员账户、关注、书架、偏好、订单、播放、评论、搜索、工单和消息。
- 创作者入驻时间应早于其上传任务、内容审核、专辑上架、章节发布和动态发布时间。
- 专辑创建时间应早于专辑关系、章节、音频文件、上传任务、审核记录、更新记录和价格规则；已发布专辑的 `published_at` 应不早于专辑创建时间且不晚于 `T`。
- 章节发布时间应不早于所属专辑创建时间；音频文件创建时间应不早于章节创建时间；可播放音频文件的创建时间应不晚于首次播放时间。
- 价格规则的 `effective_from` 应不早于专辑创建时间；启用价格规则之间不得在同一专辑上产生有效期重叠。
- 书架、偏好和关注应按用户生命周期生成，首次收藏或关注时间不得早于用户注册、内容上架或被关注对象创建。
- 内容订单、充值订单和支付流水应按“创建订单 -> 发起支付 -> 支付成功或关闭 -> 权益发放或钱包入账”的顺序生成。
- 退款链路应按“支付成功 -> 申请退款 -> 审核处理 -> 退款成功或失败 -> 权益撤销或钱包流水回写”的顺序生成。
- 钱包流水时间必须按同一钱包的业务发生顺序递增，余额字段必须由上一条流水余额和本条变动金额连续推导。
- 播放会话时间必须晚于用户注册、章节发布时间和可播放权益生效时间；收听进度的 `last_played_at` 必须来自该用户对应章节最近一次有效播放时间。
- 评论、评分、点赞、举报和分享应晚于用户可见或可播放内容的时间；评论回复不得早于父评论创建时间。
- 动态、消息和工单时间应与来源事件保持一致；交易消息不得早于订单或支付事件，审核消息不得早于审核记录，工单处理时间不得早于提交时间。
- 榜单统计日期应晚于榜单对象上架或创建时间，并与播放、收藏、订单等明细时间口径一致；榜单明细 `created_at` 应表示统计任务产出时间，不得早于 `stat_date`。
- 推荐投放 `effective_from` 应不早于推荐对象创建或上架时间；同一推荐位同一排序号下启用投放不得出现有效期重叠。
- 搜索日志时间应晚于用户注册时间和渠道启用时间；点击对象存在时，搜索时间不得早于点击对象创建或上架时间。
- 搜索词统计的 `stat_date` 必须由搜索日志的 `created_at` 聚合得到，统计记录创建时间应不早于该统计日期且不晚于 `T`。
- 所有冗余统计字段的更新时间应不早于参与聚合的最新明细时间，且不得早于被回填主表的创建时间。

### 集成执行说明
以下内容按实际执行顺序组织。每个阶段都同时包含：

- 本阶段处理哪些表
- 这些表如何生成
- 具体执行步骤
- 本阶段完成后的检查点

### 阶段 1：Layer1 基础维度与主体主数据
- 目标：导入基础维度，生成用户、机构、作者和主播主体，为内容供给、播放互动和交易链路提供稳定引用。
- 处理表：`dim_audio_category`、`dim_content_tag`、`dim_channel`、`dim_language`、`dim_currency`、`user_account`、`content_organization`、`content_author`、`content_narrator`

表级说明：

- `dim_audio_category`
  - 来源：导入 `seeds/1_foundation/dim_audio_category.csv`。
  - 生成方式：先导入频道，再按 `parent_category_code` 解析一级分类和二级分类，建立三级分类树。
  - 关键约束：`category_code` 唯一；非顶级分类必须能找到父级；父子 `category_type` 必须一致。
- `dim_content_tag`
  - 来源：导入 `seeds/1_foundation/dim_content_tag.csv`。
  - 生成方式：先导入标签组，再导入题材、风格、场景、适听人群和专题主题标签。
  - 关键约束：`tag_code` 唯一；子标签必须能找到父标签；同一父标签下启用标签名称不重复。
- `dim_channel`
  - 来源：导入 `seeds/1_foundation/dim_channel.csv`。
  - 生成方式：官网 Web 渠道来自懒人听书站点，其余 App、小程序、车载端和合作渠道按业务常用渠道兜底生成。
  - 关键约束：`channel_code` 唯一；启用渠道覆盖注册、播放、下单、支付和搜索场景。
- `dim_language`
  - 来源：导入 `seeds/1_foundation/dim_language.csv`。
  - 生成方式：站点公开页面没有稳定语言维表时，按内容业务常用语言兜底生成普通话、粤语和英语。
  - 关键约束：`language_code` 唯一；启用语言必须能覆盖全部内容样本。
- `dim_currency`
  - 来源：导入 `seeds/1_foundation/dim_currency.csv`。
  - 生成方式：站点公开页面没有稳定币种维表时，按交易业务默认币种兜底生成人民币。
  - 关键约束：`currency_code` 唯一；金额精度必须被价格、订单、支付和退款复用。
- `user_account`
  - 来源：程序生成。
  - 生成方式：按渠道生成普通用户、会员用户、创作者用户和少量受限用户，手机号、邮箱和账号状态分布稳定。
  - 关键约束：手机号、邮箱和用户编号唯一；账号状态必须与后续播放、互动、下单权限一致。
- `content_organization`
  - 来源：优先导入站点爬取的 `seeds/1_foundation/content_organization.csv`，缺失时程序补齐。
  - 生成方式：导入版权方、出版方、制作方、MCN 和平台自营机构；缺失的组织类型按专辑关系需要补齐。
  - 关键约束：`organization_code` 唯一；平台自营机构至少一条；启用机构才能被新建主播和专辑引用。
- `content_author`
  - 来源：优先导入站点爬取的 `seeds/2_content/content_author.csv`，缺失时程序补齐。
  - 生成方式：从专辑详情页导入原著作者；专辑需要但站点未提供的编剧、栏目作者和匿名作者由程序补齐。
  - 关键约束：`author_code` 唯一；同一启用作者名称和作者类型组合不重复。
- `content_narrator`
  - 来源：优先导入站点爬取的 `seeds/2_content/content_narrator.csv`，缺失时程序补齐。
  - 生成方式：从专辑详情页、主播主页和首页主播推荐导入主播；缺失的签约类型、所属机构和运营状态由程序补齐。
  - 关键约束：`narrator_code` 唯一；所属机构必须存在；关注数和专辑数初始值不得为负。

Checklist：

- [x] 导入全部基础维度表。
- [x] 生成用户账号、内容机构、作者和主播主体。
- [x] 确认分类树、标签树、渠道、语言和币种均满足唯一性和启用状态约束。
- [x] 确认机构、作者、主播编码唯一且可被内容供给域引用。
- [x] 执行 Layer1 层级、唯一性、启用状态和主体覆盖度校验。

### 阶段 2：Layer2 内容供给与内容资产
- 目标：生成创作者档案、专辑、章节、音频文件、内容关系、上传审核记录和价格规则，形成用户侧可浏览、可播放、可购买的内容资产。
- 处理表：`creator_profile`、`creator_apply_record`、`audio_album`、`album_organization_rel`、`album_author_rel`、`album_narrator_rel`、`album_tag_rel`、`audio_track`、`track_audio_file`、`content_upload_task`、`content_audit_record`、`album_update_record`、`album_price_rule`
- 阶段内顺序：先生成创作者档案和申请记录，再生成专辑、内容关系、章节、音频文件、上传任务、内容审核记录、专辑更新记录和价格规则。

表级说明：

- `creator_profile`
  - 来源：程序生成。
  - 生成方式：从主播用户、机构账号和官方账号中生成创作者档案，并绑定主播或机构。
  - 关键约束：`creator_no` 唯一；同一用户最多一条创作者档案；认证通过创作者必须有入驻时间。
- `creator_apply_record`
  - 来源：程序生成。
  - 生成方式：为创作者入驻、主播认证、机构认证和签约升级生成申请过程记录。
  - 关键约束：首次入驻申请 `creator_id` 可为空；审核通过后必须创建或更新创作者档案；同一用户同一申请类型不能存在多条未完结申请。
- `audio_album`
  - 来源：优先导入站点爬取的 `seeds/2_content/audio_album.csv`，缺失时程序补齐。
  - 生成方式：从书籍详情页和节目详情页导入有声书、主播节目等专辑主档；播客、电台和知识课程等站点样本不足类型按分类比例补齐。
  - 关键约束：已发布专辑必须有封面、简介、分类、语言、主讲主播、已发布章节和上架时间。
- `album_organization_rel`
  - 来源：程序生成。
  - 生成方式：为专辑生成版权方、出版方、出品方、制作方、发行方、来源平台和 MCN 关系。
  - 关键约束：已上架专辑至少存在一个有效的版权方、出品方、制作方或平台自营机构关系。
- `album_author_rel` / `album_narrator_rel` / `album_tag_rel`
  - 来源：程序生成。
  - 生成方式：按专辑类型挂接作者、主播和标签，有声书优先生成原著作者，节目和播客优先生成主持或主讲主播。
  - 关键约束：已上架专辑必须至少存在一名主讲或主持主播；标签必须启用；同一专辑下关系不重复。
- `audio_track`
  - 来源：优先导入站点爬取的 `seeds/2_content/audio_track.csv`，缺失时程序补齐。
  - 生成方式：从专辑详情页和章节分页接口导入章节清单；站点未公开的预告、番外、直播回放、音频时长和文件信息由程序补齐。
  - 关键约束：同一专辑下 `track_no` 唯一；已上架章节必须有发布时间和可用音频文件。
- `track_audio_file`
  - 来源：程序生成。
  - 生成方式：为章节生成 MP3、M4A 或 AAC 音频文件，并按码率生成多个可播放版本。
  - 关键约束：同一章节同一格式同一码率只保留一条当前文件；可用文件必须有地址、大小和时长。
- `content_upload_task`
  - 来源：程序生成。
  - 生成方式：为专辑资料、章节资料、音频文件、封面和批量章节生成上传处理过程。
  - 关键约束：处理完成任务必须关联处理结果对象；失败任务必须记录失败原因。
- `content_audit_record`
  - 来源：程序生成。
  - 生成方式：围绕已生成的专辑、章节、音频文件、上传任务和创作者档案生成机审、人工审核和申诉复核记录；本阶段不生成评论审核记录。
  - 关键约束：审核对象必须真实存在且已在本阶段前序步骤生成；审核终态必须写入审核时间；拒绝、需修改和封禁必须写入原因。
- `album_update_record`
  - 来源：程序生成。
  - 生成方式：按专辑上架、章节发布、批量发布、恢复更新、暂停更新、完结和下架生成更新事件。
  - 关键约束：章节发布事件必须绑定章节；更新事件时间不得早于专辑创建时间。
- `album_price_rule`
  - 来源：程序生成。
  - 生成方式：按专辑类型生成全本免费、会员免费、整本付费、章节付费和限时免费价格规则。
  - 关键约束：同一专辑同一时间点只能有一条启用价格规则生效；金额精度必须符合币种配置。

Checklist：

- [x] 生成创作者档案。
- [x] 生成创作者申请记录。
- [x] 生成专辑、机构关系、作者关系、主播关系和标签关系。
- [x] 生成章节、音频文件和上传任务。
- [x] 生成内容审核记录和专辑更新记录。
- [x] 生成价格规则。
- [x] 执行 Layer2 上架条件、内容关系、音频文件可用性、价格规则和时间顺序校验。

### 阶段 3：Layer3 用户会员与内容偏好
- 目标：基于用户和内容资产生成会员账户、关注关系、书架和偏好，为交易、播放、互动和推荐提供用户侧上下文。
- 处理表：`user_profile`、`member_account`、`user_follow`、`user_bookshelf`、`user_preference`
- 阶段内顺序：先生成用户画像和会员账户初始记录，再生成关注关系、书架基础记录和用户基础偏好；会员有效状态、完播书架和行为偏好由后续交易与播放阶段回写。

表级说明：

- `user_profile`
  - 来源：程序生成。
  - 生成方式：为用户生成性别、生日、地区、职业和常用收听场景画像。
  - 关键约束：`user_id` 唯一；生日早于画像创建时间；城市不为空时省份必须不为空。
- `member_account`
  - 来源：程序生成。
  - 生成方式：为用户初始化普通会员账户，允许生成少量历史已过期或冻结会员账户；生效中的 VIP/SVIP 状态和有效期由 Layer4 会员订单、会员权益或明确授权记录回写。
  - 关键约束：每个用户最多一条会员账户；生效会员必须能回溯到有效会员权益或明确授权记录；积分和成长值不得为负。
- `user_follow`
  - 来源：程序生成。
  - 生成方式：按用户兴趣关注主播、作者和机构，并生成少量取消关注记录。
  - 关键约束：同一用户对同一对象只保留一条关注关系；被关注对象必须存在。
- `user_bookshelf`
  - 来源：程序生成。
  - 生成方式：从已发布专辑中抽样生成收藏、订阅和移除记录，并按可展示章节回填最近收听章节与基础位置；完播状态由 Layer5 收听进度生成后回填。
  - 关键约束：书架专辑必须用户侧可见；最近收听章节必须属于当前专辑；基础位置不得超过章节时长；本阶段不直接生成 `shelf_status = finished`。
- `user_preference`
  - 来源：程序生成。
  - 生成方式：基于用户画像、收听场景、关注、收藏和订阅生成分类偏好、标签偏好和播放设置；播放行为偏好由 Layer5 播放会话和收听进度生成后增量回填。
  - 关键约束：分类偏好只填 `category_id`；标签偏好只填 `tag_id`；播放设置写入 JSON 配置；本阶段不得依赖尚未生成的播放行为。
Checklist：

- [x] 生成用户画像和会员账户。
- [x] 生成关注关系、书架基础记录和用户基础偏好。
- [x] 回填主播关注数、专辑收藏数和用户侧偏好权重。
- [x] 执行 Layer3 用户状态、对象存在性、书架进度和偏好互斥校验。

### 阶段 4：Layer4 交易、支付、退款与权益
- 目标：基于价格规则、会员套餐、钱包账户和用户行为生成充值、订单、支付、退款、权益和钱包流水闭环，为付费播放和交易类服务工单提供前置数据。
- 处理表：`vip_plan`、`wallet_account`、`recharge_order`、`content_order`、`content_order_item`、`payment_record`、`refund_record`、`refund_record_item`、`entitlement_record`、`wallet_ledger`
- 阶段内顺序：先生成 VIP 套餐和钱包账户，再生成充值订单、内容订单和订单明细；支付成功后生成权益和钱包流水；退款单生成后再生成退款明细，并按退款结果撤销权益、回写订单、会员账户和钱包状态。

表级说明：

- `vip_plan`
  - 来源：导入 `seeds/4_trade/vip_plan.csv`。
  - 生成方式：站点公开页面无法稳定获取会员套餐时，按听书平台常用售卖周期兜底生成 VIP 和 SVIP 月卡、季卡、年卡等会员套餐及权益配置。
  - 关键约束：套餐编码唯一；销售价不大于划线价；权益配置必须为合法 JSON。
- `wallet_account`
  - 来源：程序生成。
  - 生成方式：为用户按币种生成钱包账户，覆盖正常、冻结和关闭状态。
  - 关键约束：同一用户同一币种唯一；可用余额等于总余额减冻结金额。
- `recharge_order`
  - 来源：程序生成。
  - 生成方式：从钱包账户生成充值订单，覆盖创建、支付中、已支付、已入账、取消、失败和退款状态。
  - 关键约束：充值订单币种必须与钱包账户一致；已入账充值必须生成钱包充值流水。
- `content_order` / `content_order_item`
  - 来源：程序生成。
  - 生成方式：从 VIP 套餐、可购买专辑和可购买章节中生成会员订单、专辑订单、章节订单和组合订单。
  - 关键约束：订单类型与明细类型一致；订单金额等于明细汇总；同一订单内不重复购买同一对象。
- `payment_record`
  - 来源：程序生成。
  - 生成方式：为充值订单生成微信、支付宝和 Apple Pay 支付流水；为内容订单生成微信、支付宝、Apple Pay 或余额支付流水。
  - 关键约束：充值订单只能使用现金支付渠道；余额支付必须在支付发生时具备足额可用余额；支付币种与支付对象一致；同一支付对象最多一条成功现金支付流水。
- `refund_record`
  - 来源：程序生成。
  - 生成方式：对已成功支付的内容订单和充值订单抽样生成退款单，内容订单先生成申请态退款单和退款明细，再进入通过、驳回、成功或失败状态。
  - 关键约束：退款对象必须与支付对象一致；累计退款金额不得超过成功支付金额；内容订单退款终态必须已经具备退款明细。
- `refund_record_item`
  - 来源：程序生成。
  - 生成方式：为内容订单退款单生成明细级退款对象，支持 VIP、专辑和章节的部分退款。
  - 关键约束：退款明细必须属于当前退款单对应的内容订单；明细退款金额汇总必须等于退款单金额。
- `entitlement_record`
  - 来源：程序生成。
  - 生成方式：内容订单支付成功后生成会员、专辑或章节权益；退款成功后撤销或缩短对应权益。
  - 关键约束：会员权益 `target_id` 指向 `vip_plan.id`；购买权益必须关联已支付内容订单；会员权益生成或变更后必须同步回写 `member_account` 的等级、状态和有效期。
- `wallet_ledger`
  - 来源：程序生成。
  - 生成方式：由充值入账、余额消费、退款入账、充值退款扣减、冻结、解冻和人工调整反推钱包流水。
  - 关键约束：按 `wallet_id + created_at + id` 排序后余额连续；余额、冻结金额和可用余额不得为负；流水币种与钱包账户一致。

Checklist：

- [x] 生成 VIP 套餐和钱包账户。
- [x] 生成充值订单、内容订单和订单明细。
- [x] 生成支付流水，并按成功支付生成权益记录和钱包流水。
- [x] 生成退款单、退款明细和退款结果，并按退款结果撤销权益或生成退款钱包流水。
- [x] 回写会员账户有效期、钱包余额和订单状态。
- [x] 执行 Layer4 金额闭环、支付对象匹配、退款明细汇总、权益有效性和钱包余额连续性校验。

### 阶段 5：Layer5 播放互动、服务与站内消息
- 目标：基于真实用户、专辑、章节和权益口径生成播放会话、收听进度、评论、评分、互动、举报、动态、客服工单和站内消息。
- 处理表：`play_session`、`listening_progress`、`content_comment`、`content_rating`、`user_reaction`、`content_report`、`user_activity_feed`、`support_ticket`、`user_message`
- 阶段内顺序：先生成播放会话和收听进度，再回填书架完播状态和行为偏好；随后生成评论、评分、互动、举报，最后生成动态、客服工单和站内消息。

表级说明：

- `play_session`
  - 来源：程序生成。
  - 生成方式：从可播放章节中按用户、渠道、权益状态生成完整播放、中断播放和失败播放会话。
  - 关键约束：播放章节必须已发布；付费章节必须满足免费规则、会员权益、专辑权益、章节权益或试看规则；播放时长和进度不得越界。
- `listening_progress`
  - 来源：程序生成。
  - 生成方式：按用户和章节聚合最近一次有效播放，生成最新收听位置和完播状态。
  - 关键约束：同一用户同一章节只保留一条进度；完播标记与进度比例一致；生成后按专辑完播口径回填 `user_bookshelf.shelf_status = finished`。
- `content_comment`
  - 来源：程序生成。
  - 生成方式：围绕专辑和章节生成评论和回复，覆盖待审核、已通过和已拒绝状态。
  - 关键约束：父评论与子评论目标对象一致；评论内容不为空；回复链不得循环。
- `content_rating`
  - 来源：程序生成。
  - 生成方式：对有播放、收藏、订阅、购买或会员可听记录的用户生成专辑评分。
  - 关键约束：同一用户同一专辑只保留一条评分；评分范围为 `1-10`。
- `user_reaction`
  - 来源：程序生成。
  - 生成方式：对专辑、章节、评论和主播生成点赞、点踩、分享和转发记录。
  - 关键约束：同一用户对同一对象同一互动类型唯一；点赞和点踩不能同时保持有效；评论互动必须引用本阶段已生成的评论。
- `content_report`
  - 来源：程序生成。
  - 生成方式：从用户可见的专辑、章节、评论和主播中抽样生成举报与处理结果。
  - 关键约束：举报对象必须存在；评论举报必须引用本阶段已生成的评论；未处理举报不得写入处理时间；成立举报可联动内容隐藏或下架。
- `user_activity_feed`
  - 来源：程序生成。
  - 生成方式：从专辑上架、章节发布、专辑更新、关注和系统动态中生成创作者主页和用户主页动态。
  - 关键约束：动态主体用户或创作者至少一个不为空；动态目标类型必须与动态类型匹配；本阶段不生成 `target_type = topic` 的动态。
- `support_ticket`
  - 来源：程序生成。
  - 生成方式：围绕功能反馈、版权投诉、支付问题、账号问题、内容问题和其他问题生成客服工单。
  - 关键约束：未登录工单必须填写手机号或邮箱；支付问题可关联内容订单、充值订单、支付流水或退款单；关联举报记录时举报必须已生成。
- `user_message`
  - 来源：程序生成。
  - 生成方式：生成系统通知、审核通知、交易通知、活动通知、工单通知和少量私信，关联专辑、章节、评论、内容订单、充值订单、上传任务或工单。
  - 关键约束：接收用户必须存在；非私信可为空发送人；关联对象类型与 `target_id` 必须匹配；关联评论、订单、上传任务或工单时源对象必须已生成且状态可见。

Checklist：

- [x] 生成播放会话和收听进度。
- [x] 回填书架完播状态和行为偏好。
- [x] 生成评论、评分、互动和举报。
- [x] 生成用户动态、客服工单和站内消息。
- [x] 回填专辑播放数、章节播放数、评论点赞数和评分均值。
- [x] 执行 Layer5 播放鉴权、进度边界、互动唯一性、审核状态、工单状态和消息关联对象校验。

### 阶段 6：Layer6 运营推荐与搜索统计
- 目标：基于内容资产、播放互动、交易和搜索行为生成榜单、推荐位、专题、搜索日志和搜索词统计。
- 处理表：`ranking_list`、`recommend_slot`、`content_topic`、`ranking_item`、`content_topic_item`、`recommend_item`、`search_query_log`、`search_keyword_stat`

表级说明：

- `ranking_list`
  - 来源：导入站点爬取的 `seeds/6_operation/ranking_list.csv`。
  - 生成方式：从榜单页导入热播榜、畅销榜、完结榜及周榜、月榜、总榜定义；站点未公开的分类榜单由程序补齐。
  - 关键约束：同一榜单类型、分类和周期下启用榜单不重复。
- `recommend_slot`
  - 来源：导入站点爬取的 `seeds/6_operation/recommend_slot.csv`。
  - 生成方式：从首页导入每日推荐、热门节目、主播推荐、精彩专题和机构热书推荐位；其他页面推荐位由程序补齐。
  - 关键约束：推荐位编码唯一；启用推荐位最大展示数量大于 `0`。
- `content_topic`
  - 来源：导入站点爬取的 `seeds/6_operation/content_topic.csv`。
  - 生成方式：从首页专题入口和专题详情页导入专题主档；缺失的营销活动、分类专题和节日专题由程序补齐。
  - 关键约束：已发布专题必须有封面、发布时间和启用专题明细；无明细专题只能保持草稿或下线状态。
- `ranking_item`
  - 来源：优先导入站点爬取的 `seeds/6_operation/ranking_item.csv`，缺失时程序补齐。
  - 生成方式：从榜单页导入榜单明细和排名；站点未公开的统计日期、分类榜、主播榜和指标值由程序根据播放、收藏、评分、完播率和有效成交订单数补齐。
  - 关键约束：榜单对象类型必须与榜单类型一致；同一榜单同一统计日期排名连续且对象不重复；订单数只统计支付成功且未全额退款的有效成交订单。
- `content_topic_item`
  - 来源：优先导入站点爬取的 `seeds/6_operation/content_topic_item.csv`，缺失时程序补齐。
  - 生成方式：从专题详情页导入专题书籍明细；缺失的主播、榜单入口和运营排序由程序补齐。
  - 关键约束：同一专题内同一对象不重复；排序号不重复。
- `recommend_item`
  - 来源：优先导入站点爬取的 `seeds/6_operation/recommend_item.csv`，缺失时程序补齐。
  - 生成方式：从首页导入每日推荐、热门节目、主播推荐和精彩专题明细；站点未公开的榜单入口、外部链接和其他页面投放由程序补齐。
  - 关键约束：投放对象必须存在且可展示；同一推荐位同一生效时间段内排序号不重复；启用明细不超过推荐位上限。
- `search_query_log`
  - 来源：程序生成。
  - 生成方式：按用户、渠道和关键词生成综合搜索、书籍搜索、节目搜索和主播搜索日志，并抽样生成点击对象。
  - 关键约束：未点击时点击对象为空；点击时对象必须存在；用于搜索词统计聚合的点击对象限定为专辑和主播；`created_at` 表示搜索发生时间。
- `search_keyword_stat`
  - 来源：程序聚合。
  - 生成方式：按 `stat_date + channel_id + keyword` 聚合搜索次数、结果点击次数、专辑点击次数和主播点击次数。
  - 关键约束：搜索次数不得小于点击次数；`album_click_count` 只聚合 `clicked_target_type = album` 的日志，`narrator_click_count` 只聚合 `clicked_target_type = narrator` 的日志，其他点击类型只计入 `result_click_count`。

Checklist：

- [x] 生成榜单定义、推荐位和内容专题草稿。
- [x] 生成榜单明细和专题明细。
- [x] 回写专题发布状态并生成推荐明细。
- [x] 生成搜索日志并聚合搜索词统计。
- [x] 执行 Layer6 榜单对象、推荐投放、专题发布、搜索点击对象和统计汇总校验。

### 阶段 7：最终验收
- 目标：对全量生成数据进行最终验收，不重复执行 Layer1 到 Layer6 的阶段内细粒度检查。
- 验收范围：全库数据。

最终验收项：

- 关键表非空：确认基础维度、内容供给、用户会员、播放互动、交易权益和运营推荐核心表均非空。
- 全局唯一性：确认分类编码、标签编码、用户编号、专辑编码、章节文件编码、上传编号、审核编号、订单号、支付号、退款号、榜单编码、推荐位编码、专题编码和搜索请求编号无重复。
- 跨域外键完整性：确认用户、内容、播放、交易、权益、推荐和搜索之间的外键引用全部闭环。
- 内容上架闭环：确认已发布专辑具备分类、语言、主播、章节、可用音频文件、价格规则和必要版权机构关系。
- 播放鉴权闭环：确认付费章节的完整播放能回溯到免费规则、会员权益、专辑权益或章节权益。
- 金额闭环成立：确认内容订单、充值订单、支付流水、退款单、退款明细、钱包流水和钱包余额之间金额关系全部成立。
- 权益状态一致：确认支付成功生成权益，退款成功撤销或缩短权益，会员账户有效期与会员权益一致。
- 运营统计一致：确认专辑播放数、收藏数、评分、榜单指标和搜索词统计能由明细数据解释。
- 时间顺序正确：确认创建时间、更新时间、上架时间、播放时间、支付时间、退款时间、权益有效期、推荐投放时间和统计日期整体有序。

Checklist：

- [x] 执行关键表非空校验。
- [x] 执行业务唯一键校验。
- [x] 执行跨域外键完整性校验。
- [x] 执行内容上架闭环校验。
- [x] 执行播放鉴权闭环校验。
- [x] 执行交易金额闭环校验。
- [x] 执行权益状态一致性校验。
- [x] 执行运营统计一致性校验。
- [x] 执行全局时间顺序校验。

## 接口定义
### 公共约定
所有接口统一返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

错误响应使用同一结构：

```json
{
  "code": "INVALID_USER_ID",
  "message": "X-User-Id 必须为合法数字",
  "data": null
}
```

鉴权约定：

- 用户身份统一从请求头 `X-User-Id` 读取，值为 `user_account.id`。
- 需要用户身份的接口必须校验 `X-User-Id` 为合法数字，且对应 `user_account.account_status = normal`。
- 公共内容浏览、搜索、榜单、专题、推荐和主播主页接口允许不传 `X-User-Id`。
- 公共接口传入合法 `X-User-Id` 时，应返回当前用户相关状态，例如是否收藏、是否订阅、是否关注、是否已评分、是否有可播放权益、最近播放进度。
- `POST /api/v1/payment-notifications/mock` 不读取 `X-User-Id`，只校验 `X-Demo-Payment-Signature`。

分页约定：

- `pageNo` 从 `1` 开始，默认 `1`。
- `pageSize` 默认 `20`，服务端限制为 `1` 到 `100`。
- 分页响应统一包含 `list`、`pageNo`、`pageSize`、`total`。

金额与时间约定：

- 金额字段返回 number，保留两位小数语义。
- 日期时间格式为 `YYYY-MM-DD HH:mm:ss`。
- 日期格式为 `YYYY-MM-DD`。
- 写接口的业务时间由应用程序按 `Asia/Shanghai` 本地时间生成，不使用数据库当前时间函数。

### 业务链路返回约定
听书平台接口围绕内容浏览、播放鉴权、交易权益和用户行为形成可追溯链路。

核心链路：

```text
audio_album -> audio_track -> track_audio_file
content_order -> content_order_item -> payment_record -> entitlement_record
payment_record -> refund_record -> refund_record_item
wallet_account -> recharge_order -> payment_record -> wallet_ledger
user_account -> play_session -> listening_progress -> user_bookshelf
user_account -> content_comment -> user_reaction -> content_report
```

公共内容接口在带 `X-User-Id` 时返回用户态信息：

- `favorited`：当前用户是否收藏该专辑。
- `subscribed`：当前用户是否订阅该专辑。
- `following`：当前用户是否关注主播、作者或机构。
- `rated` 和 `ratingScore`：当前用户是否评分以及评分值。
- `entitled` 和 `entitlementType`：当前用户是否具备完整播放权益以及权益来源。
- `lastTrackId` 和 `lastPositionSeconds`：当前用户最近收听位置。

内容订单、支付、退款和工单接口应尽量返回上下游摘要：

```json
{
  "orderId": 70001,
  "orderNo": "ORD000000000001",
  "orderType": "album",
  "orderStatus": "paid",
  "payableAmount": 19.9,
  "items": [],
  "payments": [],
  "refunds": [],
  "entitlements": []
}
```

### 1. 公共内容浏览
#### 1.1 `GET /api/v1/categories`
说明：查询启用的音频分类树。

请求头：`X-User-Id` 可选。

查询参数：

- `categoryType`：分类类型，支持 `audiobook`、`program`、`podcast`、`radio`、`course`。

返回字段：

```json
{
  "categories": [
    {
      "categoryId": 1,
      "categoryCode": "CAT000001",
      "categoryName": "有声小说",
      "categoryLevel": 1,
      "categoryType": "audiobook",
      "children": []
    }
  ]
}
```

行为：只返回 `yn = 1` 的分类，按 `category_level asc, sort_no asc, id asc` 排序并组装树。

#### 1.2 `GET /api/v1/tags`
说明：查询启用的内容标签树。

请求头：`X-User-Id` 可选。

查询参数：

- `tagType`：标签类型，支持 `genre`、`style`、`scene`、`audience`、`topic`。

返回字段：

```json
{
  "tags": [
    {
      "tagId": 1,
      "tagCode": "TAG000001",
      "tagName": "悬疑推理",
      "tagType": "genre",
      "children": []
    }
  ]
}
```

行为：只返回 `yn = 1` 的标签，按 `sort_no asc, id asc` 排序并组装树。

#### 1.3 `GET /api/v1/albums`
说明：分页查询用户侧可展示专辑。

请求头：`X-User-Id` 可选。

查询参数：

- `categoryId`：分类 ID。
- `tagId`：标签 ID。
- `albumType`：专辑类型，支持 `audiobook`、`program`、`podcast`、`radio`、`course`。
- `priceType`：价格类型，支持 `free`、`vip_free`、`album_paid`、`track_paid`、`limited_free`。
- `publishStatus`：发布进度状态，支持 `serializing`、`completed`、`unknown`。
- `sortBy`：排序方式，支持 `popular`、`newest`、`rating`、`favorite`。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {
      "albumId": 10001,
      "albumCode": "ALB0000000001",
      "albumTitle": "长篇有声小说",
      "albumType": "audiobook",
      "coverUrl": "https://example.com/cover.jpg",
      "categoryName": "悬疑",
      "languageCode": "zh-CN",
      "publishStatus": "serializing",
      "trackCount": 120,
      "freeTrackCount": 5,
      "playCount": 382190,
      "favoriteCount": 10230,
      "ratingScore": 8.9,
      "priceType": "vip_free",
      "albumPriceAmount": 0.0,
      "primaryNarrator": {"narratorId": 20001, "narratorName": "主播一号"},
      "primaryAuthor": {"authorId": 30001, "authorName": "作者一号"},
      "favorited": true,
      "subscribed": true,
      "entitled": true,
      "lastTrackId": 50001,
      "lastPositionSeconds": 620
    }
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回 `album_status = published` 的专辑；未传 `X-User-Id` 时用户态字段返回 `false` 或 `null`；排序默认 `play_count desc, id desc`。

#### 1.4 `GET /api/v1/albums/{albumId}`
说明：查询专辑详情。

请求头：`X-User-Id` 可选。

路径参数：`albumId`。

返回字段：

```json
{
  "album": {
    "albumId": 10001,
    "albumCode": "ALB0000000001",
    "albumTitle": "长篇有声小说",
    "albumType": "audiobook",
    "coverUrl": "https://example.com/cover.jpg",
    "summary": "专辑简介",
    "category": {"categoryId": 10, "categoryName": "悬疑"},
    "languageCode": "zh-CN",
    "publishStatus": "serializing",
    "publishedAt": "2026-01-01 10:00:00",
    "trackCount": 120,
    "totalDurationSeconds": 360000,
    "playCount": 382190,
    "favoriteCount": 10230,
    "ratingScore": 8.9
  },
  "authors": [{"authorId": 30001, "authorName": "作者一号", "authorRole": "original_author"}],
  "narrators": [{"narratorId": 20001, "narratorName": "主播一号", "narratorRole": "main"}],
  "tags": [{"tagId": 1, "tagName": "悬疑推理"}],
  "priceRule": {
    "priceType": "vip_free",
    "freeTrackCount": 5,
    "albumPriceAmount": 0.0,
    "trackPriceAmount": 0.99,
    "vipFreeFlag": true
  },
  "userState": {
    "favorited": true,
    "subscribed": true,
    "rated": true,
    "ratingScore": 9.0,
    "entitled": true,
    "entitlementType": "vip",
    "lastTrackId": 50001,
    "lastPositionSeconds": 620
  }
}
```

行为：专辑不存在或未发布时返回 `ALBUM_NOT_FOUND`；当前启用价格规则取 `yn = 1` 且当前时间在生效区间内的记录。

#### 1.5 `GET /api/v1/albums/{albumId}/tracks`
说明：分页查询专辑章节。

请求头：`X-User-Id` 可选。

路径参数：`albumId`。

查询参数：

- `sort`：排序方式，支持 `asc`、`desc`，默认 `asc`。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {
      "trackId": 50001,
      "trackNo": 1,
      "trackTitle": "第 1 章",
      "durationSeconds": 1800,
      "freeFlag": 1,
      "trackStatus": "published",
      "publishedAt": "2026-01-01 10:00:00",
      "playCount": 12090,
      "needPurchase": false,
      "canPlayFull": true,
      "trialEndSeconds": 0,
      "lastPositionSeconds": 620,
      "finishedFlag": 0
    }
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回 `track_status = published` 的章节；`canPlayFull` 按免费规则、会员权益、专辑权益和章节权益计算。

#### 1.6 `GET /api/v1/tracks/{trackId}`
说明：查询章节详情。

请求头：`X-User-Id` 可选。

路径参数：`trackId`。

返回字段：

```json
{
  "track": {
    "trackId": 50001,
    "albumId": 10001,
    "trackNo": 1,
    "trackTitle": "第 1 章",
    "durationSeconds": 1800,
    "freeFlag": 1,
    "trialSeconds": 0,
    "publishedAt": "2026-01-01 10:00:00",
    "playCount": 12090
  },
  "album": {"albumId": 10001, "albumTitle": "长篇有声小说", "coverUrl": "https://example.com/cover.jpg"},
  "userState": {"canPlayFull": true, "needPurchase": false, "trialEndSeconds": 0, "lastPositionSeconds": 620, "finishedFlag": 0}
}
```

行为：章节不存在、章节未发布或所属专辑未发布时返回 `TRACK_NOT_FOUND`。

#### 1.7 `GET /api/v1/narrators/{narratorId}`
说明：查询主播主页。

请求头：`X-User-Id` 可选。

路径参数：`narratorId`。

返回字段：

```json
{
  "narrator": {
    "narratorId": 20001,
    "narratorName": "主播一号",
    "avatarUrl": "https://example.com/narrator.jpg",
    "intro": "主播简介",
    "contractType": "signed",
    "followerCount": 12000,
    "albumCount": 24
  },
  "albums": [],
  "activities": [],
  "userState": {"following": true}
}
```

行为：主播不存在或 `yn = 0` 时返回 `NARRATOR_NOT_FOUND`；`activities` 来源于 `user_activity_feed`。

#### 1.8 `GET /api/v1/rankings`
说明：查询启用榜单及榜单明细。

请求头：`X-User-Id` 可选。

查询参数：

- `rankingType`：榜单类型。
- `categoryId`：分类 ID。
- `periodType`：周期类型，支持 `daily`、`weekly`、`monthly`、`total`。

返回字段：

```json
{
  "rankings": [
    {
      "rankingId": 1,
      "rankingCode": "RANK_HOT_TOTAL",
      "rankingName": "热播总榜",
      "rankingType": "hot_album",
      "periodType": "total",
      "items": [
        {"rankNo": 1, "targetType": "album", "targetId": 10001, "targetName": "长篇有声小说", "coverUrl": "https://example.com/cover.jpg", "metricValue": 98231.0}
      ]
    }
  ]
}
```

行为：只返回 `ranking_list.yn = 1` 的榜单；明细取每个榜单最新 `stat_date`。

#### 1.9 `GET /api/v1/topics`
说明：分页查询已发布专题。

请求头：`X-User-Id` 可选。

查询参数：

- `topicType`：专题类型。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"topicId": 1, "topicCode": "TOPIC000001", "topicTitle": "悬疑精品", "topicType": "editorial", "coverUrl": "https://example.com/topic.jpg", "summary": "专题摘要", "publishedAt": "2026-01-01 10:00:00", "itemCount": 12}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回 `topic_status = published` 的专题。

#### 1.10 `GET /api/v1/topics/{topicId}`
说明：查询专题详情和专题明细。

请求头：`X-User-Id` 可选。

路径参数：`topicId`。

返回字段：

```json
{
  "topic": {"topicId": 1, "topicCode": "TOPIC000001", "topicTitle": "悬疑精品", "topicType": "editorial", "coverUrl": "https://example.com/topic.jpg", "summary": "专题摘要", "publishedAt": "2026-01-01 10:00:00"},
  "items": [
    {"itemId": 1, "targetType": "album", "targetId": 10001, "title": "长篇有声小说", "summary": "内容摘要", "imageUrl": "https://example.com/cover.jpg", "sortNo": 1}
  ]
}
```

行为：专题不存在或未发布时返回 `TOPIC_NOT_FOUND`；只返回 `content_topic_item.yn = 1` 的明细。

#### 1.11 `GET /api/v1/recommend-slots/{slotCode}/items`
说明：按推荐位编码查询当前有效推荐明细。

请求头：`X-User-Id` 可选。

路径参数：`slotCode`。

返回字段：

```json
{
  "slot": {"slotId": 1, "slotCode": "HOME_DAILY", "slotName": "每日推荐", "slotType": "album_list", "maxItemCount": 10},
  "items": [
    {"itemId": 1, "targetType": "album", "targetId": 10001, "title": "长篇有声小说", "imageUrl": "https://example.com/cover.jpg", "jumpUrl": null, "sortNo": 1}
  ]
}
```

行为：推荐位不存在或停用时返回 `RECOMMEND_SLOT_NOT_FOUND`；只返回当前时间有效且 `yn = 1` 的推荐明细。

### 2. 搜索
#### 2.1 `GET /api/v1/search`
说明：综合搜索专辑、章节、主播、机构和专题，并写入搜索日志。

请求头：`X-User-Id` 可选。

查询参数：

- `keyword`：必填，搜索词。
- `channelId`：必填，渠道 ID。
- `searchType`：搜索类型，支持 `all`、`album`、`book`、`program`、`track`、`narrator`、`organization`、`topic`，默认 `all`。
- `categoryId`：分类 ID，仅对专辑类结果生效。
- `sortBy`：排序方式，支持 `relevance`、`popular`、`newest`，默认 `relevance`。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "requestNo": "SRCH000000000001",
  "keyword": "悬疑",
  "searchType": "all",
  "resultCount": 12,
  "list": [
    {"targetType": "album", "targetId": 10001, "title": "长篇有声小说", "coverUrl": "https://example.com/cover.jpg", "summary": "内容摘要", "album": {"albumId": 10001, "albumTitle": "长篇有声小说"}}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 12
}
```

行为：每次请求写入 `search_query_log`；`keyword` 为空时返回 `VALIDATION_ERROR`；`channelId` 不存在或停用时返回 `CHANNEL_NOT_FOUND`；点击对象统一使用 `targetType` 和 `targetId` 标识。

#### 2.2 `POST /api/v1/search/clicks`
说明：记录搜索结果点击。

请求头：`X-User-Id` 可选。

请求体：

```json
{
  "requestNo": "SRCH000000000001",
  "clickedTargetType": "album",
  "clickedTargetId": 10001
}
```

返回字段：

```json
{
  "requestNo": "SRCH000000000001",
  "clickedFlag": 1,
  "clickedTargetType": "album",
  "clickedTargetId": 10001
}
```

行为：搜索日志不存在时返回 `SEARCH_QUERY_NOT_FOUND`；点击对象不存在时返回 `TARGET_NOT_FOUND`；同一个 `requestNo` 重复点击时覆盖为最新点击对象。

#### 2.3 `GET /api/v1/search/hot-keywords`
说明：查询热门搜索词。

请求头：无。

查询参数：

- `channelId`：渠道 ID。
- `days`：统计天数，默认 `7`，最大 `90`。
- `limit`：返回数量，默认 `20`，最大 `50`。

返回字段：

```json
{
  "keywords": [
    {"keyword": "悬疑", "searchCount": 1200, "resultClickCount": 860, "albumClickCount": 520, "narratorClickCount": 80, "latestStatDate": "2026-01-01"}
  ]
}
```

行为：按 `search_keyword_stat.search_count desc` 排序；未传 `channelId` 时聚合全部渠道。

#### 2.4 `GET /api/v1/search/suggestions`
说明：查询搜索联想词。

请求头：无。

查询参数：

- `keyword`：必填，搜索前缀。
- `limit`：返回数量，默认 `10`，最大 `20`。

返回字段：

```json
{
  "suggestions": [
    {"keyword": "悬疑推理", "displayText": "悬疑推理", "searchCount": 980}
  ]
}
```

行为：优先基于 `search_keyword_stat.keyword` 前缀匹配，不足时用已发布专辑标题补充。

### 3. 播放
#### 3.1 `POST /api/v1/tracks/{trackId}/play-url`
说明：获取章节播放地址，并执行播放鉴权。

请求头：`X-User-Id` 可选。

路径参数：`trackId`。

请求体：

```json
{
  "fileFormat": "mp3",
  "bitrateKbps": 128
}
```

返回字段：

```json
{
  "trackId": 50001,
  "albumId": 10001,
  "canPlay": true,
  "canPlayFull": true,
  "needPurchase": false,
  "entitlementType": "vip",
  "trialEndSeconds": 0,
  "audioFile": {"fileId": 90001, "fileFormat": "mp3", "bitrateKbps": 128, "durationSeconds": 1800, "fileUrl": "https://example.com/audio.mp3"},
  "purchaseOptions": []
}
```

行为：章节或音频文件不存在时返回 `TRACK_NOT_FOUND`；用户无完整播放权益时返回试看文件和购买选项；播放地址只选择 `file_status = available` 且 `is_current = 1` 的音频文件。

#### 3.2 `POST /api/v1/play-sessions`
说明：创建播放会话。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "trackId": 50001,
  "channelId": 1,
  "startPositionSeconds": 0
}
```

返回字段：

```json
{
  "sessionId": 80001,
  "sessionNo": "PLY000000000001",
  "albumId": 10001,
  "trackId": 50001,
  "channelId": 1,
  "playStartAt": "2026-01-01 10:00:00",
  "startPositionSeconds": 0,
  "playStatus": "interrupted"
}
```

行为：创建前校验渠道存在且用户具有可播放资格；专辑由章节推导；`startPositionSeconds` 超过章节时长时返回 `INVALID_START_POSITION`；会话创建时先以 `interrupted` 暂存，结束时按实际上报状态更新。

#### 3.3 `PATCH /api/v1/play-sessions/{sessionId}`
说明：结束或更新播放会话。

请求头：`X-User-Id` 必填。

路径参数：`sessionId`。

请求体：

```json
{
  "endPositionSeconds": 1200,
  "playedSeconds": 1200,
  "playStatus": "interrupted"
}
```

返回字段：

```json
{
  "sessionId": 80001,
  "playStatus": "interrupted",
  "playDurationSeconds": 1200,
  "endPositionSeconds": 1200,
  "playEndAt": "2026-01-01 10:20:00"
}
```

行为：会话不存在或不属于当前用户时返回 `PLAY_SESSION_NOT_FOUND`；结束位置不得超过章节时长；接口同步回写 `listening_progress`。

#### 3.4 `PUT /api/v1/listening-progress`
说明：写入或更新章节收听进度。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "trackId": 50001,
  "positionSeconds": 1200,
  "durationSeconds": 1800,
  "finishedFlag": false
}
```

返回字段：

```json
{
  "albumId": 10001,
  "trackId": 50001,
  "positionSeconds": 1200,
  "durationSeconds": 1800,
  "finishedFlag": 0,
  "lastPlayedAt": "2026-01-01 10:20:00"
}
```

行为：同一用户同一章节只保留一条进度；`positionSeconds` 不得超过 `durationSeconds`；完播后可同步回写书架状态。

#### 3.5 `GET /api/v1/listening-progress`
说明：查询当前用户收听进度。

请求头：`X-User-Id` 必填。

查询参数：

- `albumId`：专辑 ID。
- `trackId`：章节 ID。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"albumId": 10001, "albumTitle": "长篇有声小说", "trackId": 50001, "trackTitle": "第 1 章", "positionSeconds": 1200, "durationSeconds": 1800, "finishedFlag": 0, "lastPlayedAt": "2026-01-01 10:20:00"}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：默认按 `last_played_at desc` 排序。

### 4. 书架与关注
#### 4.1 `GET /api/v1/bookshelf`
说明：查询当前用户书架。

请求头：`X-User-Id` 必填。

查询参数：

- `shelfStatus`：书架状态，支持 `favorited`、`subscribed`、`finished`、`removed`。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"albumId": 10001, "albumTitle": "长篇有声小说", "coverUrl": "https://example.com/cover.jpg", "shelfStatus": "subscribed", "lastTrackId": 50001, "lastTrackTitle": "第 1 章", "lastPositionSeconds": 1200, "updatedAt": "2026-01-01 10:20:00", "publishStatus": "serializing"}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：默认不返回 `removed` 状态；按 `user_bookshelf.updated_at desc` 排序。

#### 4.2 `POST /api/v1/bookshelf`
说明：收藏或订阅专辑。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "albumId": 10001,
  "shelfStatus": "subscribed"
}
```

返回字段：

```json
{
  "albumId": 10001,
  "shelfStatus": "subscribed",
  "createdAt": "2026-01-01 10:00:00",
  "updatedAt": "2026-01-01 10:00:00"
}
```

行为：专辑不存在或未发布时返回 `ALBUM_NOT_FOUND`；重复收藏或订阅时幂等更新状态。

#### 4.3 `DELETE /api/v1/bookshelf/{albumId}`
说明：从书架移除专辑。

请求头：`X-User-Id` 必填。

路径参数：`albumId`。

返回字段：

```json
{
  "albumId": 10001,
  "shelfStatus": "removed",
  "updatedAt": "2026-01-01 10:00:00"
}
```

行为：书架记录不存在时幂等返回移除成功。

#### 4.4 `GET /api/v1/follows`
说明：查询当前用户关注对象。

请求头：`X-User-Id` 必填。

查询参数：

- `targetType`：关注对象类型，支持 `narrator`、`author`、`organization`。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"targetType": "narrator", "targetId": 20001, "targetName": "主播一号", "avatarUrl": "https://example.com/narrator.jpg", "summary": "主播简介", "followedAt": "2026-01-01 10:00:00"}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回 `follow_status = following` 的记录。

#### 4.5 `POST /api/v1/follows`
说明：关注主播、作者或机构。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "targetType": "narrator",
  "targetId": 20001
}
```

返回字段：

```json
{
  "targetType": "narrator",
  "targetId": 20001,
  "followStatus": "following",
  "followedAt": "2026-01-01 10:00:00"
}
```

行为：关注对象不存在时返回 `FOLLOW_TARGET_NOT_FOUND`；重复关注时幂等返回当前关注状态。

#### 4.6 `DELETE /api/v1/follows`
说明：取消关注。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "targetType": "narrator",
  "targetId": 20001
}
```

返回字段：

```json
{
  "targetType": "narrator",
  "targetId": 20001,
  "followStatus": "cancelled",
  "cancelledAt": "2026-01-01 10:00:00"
}
```

行为：关注记录不存在时幂等返回取消成功。

### 5. 互动与反馈
#### 5.1 `GET /api/v1/comments`
说明：分页查询专辑或章节评论。

请求头：`X-User-Id` 可选。

查询参数：

- `targetType`：必填，支持 `album`、`track`。
- `targetId`：必填，对象 ID。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"commentId": 1, "userId": 10001, "nickname": "听友000001", "avatarUrl": "https://example.com/avatar.jpg", "commentText": "声音很好", "auditStatus": "approved", "likeCount": 12, "createdAt": "2026-01-01 10:00:00", "liked": true}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：公共查询只返回 `audit_status = approved` 的评论；传入合法 `X-User-Id` 时返回 `liked`。

#### 5.2 `POST /api/v1/comments`
说明：提交评论或回复。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "targetType": "album",
  "targetId": 10001,
  "parentCommentId": null,
  "commentText": "声音很好"
}
```

返回字段：

```json
{
  "commentId": 1,
  "auditStatus": "pending",
  "createdAt": "2026-01-01 10:00:00"
}
```

行为：评论对象不存在时返回 `COMMENT_TARGET_NOT_FOUND`；新评论默认进入 `pending`。

#### 5.3 `POST /api/v1/ratings`
说明：提交或更新专辑评分。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "albumId": 10001,
  "ratingScore": 9.0,
  "ratingText": "值得听"
}
```

返回字段：

```json
{
  "albumId": 10001,
  "ratingScore": 9.0,
  "ratingText": "值得听",
  "createdAt": "2026-01-01 10:00:00",
  "updatedAt": "2026-01-01 10:00:00"
}
```

行为：评分范围为 `1` 到 `10`；重复评分时更新原记录，并回写专辑评分均值。

#### 5.4 `POST /api/v1/reactions`
说明：点赞、点踩、分享或转发。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "targetType": "comment",
  "targetId": 1,
  "reactionType": "like",
  "reactionStatus": "active"
}
```

返回字段：

```json
{
  "targetType": "comment",
  "targetId": 1,
  "reactionType": "like",
  "reactionStatus": "active",
  "updatedAt": "2026-01-01 10:00:00"
}
```

行为：互动对象不存在时返回 `REACTION_TARGET_NOT_FOUND`；同一用户同一对象同一互动类型唯一；评论点赞会回写 `content_comment.like_count`。

#### 5.5 `POST /api/v1/reports`
说明：举报专辑、章节、评论或主播。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "targetType": "album",
  "targetId": 10001,
  "reportReason": "copyright",
  "reportText": "疑似版权问题"
}
```

返回字段：

```json
{
  "reportId": 1,
  "reportNo": "RPT000000000001",
  "handleStatus": "pending",
  "createdAt": "2026-01-01 10:00:00"
}
```

行为：举报对象不存在时返回 `REPORT_TARGET_NOT_FOUND`；新举报默认进入 `pending`。

### 6. 会员、交易与权益
#### 6.1 `GET /api/v1/vip-plans`
说明：查询启用会员套餐。

请求头：`X-User-Id` 可选。

返回字段：

```json
{
  "plans": [
    {"planId": 1, "planCode": "LR_VIP_MONTHLY", "planName": "VIP 月度会员", "memberLevel": "vip", "durationDays": 31, "currencyCode": "CNY", "salePriceAmount": 19.0, "originalPriceAmount": 23.75, "benefitPayload": {}}
  ],
  "currentMember": {"memberLevel": "vip", "memberStatus": "active", "validFrom": "2026-01-01 10:00:00", "validTo": "2026-02-01 10:00:00"}
}
```

行为：只返回 `yn = 1` 的套餐；未传 `X-User-Id` 时 `currentMember` 为 `null`。

#### 6.2 `GET /api/v1/entitlements`
说明：查询当前用户权益。

请求头：`X-User-Id` 必填。

查询参数：

- `targetType`：权益对象类型，支持 `vip`、`album`、`track`。
- `entitlementStatus`：权益状态，支持 `active`、`expired`、`revoked`。

返回字段：

```json
{
  "entitlements": [
    {"entitlementId": 1, "sourceType": "purchase", "orderId": 70001, "targetType": "album", "targetId": 10001, "targetName": "长篇有声小说", "validFrom": "2026-01-01 10:00:00", "validTo": null, "entitlementStatus": "active"}
  ]
}
```

行为：只返回当前用户权益；`targetName` 按目标类型关联 `vip_plan`、`audio_album` 或 `audio_track`。

#### 6.3 `POST /api/v1/orders/preview`
说明：按当前价格、权益和商品状态预览订单金额。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "orderType": "album",
  "channelId": 1,
  "items": [
    {"itemType": "album", "albumId": 10001, "trackId": null, "vipPlanId": null, "quantity": 1}
  ]
}
```

返回字段：

```json
{
  "orderType": "album",
  "currencyCode": "CNY",
  "totalAmount": 19.9,
  "discountAmount": 0.0,
  "payableAmount": 19.9,
  "items": [
    {"itemType": "album", "albumId": 10001, "itemName": "长篇有声小说", "quantity": 1, "unitPriceAmount": 19.9, "discountAmount": 0.0, "payableAmount": 19.9}
  ]
}
```

行为：预览不落订单；商品不可购买时返回 `ORDER_ITEM_NOT_AVAILABLE`；用户已拥有有效权益时返回 `ORDER_ITEM_ALREADY_OWNED`；`itemType = vip_plan` 时仅允许填写 `vipPlanId`，`itemType = album` 时仅允许填写 `albumId`，`itemType = track` 时仅允许填写 `trackId`。

#### 6.4 `POST /api/v1/orders`
说明：创建会员、专辑、章节或组合订单。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "orderType": "album",
  "channelId": 1,
  "items": [
    {"itemType": "album", "albumId": 10001, "trackId": null, "vipPlanId": null, "quantity": 1}
  ]
}
```

返回字段：

```json
{
  "order": {"orderId": 70001, "orderNo": "ORD000000000001", "orderType": "album", "orderStatus": "created", "currencyCode": "CNY", "totalAmount": 19.9, "discountAmount": 0.0, "payableAmount": 19.9, "createdAt": "2026-01-01 10:00:00"},
  "items": [
    {"itemId": 71001, "itemType": "album", "itemName": "长篇有声小说", "quantity": 1, "unitPriceAmount": 19.9, "discountAmount": 0.0, "payableAmount": 19.9}
  ]
}
```

行为：服务端按 `vip_plan` 和 `album_price_rule` 重新计算金额；前端传入金额不参与落库；商品不可购买时返回 `ORDER_ITEM_NOT_AVAILABLE`；用户已拥有有效权益时返回 `ORDER_ITEM_ALREADY_OWNED`；`bundle` 订单允许混合 `vip_plan`、`album` 和 `track` 商品。

#### 6.5 `GET /api/v1/orders`
说明：分页查询当前用户订单。

请求头：`X-User-Id` 必填。

查询参数：

- `orderType`：订单类型。
- `orderStatus`：订单状态。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"orderId": 70001, "orderNo": "ORD000000000001", "orderType": "album", "orderStatus": "paid", "payableAmount": 19.9, "paidAt": "2026-01-01 10:01:00", "createdAt": "2026-01-01 10:00:00", "firstItemName": "长篇有声小说", "itemCount": 1}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回当前用户订单，默认按 `created_at desc` 排序。

#### 6.6 `GET /api/v1/orders/{orderId}`
说明：查询订单详情。

请求头：`X-User-Id` 必填。

路径参数：`orderId`。

返回字段：

```json
{
  "order": {"orderId": 70001, "orderNo": "ORD000000000001", "orderType": "album", "orderStatus": "paid", "currencyCode": "CNY", "totalAmount": 19.9, "discountAmount": 0.0, "payableAmount": 19.9, "paidAt": "2026-01-01 10:01:00", "createdAt": "2026-01-01 10:00:00"},
  "items": [],
  "payments": [],
  "refunds": [],
  "entitlements": []
}
```

行为：订单不存在或不属于当前用户时返回 `ORDER_NOT_FOUND`。

#### 6.7 `POST /api/v1/payments`
说明：创建或复用支付流水。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "paySubjectType": "content_order",
  "paySubjectId": 70001,
  "paymentChannel": "alipay"
}
```

返回字段：

```json
{
  "payment": {"paymentId": 90001, "paymentNo": "PAY000000000001", "paySubjectType": "content_order", "paySubjectId": 70001, "paymentChannel": "alipay", "paymentStatus": "created", "paymentAmount": 19.9, "currencyCode": "CNY", "createdAt": "2026-01-01 10:00:00"}
}
```

行为：内容订单支持 `wechat_pay`、`alipay`、`apple_pay`、`balance`、`coupon`；充值订单支持 `wechat_pay`、`alipay`、`apple_pay`；余额支付金额不足时返回 `WALLET_BALANCE_NOT_ENOUGH`。

#### 6.8 `POST /api/v1/payment-notifications/mock`
说明：模拟支付回调。

请求头：`X-Demo-Payment-Signature` 必填。

请求体：

```json
{
  "paymentNo": "PAY000000000001",
  "paymentStatus": "success"
}
```

返回字段：

```json
{
  "payment": {"paymentId": 90001, "paymentNo": "PAY000000000001", "paymentStatus": "success", "paidAt": "2026-01-01 10:01:00"},
  "subject": {"subjectType": "content_order", "subjectId": 70001, "subjectStatus": "paid"},
  "entitlements": [],
  "walletLedger": null
}
```

行为：支付不存在时返回 `PAYMENT_NOT_FOUND`；支付已为终态时按幂等规则返回当前状态；支付成功时间由应用生成；支付成功后更新订单、权益和钱包流水。

#### 6.9 `POST /api/v1/refunds`
说明：申请退款。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "paymentId": 90001,
  "refundReason": "用户申请退款",
  "items": [
    {"orderItemId": 71001, "refundQuantity": 1, "refundAmount": 19.9}
  ]
}
```

返回字段：

```json
{
  "refund": {"refundId": 95001, "refundNo": "RFD000000000001", "refundStatus": "requested", "refundAmount": 19.9, "requestedAt": "2026-01-01 10:10:00"},
  "items": []
}
```

行为：支付不存在、不属于当前用户或未成功时返回 `PAYMENT_NOT_REFUNDABLE`；内容订单退款必须提交退款明细，充值订单退款不得提交明细；退款金额不得超过可退金额。

#### 6.10 `POST /api/v1/refund-notifications/mock`
说明：模拟退款处理回调。

请求头：`X-Demo-Payment-Signature` 必填。

请求体：

```json
{
  "refundNo": "RFD000000000001",
  "refundStatus": "success",
  "handleResult": "退款成功"
}
```

返回字段：

```json
{
  "refund": {"refundId": 95001, "refundNo": "RFD000000000001", "refundStatus": "success", "refundAmount": 19.9, "requestedAt": "2026-01-01 10:10:00", "handledAt": "2026-01-01 10:20:00", "refundedAt": "2026-01-01 10:21:00"},
  "walletLedger": null
}
```

行为：退款单不存在时返回 `REFUND_NOT_FOUND`；支持 `approved`、`rejected`、`success`、`failed`；退款成功后撤销对应权益，余额支付退款生成钱包退款流水，充值退款生成钱包扣减流水。

#### 6.11 `GET /api/v1/refunds`
说明：分页查询当前用户退款单。

请求头：`X-User-Id` 必填。

查询参数：

- `refundStatus`：退款状态。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"refundId": 95001, "refundNo": "RFD000000000001", "refundStatus": "success", "refundAmount": 19.9, "refundReason": "用户申请退款", "requestedAt": "2026-01-01 10:10:00", "handledAt": "2026-01-01 10:20:00", "refundedAt": "2026-01-01 10:21:00"}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回当前用户支付记录下的退款单。

### 7. 钱包
#### 7.1 `GET /api/v1/wallet`
说明：查询当前用户钱包。

请求头：`X-User-Id` 必填。

返回字段：

```json
{
  "wallet": {"walletId": 1, "currencyCode": "CNY", "walletStatus": "active", "balanceAmount": 120.0, "frozenAmount": 0.0, "availableAmount": 120.0, "openedAt": "2026-01-01 10:00:00"}
}
```

行为：钱包不存在时返回 `WALLET_NOT_FOUND`。

#### 7.2 `GET /api/v1/wallet/ledgers`
说明：分页查询当前用户钱包流水。

请求头：`X-User-Id` 必填。

查询参数：

- `ledgerType`：流水类型，支持 `recharge`、`consume`、`refund`、`freeze`、`unfreeze`、`adjust`。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"ledgerId": 1, "ledgerType": "recharge", "relatedType": "recharge_order", "relatedId": 80001, "amountDelta": 100.0, "frozenDelta": 0.0, "balanceAfter": 100.0, "availableAfter": 100.0, "createdAt": "2026-01-01 10:00:00"}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：按 `created_at desc, id desc` 排序。

#### 7.3 `POST /api/v1/recharge-orders`
说明：创建充值订单。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "walletId": 1,
  "channelId": 1,
  "rechargeAmount": 100.0,
  "paymentChannel": "alipay"
}
```

返回字段：

```json
{
  "rechargeOrder": {"rechargeOrderId": 80001, "rechargeNo": "RCH000000000001", "payableAmount": 100.0, "rechargeStatus": "created"},
  "payment": {"paymentId": 90001, "paymentNo": "PAY000000000002", "paymentStatus": "created"}
}
```

行为：钱包不存在或不属于当前用户时返回 `WALLET_NOT_FOUND`；充值金额必须大于 `0`。

### 8. 用户中心与消息
#### 8.1 `GET /api/v1/me`
说明：查询当前用户账号、画像、会员和钱包摘要。

请求头：`X-User-Id` 必填。

返回字段：

```json
{
  "user": {"userId": 10001, "userNo": "USR0000000001", "nickname": "听友000001", "avatarUrl": "https://example.com/avatar.jpg", "accountStatus": "normal", "lastLoginAt": "2026-01-01 10:00:00"},
  "profile": {"gender": "unknown", "birthday": null, "province": "上海", "city": "上海", "occupation": "互联网", "listeningScene": []},
  "member": {"memberLevel": "vip", "memberStatus": "active", "validFrom": "2026-01-01 10:00:00", "validTo": "2026-02-01 10:00:00"},
  "wallet": {"walletId": 1, "availableAmount": 120.0, "currencyCode": "CNY"}
}
```

行为：用户不存在或不可用时返回 `USER_NOT_FOUND_OR_DISABLED`。

#### 8.2 `PATCH /api/v1/me/profile`
说明：更新当前用户画像。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "nickname": "新昵称",
  "avatarUrl": "https://example.com/avatar.jpg",
  "gender": "female",
  "birthday": "1998-01-01",
  "province": "上海",
  "city": "上海",
  "occupation": "互联网",
  "listeningScene": ["commute", "sleep"]
}
```

返回字段：

```json
{
  "user": {"userId": 10001, "nickname": "新昵称", "avatarUrl": "https://example.com/avatar.jpg"},
  "profile": {"gender": "female", "birthday": "1998-01-01", "province": "上海", "city": "上海", "occupation": "互联网", "listeningScene": ["commute", "sleep"]}
}
```

行为：只允许更新当前用户资料；`listeningScene` 写入 `user_profile.listening_scene_payload`。

#### 8.3 `GET /api/v1/messages`
说明：分页查询当前用户站内消息。

请求头：`X-User-Id` 必填。

查询参数：

- `messageType`：消息类型。
- `readStatus`：读取状态，支持 `unread`、`read`、`deleted`。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"messageId": 1, "messageType": "trade", "messageTitle": "订单通知", "messageContent": "您的订单已支付", "targetType": "content_order", "targetId": 70001, "readStatus": "unread", "sentAt": "2026-01-01 10:00:00", "readAt": null}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回当前用户作为 `receiver_user_id` 的消息。

#### 8.4 `PATCH /api/v1/messages/{messageId}/read`
说明：标记消息已读。

请求头：`X-User-Id` 必填。

路径参数：`messageId`。

返回字段：

```json
{
  "messageId": 1,
  "readStatus": "read",
  "readAt": "2026-01-01 10:00:00"
}
```

行为：消息不存在或不属于当前用户时返回 `MESSAGE_NOT_FOUND`；已读消息幂等返回当前状态。

### 9. 客服工单
#### 9.1 `POST /api/v1/support-tickets`
说明：提交客服工单。

请求头：`X-User-Id` 可选。

请求体：

```json
{
  "ticketType": "payment_issue",
  "relatedType": "content_order",
  "relatedId": 70001,
  "contactMobile": "13800000000",
  "contactEmail": "user@example.com",
  "ticketTitle": "订单支付问题",
  "ticketContent": "支付后权益未到账"
}
```

返回字段：

```json
{
  "ticketId": 1,
  "ticketNo": "TCK000000000001",
  "ticketStatus": "submitted",
  "submittedAt": "2026-01-01 10:00:00"
}
```

行为：未登录提交时 `contactMobile` 和 `contactEmail` 至少填写一个；关联对象不存在时返回 `SUPPORT_TICKET_RELATED_OBJECT_NOT_FOUND`；`relatedType` 为 `content_order`、`recharge_order`、`payment`、`refund`、`upload_task` 或 `report` 时必须登录并校验对象归属，匿名工单只能关联 `none`、`album` 或 `track`。

#### 9.2 `GET /api/v1/support-tickets`
说明：分页查询当前用户工单。

请求头：`X-User-Id` 必填。

查询参数：

- `ticketStatus`：工单状态。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"ticketId": 1, "ticketNo": "TCK000000000001", "ticketType": "payment_issue", "ticketTitle": "订单支付问题", "ticketStatus": "submitted", "submittedAt": "2026-01-01 10:00:00", "handledAt": null, "closedAt": null}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回当前用户提交的工单。

#### 9.3 `GET /api/v1/support-tickets/{ticketId}`
说明：查询工单详情。

请求头：`X-User-Id` 必填。

路径参数：`ticketId`。

返回字段：

```json
{
  "ticket": {"ticketId": 1, "ticketNo": "TCK000000000001", "ticketType": "payment_issue", "relatedType": "content_order", "relatedId": 70001, "ticketTitle": "订单支付问题", "ticketContent": "支付后权益未到账", "ticketStatus": "submitted", "handleResult": null, "submittedAt": "2026-01-01 10:00:00", "handledAt": null, "closedAt": null},
  "relatedObject": {"relatedType": "content_order", "relatedId": 70001, "title": "ORD000000000001"}
}
```

行为：工单不存在或不属于当前用户时返回 `SUPPORT_TICKET_NOT_FOUND`。

### 10. 创作者与内容供给
#### 10.1 `GET /api/v1/creator-profile`
说明：查询当前用户的创作者档案。

请求头：`X-User-Id` 必填。

返回字段：

```json
{
  "creator": {"creatorId": 1, "creatorNo": "CRT000001", "creatorName": "主播工作室", "creatorType": "studio", "narratorId": 20001, "organizationId": 30001, "certificationStatus": "certified", "creatorIntro": "简介", "homepageUrl": null, "settledAt": "2026-01-01 10:00:00"}
}
```

行为：当前用户未入驻创作者时返回 `CREATOR_PROFILE_NOT_FOUND`。

#### 10.2 `POST /api/v1/creator-applications`
说明：提交创作者入驻、主播认证、机构认证或合约升级申请。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "applyType": "creator_settle",
  "organizationId": null,
  "applyPayload": {"contactName": "张三", "contactInfo": "user@example.com"}
}
```

返回字段：

```json
{
  "applicationId": 1,
  "applyNo": "CAP000000000001",
  "applyStatus": "submitted",
  "submittedAt": "2026-01-01 10:00:00"
}
```

行为：`applyType` 支持 `creator_settle`、`narrator_certification`、`organization_certification`、`contract_upgrade`；机构不存在时返回 `ORGANIZATION_NOT_FOUND`。

#### 10.3 `GET /api/v1/creator-applications`
说明：分页查询当前用户的创作者申请记录。

请求头：`X-User-Id` 必填。

查询参数：

- `applyStatus`：申请状态。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"applicationId": 1, "applyNo": "CAP000000000001", "applyType": "creator_settle", "applyStatus": "submitted", "rejectReason": null, "submittedAt": "2026-01-01 10:00:00", "reviewedAt": null}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回当前用户提交的申请。

#### 10.4 `POST /api/v1/creator/albums`
说明：创建创作者专辑草稿。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "albumTitle": "新有声书",
  "albumType": "audiobook",
  "categoryId": 10,
  "languageId": 1,
  "coverUrl": "https://example.com/cover.jpg",
  "summary": "专辑简介",
  "publishStatus": "serializing",
  "ageRating": "all"
}
```

返回字段：

```json
{
  "album": {"albumId": 10001, "albumCode": "ALB0000000001", "albumTitle": "新有声书", "albumStatus": "draft", "publishStatus": "serializing"}
}
```

行为：当前用户必须存在有效创作者档案；分类或语言不存在时返回对应错误；新专辑默认 `album_status = draft`。

#### 10.5 `PATCH /api/v1/creator/albums/{albumId}`
说明：更新创作者专辑基础信息。

请求头：`X-User-Id` 必填。

路径参数：`albumId`。

请求体：

```json
{
  "albumTitle": "新标题",
  "summary": "新简介",
  "coverUrl": "https://example.com/new-cover.jpg"
}
```

返回字段：

```json
{
  "album": {"albumId": 10001, "albumTitle": "新标题", "albumStatus": "draft", "updatedAt": "2026-01-01 10:00:00"}
}
```

行为：只能操作当前创作者拥有的专辑；`published` 和 `offline` 专辑不可直接编辑基础信息。

#### 10.6 `POST /api/v1/upload-tasks`
说明：提交封面、章节、音频文件或批量章节上传任务。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "albumId": 10001,
  "trackId": null,
  "fileId": null,
  "uploadType": "audio_file",
  "sourceFileName": "001.mp3",
  "sourceFileUrl": "https://example.com/001.mp3",
  "fileSizeBytes": 1024000
}
```

返回字段：

```json
{
  "uploadTask": {"uploadTaskId": 1, "uploadNo": "UPL000000000001", "uploadType": "audio_file", "processStatus": "submitted", "submittedAt": "2026-01-01 10:00:00"}
}
```

行为：`uploadType` 为 `track`、`audio_file`、`cover` 或 `batch_tracks` 时必须传入 `albumId`；`album`、`cover`、`batch_tracks` 上传任务不得关联单个章节或音频文件；关联专辑、章节或音频文件时必须属于当前创作者；同时传入专辑、章节或音频文件时，章节必须属于指定专辑，音频文件必须属于指定章节或专辑；新任务默认 `process_status = submitted`。

#### 10.7 `GET /api/v1/upload-tasks`
说明：分页查询当前创作者上传任务。

请求头：`X-User-Id` 必填。

查询参数：

- `processStatus`：处理状态。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"uploadTaskId": 1, "uploadNo": "UPL000000000001", "uploadType": "audio_file", "processStatus": "submitted", "submittedAt": "2026-01-01 10:00:00"}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回当前创作者的上传任务。

#### 10.8 `GET /api/v1/upload-tasks/{uploadTaskId}`
说明：查询上传任务详情。

请求头：`X-User-Id` 必填。

路径参数：`uploadTaskId`。

返回字段：

```json
{
  "uploadTask": {"uploadTaskId": 1, "uploadNo": "UPL000000000001", "albumId": 10001, "trackId": null, "fileId": null, "uploadType": "audio_file", "sourceFileName": "001.mp3", "sourceFileUrl": "https://example.com/001.mp3", "fileSizeBytes": 1024000, "processStatus": "submitted", "failureReason": null, "submittedAt": "2026-01-01 10:00:00", "processedAt": null}
}
```

行为：任务不存在或不属于当前创作者时返回 `UPLOAD_TASK_NOT_FOUND`。

#### 10.9 `POST /api/v1/content-audits`
说明：提交内容审核记录。

请求头：`X-User-Id` 必填。

请求体：

```json
{
  "uploadTaskId": 1,
  "targetType": "album",
  "targetId": 10001,
  "auditType": "manual",
  "auditPayload": {"remark": "提交审核"}
}
```

返回字段：

```json
{
  "auditId": 1,
  "auditNo": "AUD000000000001",
  "auditStatus": "pending"
}
```

行为：关联上传任务时必须属于当前创作者；审核对象为专辑、章节、音频文件、上传任务、评论或创作者档案时，必须属于当前创作者；新审核记录默认 `audit_status = pending`。

#### 10.10 `GET /api/v1/content-audits`
说明：分页查询当前创作者内容审核记录。

请求头：`X-User-Id` 必填。

查询参数：

- `auditStatus`：审核状态。
- `pageNo`、`pageSize`。

返回字段：

```json
{
  "list": [
    {"auditId": 1, "auditNo": "AUD000000000001", "targetType": "album", "targetId": 10001, "auditType": "manual", "auditStatus": "pending", "auditReason": null, "auditedAt": null, "createdAt": "2026-01-01 10:00:00"}
  ],
  "pageNo": 1,
  "pageSize": 20,
  "total": 1
}
```

行为：只返回当前创作者上传任务关联的审核记录。

#### 10.11 `POST /api/v1/creator/albums/{albumId}/publish-actions`
说明：提交专辑发布状态动作。

请求头：`X-User-Id` 必填。

路径参数：`albumId`。

请求体：

```json
{
  "action": "submit_review",
  "reason": "提交审核"
}
```

返回字段：

```json
{
  "album": {"albumId": 10001, "albumTitle": "新有声书", "albumStatus": "reviewing"},
  "action": "submit_review"
}
```

行为：`action` 支持 `submit_review`、`publish`、`pause`、`offline`；只能操作当前创作者拥有的专辑；每次动作写入 `album_update_record`。
