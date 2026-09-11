# 登录认证原理速查手册

> 覆盖范围：本项目（漫画聚合平台）用户登录/收藏功能的认证体系
> 技术栈：JWT (HS256) + bcrypt 密码哈希 + user 表唯一约束
> 说明：本文档以 `api-service` 的真实代码为准（接口在 `routers/`，实现在 `core/` 与 `services/`），供 review / 讲解使用

---

## 0. 一句话总览

**注册存密码指纹（bcrypt） → 登录验本人并签章（JWT） → 客户端随身带章（token） → 服务端用公章验章（secret）。**

四个关键角色各司其职、环环相扣：

| 角色 | 谁拥有 | 负责什么 | 一句话 |
|---|---|---|---|
| `secret` | 服务端 | 全站固定，签/验签的公章 | 造 token 的钥匙 |
| `signature` | token 第 3 段 | 内容 + secret 算出的指纹 | 防篡改的印记 |
| `token` | 客户端 | 用户身份凭证 | 每次登录发一张 |
| `password_hash` | 数据库 | 用户密码的指纹 | 验「是不是本人」 |

> ⚠️ 两组最易混淆：
> - **`password_hash` ≠ `secret`**：前者是「用户密码的指纹」（验本人），后者是「全站公章」（验 token 真假），完全无关。
> - **`signature` ≠ `secret`**：前者是「算出的结果」，后者是「用来算的原料」。

---

## 1. 密码存储：bcrypt `password_hash`

### 1.1 为什么不能存明文
- 数据库一旦泄露，明文密码全部暴露，且用户常在多站复用同一密码。
- 因此存「单向哈希」，只能验证、不能还原。

### 1.2 `password_hash` 的结构
bcrypt 字符串是**四段信息的拼接**：

```
$2b$12$  NSIuNmCBrNdd9hdU1r3Rmu  msPzM7.jLMEXRkB8MetJzhtNK67jjK2
└-┘└-┘ └──── 22 字符 salt ────┘ └──── 31 字符 hash ────┘
算法 cost  盐（随机，每人不同）      真正哈希
```

### 1.3 关键机制：盐「内嵌」在哈希里，不单独存
- **每个账号的盐都不同**（每次 `gensalt()` 随机生成）。
- **即使两个用户明文密码相同，盐不同 → 哈希也不同**（防「相同密码在库里出现相同哈希」）。
- 盐**跟着哈希一起存、一起取**，不需要单独的列或二次查询。

### 1.4 `checkpw` 如何验证密码
`checkpw` 不知道明文和哈希的「历史关系」，它只是**用盐复算**：

```
① 从 password_hash 里提取 salt（内嵌的那 22 字符）
② 对用户输入的明文密码 + 同一个 salt 重新哈希
③ 重算结果 与 库里存的 hash 比对 → 相等返回 True，否则 False
```

由于 bcrypt 是**确定性函数**（相同输入必得相同输出），盐没变则重算必然等于存储值，从而确认「是同一个密码」。

---

## 2. 用户唯一性：`username NOT NULL UNIQUE`

### 2.1 为什么同名不存在
user 表建表语句（`crawler-service/sql/mysql_schema.sql`，MySQL 5.7）：

```sql
CREATE TABLE IF NOT EXISTS user (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname      VARCHAR(64) NOT NULL DEFAULT '',
    avatar_url    VARCHAR(512) NOT NULL DEFAULT '',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_username (username)   -- ← 数据库层禁止同名
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
```

### 2.2 两道防线
| 防线 | 位置 | 作用 |
|---|---|---|
| ① 注册查重 | `register()` | 先查 username 已存在，返回 409「用户名已存在」 |
| ② 数据库唯一索引 | `UNIQUE KEY uk_username (username)` | 兜底，即使并发同名注册也强制拒绝 |

### 2.3 username vs nickname
- **`username`**：登录标识，唯一，禁止同名。
- **`nickname`**：显示昵称，可重复（两人都叫「小明」没问题）。

正因为 username 唯一，**登录时按 username 查库必然唯一命中一行**，盐和哈希绝不混淆。

---

## 3. JWT 三大件：token / signature / secret

### 3.1 三者是什么
| 名词 | 定义 | 项目真实取值 |
|---|---|---|
| `secret` | 服务器独有的公章/钥匙 | `comic-demo-secret-change-me`（演示值）|
| `signature` | 用 secret 对 header.payload 算的指纹 | token 第 3 段 |
| `token` | `header.payload.signature` 三段拼接的成品 | `eyJhbGci... . eyJzdWIi... . xr9_Ijcwn...` |

### 3.2 关联（一条链）
```
secret（钥匙） ＋ header.payload（内容）
        ↓  一起送进 HMAC-SHA256
   signature（指纹 / 第3段）
        ↓  与 header.payload 点拼接
   token = header.payload.signature（成品）
```

### 3.3 区别（最关键的四条）
| 维度 | secret | signature | token |
|---|---|---|---|
| 本质 | 输入 / 原料 | 输出 / 结果 | 组合 / 成品 |
| 谁能看到 | 只有服务端 | 服务端 + 客户端（在 token 里） | 服务端 + 客户端 |
| 数量 | 全站 1 个 | 每个 token 有 1 个 | 每人每次登录 1 个 |
| 能否再生 | 永远不变 | 内容变它就变 | 每次重新签发都变 |

### 3.4 最易踩的误区
> ⚠️ **signature ≠ secret**，也**不是** secret。

- 你手里**一定有 signature**（它在 token 第 3 段，客户端可见）。
- 但你手里**永远没有 secret**（它锁在服务端）。
- 正因为 **secret ≠ signature**，你才**算不出新的第 3 段**——否则 token 可随意伪造。

---

## 4. secret 的来源

### 4.1 是「配置」来的，不是「算」来的
```python
_JWT_SECRET = os.environ.get("COMIC_JWT_SECRET", "comic-demo-secret-change-me")
```
- 优先读环境变量 `COMIC_JWT_SECRET`；设了就用它，没设回落默认值。
- 当前未设环境变量，实际用的是默认值 `comic-demo-secret-change-me`。

### 4.2 生产环境必须替换
- 默认值写死在代码里 = 公开，任何拿到源码者都能伪造任意登录态。
- 生产做法：`COMIC_JWT_SECRET="$(head -c 48 /dev/urandom | base64)"` 注入；**不进 git、不进源码**。

### 4.3 强随机的本质是「保密」，不是「频繁变」
- ✅ 正确：生成一次 → 固定下来 → 保密。
- ✅ 对服务端，它**永远不变**（才能验签）；对敌人，它**猜不到**（才能保密）。
- ❌ 若真的「每次换新」，旧 token 用旧 secret 签，新 secret 验签必然失败 → 所有人被登出。
- secret 只在**泄露时**才换，换来的是旧 token 集体失效（安全收益）。

---

## 5. 完整登录流程（代码对照）

### 5.1 注册 `/api/auth/register` —— 诞生 `password_hash`
```python
user = users.create_user(username, _hash_password(body.password), body.nickname.strip())
# _hash_password → bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()  → 存 $2b$12$...
```

### 5.2 登录 `/api/auth/login` —— 验本人 + 签章
```python
if not user or not _verify_password(body.password, user["password_hash"]):
    raise HTTPException(status_code=401, detail="用户名或密码错误")
return _ok({"token": _make_token(user["id"], user["username"]), ...})
```
- `_verify_password` → `bcrypt.checkpw(明文, password_hash)` → 验「是不是本人」
- `_make_token` → `jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)` → 用 secret 签 token

### 5.3 `_make_token` 签发（内部五步）
```python
def _make_token(user_id: int, username: str) -> str:
    now = datetime.now()
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_JWT_EXP_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)
```
`jwt.encode` 内部：①准备 header → ②base64 payload → ③HMAC(secret, header.payload) 得到第 3 段 → ④点拼接 → ⑤返回 token。

> **签发顺序永远为「先签名 → 再拼接 → 再发送」**，不能反。

### 5.4 携带访问
客户端存 token（如 `localStorage`），请求头带：
```
Authorization: Bearer <header.payload.signature>
```

### 5.5 服务端验签 `_decode_token` / `get_current_user`
```python
def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")
    return payload

def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if cred is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    payload = _decode_token(cred.credentials)
    user = users.get_user(payload.get("sub", ""))
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    return user
```

`jwt.decode` 内部验证：①取前两段 → ②用 secret 重算 HMAC → ③与 token 第 3 段比对。一致通过；不一致 / 过期 → 401。

### 5.6 四角色 × 四步骤总表
| | ① 注册 | ② 登录 | ③ 携带 | ④ 验签 | 一句话 |
|---|---|---|---|---|---|
| `password_hash` | ✅ 生成存库 | ✅ 验本人 | — | — | 验「是不是本人」 |
| `secret` | — | ✅ 签 token | — | ✅ 验签 | 全站公章，验真实 |
| `signature` | — | ✅ 生成于第 3 段 | ✅ 带身上 | ✅ 被核对 | 防篡改指纹 |
| `token` | — | ✅ 发客户端 | ✅ 随请求携带 | ✅ 被解析 | 用户身份凭证 |

---

## 6. 安全要点总结

1. **password_hash 管「你这个人对不对」**（登录 checkpw），**secret 管「token 这章真不真」**（验签 HMAC）。两件事平行、独立。
2. **payload 可读不可改**：base64 只是编码不是加密，但改内容后签名必然对不上。
3. **篡改必失败**：改内容留旧签 → 重算≠旧签 → 401；改内容再算新签 → 缺 secret → 401。
4. **secret 是唯一信任根**：只要 secret 不泄露，token 无法被伪造。
5. **username 唯一**：保障「按用户名查盐」唯一命中，无歧义。
6. **生产必须换强随机 secret**：默认值写死在代码里，公开即可伪造。

---

## 7. 关键代码位置索引

> `api-service` 已按层拆分（2026-09-11）：认证相关代码在 `core/security.py`，接口在 `routers/auth.py`，
> 用户中心接口在 `routers/users.py`。下表按**文件**定位，不再依赖行号（行号易随改动失效）。

| 功能 | 位置 |
|---|---|
| user 表（username UNIQUE） | `crawler-service/sql/mysql_schema.sql`（`CREATE TABLE IF NOT EXISTS user`） |
| `hash_password` / `verify_password` | `api-service/core/security.py` |
| `make_token` / `decode_token` | `api-service/core/security.py` |
| `get_current_user`（Bearer 依赖） | `api-service/core/security.py` |
| `register` / `login` / `me` 端点 | `api-service/routers/auth.py` |
| 收藏 / 历史端点 | `api-service/routers/users.py` |
| 请求体模型（`RegisterBody` 等） | `api-service/schemas.py` |
| 用户对外视图（`user_out`） | `api-service/serializers.py` |
| 存储句柄 `db` / `users` | `api-service/core/db.py` |

---

*本文档整理于 2026-09-04，对应 api-service 登录/收藏功能改动；2026-09-10 同步 user 表 DDL（MySQL，时间列 `DATETIME`）；2026-09-11 改为按文件索引（api-service 已分层拆分）。*
