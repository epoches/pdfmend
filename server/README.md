# Registration server（jyang.top）

> 状态：**已部署**（2026-11-17 验证接口，2026-11-18 增加申请/审核 + QQ SMTP）。
> 线上自测：
> `curl 'https://jyang.top/api/regfileconverter.php?id=admin&code=admin'` → `{"ok":true,...}`。
> 已用 `smtp.qq.com:465`（发件人 `641279141@qq.com`，密送同址）实测发出一封，
> 收件箱可见标题「PDFMend 注册码」。

## 三个接口

| 文件 | 谁用 | 作用 |
|---|---|---|
| `api/regrequest.php` | 用户 | 提交申请（注册名 + 邮箱 + 赞助单号 + 机器码），入 `reg_request` 表等审核 |
| `api/regadmin.php` | 作者 | 令牌保护的审核页：列表、批准（生成码 + 发邮件）、拒绝 |
| `api/regfileconverter.php` | 客户端 | 校验 `(用户名, 注册码)` 是否在 `reg` 表里 |

### 申请（客户端自动发）

```
POST https://jyang.top/api/regrequest.php
     id=<注册名>&email=<邮箱>&txn=<赞助单号>&mac=<机器码>
```

返回 `{"ok":true,"status":"pending","message":"已提交…"}`；同一用户名或单号
已提交过则返回 `status:"duplicate"`（不重复入库）。

### 审核（作者手动）

```
GET https://jyang.top/api/regadmin.php?token=<admin_token>              # HTML 列表
GET https://jyang.top/api/regadmin.php?token=<admin_token>&format=json  # JSON
GET https://jyang.top/api/regadmin.php?token=<admin_token>&approve=12   # 批准并生成/发信
GET https://jyang.top/api/regadmin.php?token=<admin_token>&reject=12    # 拒绝
```

批准时用「注册名 + 今天 + 申请里的机器码」生成注册码，写入 `reg` 表，
并尝试发邮件；发信失败时状态留在 `approved`、页面上会直接显示码，
把码手动发给用户即可（再次点「重发邮件」会重试）。

### 校验

```
GET https://jyang.top/api/regfileconverter.php?id=<用户名>&code=<注册码>
```

返回 `{"ok": true, "message": "valid", "username": "…"}`；`ok=false` 表示不匹配。

> **坑 1**：这台机器前面的 Web 层会拒绝 `Python-urllib/*` 的 User-Agent（403）。
> 客户端已经改成发 `PDFMend/<版本> (+repo)`；用脚本自测也请带普通 UA。
>
> **坑 2**：`POST` 请求必须带 `Content-Type: application/x-www-form-urlencoded`，
> 否则同样 403。

## 部署

1. 建库建表（含 `reg`、`reg_request`）并写入测试账号：

   ```bash
   mysql -u root -p < schema.sql
   ```

2. 复制 `config.sample.php` 为 `config.php`，填数据库账号、`admin_token`，
   需要发信时再填 `smtp` 段（见下）。

3. 把 `api/` 下四个文件（`lib.php`、`regrequest.php`、`regadmin.php`、
   `regfileconverter.php`）与 `config.php` 放到站点根：

   ```
   <站点根>/
     api/lib.php
     api/regrequest.php
     api/regadmin.php
     api/regfileconverter.php
     api/config.php          # 与 php 同目录，见 __DIR__；chmod 600
   ```

4. 自测：

   ```bash
   curl 'https://jyang.top/api/regfileconverter.php?id=admin&code=admin'
   curl -A 'PDFMend/0.8.0' -H 'Content-Type: application/x-www-form-urlencoded' \
        -d 'id=test&email=you@example.com&txn=4200000001&mac=A1B2C3D4E5F6' \
        'https://jyang.top/api/regrequest.php'
   ```

## 发邮件（SMTP）

`config.php` 里 `smtp` 段留空时退回 PHP `mail()`，那需要本机有可用的 MTA；
这台 ECS 的 `postfix` 是 inactive，且阿里云默认封 25 端口，所以**建议填 SMTP**：

```php
'smtp' => [
    'host' => 'smtp.qq.com',      // 或 smtp.163.com、你自己的域名邮箱
    'port' => 465,
    'secure' => 'ssl',
    'user' => 'you@qq.com',
    'pass' => '授权码（不是登录密码）',
],
'mail_from' => 'no-reply@jyang.top',
```

填好后在审核页点「批准」，页面会提示「已生成并发送」；失败则提示
「邮件发送失败，请手动发给用户」，码仍会显示在列表里。

## 发注册码（手工，备用）

```bash
python tools/gen_regcode.py --user 张三 --mac A1B2C3D4E5F6
python tools/gen_regcode.py --user 张三 --date 2026-11-17 --sql
```

```sql
INSERT INTO reg (username, regcode, machine) VALUES ('张三', '20261117-XXXXXXXX', 'A1B2C3D4E5F6');
```

## 安全

- 只用预处理语句，长度受限，错误不回显 SQL；`regadmin.php` 用 `hash_equals` 校验令牌。
- 数据库口令、SMTP 口令、`admin_token` 只在 `config.php`，不进仓库（`chmod 600`）。
- 申请接口可被刷，但不会生成任何码；审核是人工的，垃圾申请直接删表行。
- 码空间 80 bit（16 个 Base32 字符），线上枚举不可行。
