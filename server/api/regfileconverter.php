<?php
/**
 * PDFMend registration endpoint.
 *
 *   GET /api/regfileconverter.php?id=<username>&code=<code>
 *
 * Answers JSON: {"ok": true|false, "message": "...", "username": "..."}
 *
 * The database is the source of truth: a pair is valid only when the exact
 * (username, regcode) row exists in `reg`. Codes are minted offline by
 * tools/gen_regcode.py from username + issue date + machine MAC, so the app
 * can also verify them without calling this endpoint at all.
 */

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function reply(int $status, array $payload): void
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

$configFile = __DIR__ . '/config.php';
if (!is_file($configFile)) {
    reply(500, ['ok' => false, 'message' => 'server not configured']);
}
$config = require $configFile;

$id = isset($_GET['id']) ? trim((string) $_GET['id']) : '';
$code = isset($_GET['code']) ? strtoupper(trim((string) $_GET['code'])) : '';

if ($id === '' || $code === '') {
    reply(400, ['ok' => false, 'message' => 'missing id or code']);
}
if (strlen($id) > 64 || strlen($code) > 64) {
    reply(400, ['ok' => false, 'message' => 'input too long']);
}

try {
    $pdo = new PDO(
        $config['dsn'],
        $config['user'],
        $config['password'],
        [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]
    );

    $stmt = $pdo->prepare(
        'SELECT 1 FROM reg WHERE username = :user AND regcode = :code LIMIT 1'
    );
    $stmt->execute([':user' => $id, ':code' => $code]);
    $valid = (bool) $stmt->fetchColumn();

    reply(200, [
        'ok' => $valid,
        'message' => $valid ? 'valid' : 'invalid',
        'username' => $id,
    ]);
} catch (Throwable $exc) {
    // Never leak credentials or SQL details to the client.
    error_log('regfileconverter: ' . $exc->getMessage());
    reply(500, ['ok' => false, 'message' => 'server error']);
}
