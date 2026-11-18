<?php
/**
 * Vendor side: review code requests and mint codes.
 *
 *   GET  /api/regadmin.php?token=...                 list requests (HTML)
 *   GET  /api/regadmin.php?token=...&format=json     list requests (JSON)
 *   GET  /api/regadmin.php?token=...&approve=12      mint + mail the code
 *   GET  /api/regadmin.php?token=...&reject=12       mark as rejected
 *
 * The token lives in config.php as `admin_token`.  Codes are generated with the
 * same HMAC recipe the app uses, from username + today's date + the machine code
 * the client submitted, so the user can also verify offline.
 */

declare(strict_types=1);

require __DIR__ . '/lib.php';

pdfmend_require_admin();

$format = (string) ($_GET['format'] ?? '');
$approve = isset($_GET['approve']) ? (int) $_GET['approve'] : 0;
$reject = isset($_GET['reject']) ? (int) $_GET['reject'] : 0;
$flash = '';

try {
    $pdo = pdfmend_pdo();

    if ($approve > 0) {
        $stmt = $pdo->prepare('SELECT * FROM reg_request WHERE id = :id LIMIT 1');
        $stmt->execute([':id' => $approve]);
        $row = $stmt->fetch();
        if (!$row) {
            $flash = '没有这条申请';
        } elseif ($row['status'] === 'rejected' || $row['status'] === 'sent') {
            $flash = '这条申请已处理过：' . $row['status'];
        } else {
            $code = pdfmend_code((string) $row['username'], (string) $row['machine']);
            $insert = $pdo->prepare(
                'INSERT IGNORE INTO reg (username, regcode, machine, note, created_at) '
                . 'VALUES (:user, :code, :mac, :note, NOW())'
            );
            $insert->execute([
                ':user' => $row['username'],
                ':code' => $code,
                ':mac' => $row['machine'],
                ':note' => 'request #' . $approve,
            ]);
            $body = "你好 " . $row['username'] . "：\n\n"
                . "感谢支持 PDFMend。你的注册码是：\n\n"
                . "    注册名：" . $row['username'] . "\n"
                . "    注册码：" . $code . "\n\n"
                . "打开 PDFMend →「关于」→「注册…」，填这两项即可；断网也能验证。\n"
                . "这个码绑定本机机器码 " . $row['machine'] . "，换机需要重新申请。\n\n"
                . "如果填错了或不需要了，忽略这封邮件即可。\n"
                . "—— PDFMend / https://github.com/epoches/pdfmend\n";
            $mailed = pdfmend_mail(
                (string) $row['email'],
                'PDFMend 注册码',
                $body,
                (string) (pdfmend_config()['notify_to'] ?? '')
            );
            $update = $pdo->prepare(
                'UPDATE reg_request SET status = :status, regcode = :code, approved_at = NOW(), mailed = :mailed '
                . 'WHERE id = :id'
            );
            $update->execute([
                ':status' => $mailed ? 'sent' : 'approved',
                ':code' => $code,
                ':mailed' => $mailed ? 1 : 0,
                ':id' => $approve,
            ]);
            $flash = $mailed
                ? '已生成并发送：' . $code
                : '已生成（邮件发送失败，请手动发给用户）：' . $code;
        }
    } elseif ($reject > 0) {
        $stmt = $pdo->prepare("UPDATE reg_request SET status = 'rejected', approved_at = NOW() WHERE id = :id");
        $stmt->execute([':id' => $reject]);
        $flash = '已拒绝';
    }

    $stmt = $pdo->query(
        "SELECT id, username, email, txn, machine, status, regcode, mailed, created_at, approved_at "
        . 'FROM reg_request ORDER BY id DESC LIMIT 200'
    );
    $rows = $stmt->fetchAll();
} catch (Throwable $exc) {
    error_log('regadmin: ' . $exc->getMessage());
    pdfmend_reply(500, ['ok' => false, 'message' => 'server error']);
}

if ($format === 'json') {
    pdfmend_reply(200, ['ok' => true, 'flash' => $flash, 'requests' => $rows]);
}

header('Content-Type: text/html; charset=utf-8');
?>
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>PDFMend 注册申请</title>
<style>
body{font:14px/1.6 -apple-system,"Microsoft YaHei",sans-serif;margin:24px;color:#1f2328}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #e3e6ea;padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f6f7f9;font-weight:600}
code{background:#f6f7f9;padding:1px 4px;border-radius:3px}
.flash{background:#eaf0ff;border:1px solid #cdd9ff;padding:10px 12px;border-radius:6px;margin-bottom:16px}
a{color:#2563eb;text-decoration:none}
a:hover{text-decoration:underline}
.muted{color:#667085}
</style>
</head>
<body>
<h1>PDFMend 注册申请</h1>
<?php if ($flash !== ''): ?>
<p class="flash"><?= htmlspecialchars($flash, ENT_QUOTES, 'UTF-8') ?></p>
<?php endif; ?>
<p class="muted">共 <?= count($rows) ?> 条。批准会生成注册码并尝试发邮件；发送失败时把码手动发给用户即可。</p>
<table>
<thead><tr><th>#</th><th>注册名</th><th>邮箱</th><th>赞助单号</th><th>机器码</th><th>状态</th><th>注册码</th><th>时间</th><th>操作</th></tr></thead>
<tbody>
<?php foreach ($rows as $row): ?>
<tr>
  <td><?= (int) $row['id'] ?></td>
  <td><?= htmlspecialchars((string) $row['username'], ENT_QUOTES, 'UTF-8') ?></td>
  <td><?= htmlspecialchars((string) $row['email'], ENT_QUOTES, 'UTF-8') ?></td>
  <td><?= htmlspecialchars((string) $row['txn'], ENT_QUOTES, 'UTF-8') ?></td>
  <td><code><?= htmlspecialchars((string) $row['machine'], ENT_QUOTES, 'UTF-8') ?></code></td>
  <td><?= htmlspecialchars((string) $row['status'], ENT_QUOTES, 'UTF-8') ?><?= $row['mailed'] ? ' (已发邮件)' : '' ?></td>
  <td><?= $row['regcode'] ? '<code>' . htmlspecialchars((string) $row['regcode'], ENT_QUOTES, 'UTF-8') . '</code>' : '—' ?></td>
  <td class="muted"><?= htmlspecialchars((string) $row['created_at'], ENT_QUOTES, 'UTF-8') ?></td>
  <td>
    <?php if ($row['status'] === 'pending'): ?>
      <a href="?token=<?= urlencode((string) ($_GET['token'] ?? '')) ?>&amp;approve=<?= (int) $row['id'] ?>">批准</a> ·
      <a href="?token=<?= urlencode((string) ($_GET['token'] ?? '')) ?>&amp;reject=<?= (int) $row['id'] ?>">拒绝</a>
    <?php elseif ($row['status'] === 'approved' && !$row['mailed']): ?>
      <a href="?token=<?= urlencode((string) ($_GET['token'] ?? '')) ?>&amp;approve=<?= (int) $row['id'] ?>">重发邮件</a>
    <?php else: ?>
      —
    <?php endif; ?>
  </td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
</body>
</html>
