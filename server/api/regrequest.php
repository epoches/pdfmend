<?php
/**
 * A user asks for a registration code.
 *
 *   POST /api/regrequest.php
 *     id     = login name the code should be bound to
 *     email  = where the code should be sent
 *     txn    = donation / order number (proof of support)
 *     mac    = the machine code shown in the app
 *
 * Answers JSON: {"ok": true, "message": "...", "status": "pending|duplicate"}
 *
 * Nothing is minted here: the vendor approves in api/regadmin.php and only then
 * does the code get written to `reg` and mailed.  That keeps a stolen machine
 * code from minting itself a licence.
 */

declare(strict_types=1);

require __DIR__ . '/lib.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST' && empty($_POST) && empty($_GET)) {
    pdfmend_reply(405, ['ok' => false, 'message' => 'use POST']);
}

$id = trim((string) ($_POST['id'] ?? $_GET['id'] ?? ''));
$email = trim((string) ($_POST['email'] ?? $_GET['email'] ?? ''));
$txn = trim((string) ($_POST['txn'] ?? $_GET['txn'] ?? ''));
$mac = strtoupper(preg_replace('/[^0-9A-Fa-f]/', '', (string) ($_POST['mac'] ?? $_GET['mac'] ?? '')));

if ($id === '' || $email === '' || $txn === '') {
    pdfmend_reply(400, ['ok' => false, 'message' => 'missing id, email or txn']);
}
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    pdfmend_reply(400, ['ok' => false, 'message' => 'invalid email']);
}
if (strlen($id) > 64 || strlen($email) > 190 || strlen($txn) > 64) {
    pdfmend_reply(400, ['ok' => false, 'message' => 'input too long']);
}

try {
    $pdo = pdfmend_pdo();

    $check = $pdo->prepare(
        'SELECT id, status FROM reg_request WHERE (username = :user OR txn = :txn) '
        . "AND status IN ('pending', 'approved', 'sent') ORDER BY id DESC LIMIT 1"
    );
    $check->execute([':user' => $id, ':txn' => $txn]);
    $existing = $check->fetch();
    if ($existing) {
        pdfmend_reply(200, [
            'ok' => true,
            'status' => 'duplicate',
            'message' => '这个用户名或单号已经提交过，请等待邮件；若长时间没收到请联系作者。',
        ]);
    }

    $stmt = $pdo->prepare(
        'INSERT INTO reg_request (username, email, txn, machine, status, created_at, ip) '
        . 'VALUES (:user, :email, :txn, :mac, :status, NOW(), :ip)'
    );
    $stmt->execute([
        ':user' => $id,
        ':email' => $email,
        ':txn' => $txn,
        ':mac' => $mac,
        ':status' => 'pending',
        ':ip' => substr((string) ($_SERVER['REMOTE_ADDR'] ?? ''), 0, 64),
    ]);

    pdfmend_reply(200, [
        'ok' => true,
        'status' => 'pending',
        'message' => '已提交。审核通过后会把注册码发到 ' . $email . '，收到后回到「注册」里填写即可。',
    ]);
} catch (Throwable $exc) {
    error_log('regrequest: ' . $exc->getMessage());
    pdfmend_reply(500, ['ok' => false, 'message' => 'server error']);
}
