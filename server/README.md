# Registration server（jyang.top）

> 状态：**已部署**（2026-11-17）。线上自测：
> `curl 'https://jyang.top/api/regfileconverter.php?id=admin&code=admin'` → `{"ok":true,...}`。

软件注册时请求：

```
GET https://jyang.top/api/regfileconverter.php?id=<用户名>&code=<注册码>
```

返回 JSON：

```json
{"ok": true, "message": "valid", "username": "admin"}
```

`ok=false` 表示用户名与注册码不匹配。`reg` 表里存在完全相同的
`(username, regcode)` 行才算通过。

> **坑**：这台机器前面的 Web 层会拒绝 `Python-urllib/*` 的 User-Agent（403）。
> 客户端已经改成发 `PDFMend/<版本> (+repo)`；用脚本自测时也请带上普通 UA，
> 否则会看到 403，误以为接口坏了。

## 部署

1. 建库建表并写入测试账号：

   ```bash
   mysql -u root -p < schema.sql
   ```

2. 把 `config.sample.php` 复制成 `config.php`，填数据库账号密码：

   ```bash
   cp config.sample.php config.php
   # 编辑 config.php
   ```

3. 把 `api/regfileconverter.php` 与 `config.php` 放到站点根目录：

   ```
   <站点根>/
     api/regfileconverter.php
     api/config.php          # 与 php 同目录，见 __DIR__
   ```

4. 自测：

   ```bash
   curl 'https://jyang.top/api/regfileconverter.php?id=admin&code=admin'
   # {"ok":true,"message":"valid","username":"admin"}
   ```

   注意：`config.php` 必须放在 `api/` 目录（脚本用 `__DIR__` 找它），
   不要提交到仓库。

## 发注册码

注册码由「用户名 + 注册日期 + 机器 MAC」算出，离线可验证：

```bash
python tools/gen_regcode.py --user 张三 --mac A1B2C3D4E5F6
python tools/gen_regcode.py --user 张三 --date 2026-11-17 --sql
```

把生成的码给用户，同时在 `reg` 表插一行（`--sql` 会直接打印 INSERT）：

```sql
INSERT INTO reg (username, regcode, machine) VALUES ('张三', '20261117-XXXXXXXX', 'A1B2C3D4E5F6');
```

用户没把机器码发来时，也可以先给码、后补 `machine` 字段；
本机验证只看用户名和码，不看数据库。

## 安全

- 只用预处理语句，`id/code` 长度受限，错误不回显 SQL。
- 数据库口令只在 `config.php`，不进仓库。
- 这个接口是「查询」：拿不到库也拿不到别人的码；但它不防暴力猜码，
  码空间是 80 bit（16 个 Base32 字符），线上够用。
