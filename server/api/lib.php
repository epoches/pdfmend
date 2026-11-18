<?php
/**
 * Shared helpers for the PDFMend registration endpoints.
 *
 * Two front doors:
 *   api/regrequest.php   - a user asks for a code (email + name + donation id)
 *   api/regfileconverter.php - the app checks a (name, code) pair
 *   api/regadmin.php     - the vendor approves requests and mints codes
 *
 * Codes are derived exactly like the client does it, so a code can be checked
 * offline:
 *   YYYYMMDD-BASE32(HMAC-SHA256(SECRET, "name|YYYYMMDD|MAC"))[:16]
 */

declare(strict_types=1);

const PDFMEND_SECRET = 'pdfmend-reg-2026-epoches';
const PDFMEND_B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

function pdfmend_config(): array
{
    static $config = null;
    if ($config === null) {
        $file = __DIR__ . '/config.php';
        $config = is_file($file) ? (array) require $file : [];
    }
    return $config;
}

function pdfmend_pdo(): PDO
{
    $config = pdfmend_config();
    $pdo = new PDO(
        (string) ($config['dsn'] ?? 'mysql:host=127.0.0.1;dbname=fileconverter;charset=utf8mb4'),
        (string) ($config['user'] ?? 'root'),
        (string) ($config['password'] ?? ''),
        [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]
    );
    return $pdo;
}

function pdfmend_reply(int $status, array $payload): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function pdfmend_base32(string $raw): string
{
    $bits = '';
    foreach (str_split($raw) as $char) {
        $bits .= str_pad(decbin(ord($char)), 8, '0', STR_PAD_LEFT);
    }
    $out = '';
    foreach (str_split($bits, 5) as $chunk) {
        if (strlen($chunk) < 5) {
            $chunk = str_pad($chunk, 5, '0', STR_PAD_RIGHT);
        }
        $out .= PDFMEND_B32[bindec($chunk)];
    }
    return $out;
}

function pdfmend_code(string $user, string $mac, ?string $day = null): string
{
    $day = $day ?: date('Ymd');
    $payload = strtolower(trim($user)) . '|' . $day . '|' . strtoupper(trim($mac));
    $digest = pdfmend_base32(hash_hmac('sha256', $payload, PDFMEND_SECRET, true));
    return $day . '-' . substr($digest, 0, 16);
}

/**
 * Send the code by mail.  Uses SMTP when config.php carries an `smtp` block,
 * otherwise falls back to PHP's mail() (needs a working local MTA).
 */
function pdfmend_mail(string $to, string $subject, string $body, string $bcc = ''): bool
{
    $config = pdfmend_config();
    $from = (string) ($config['mail_from'] ?? 'no-reply@jyang.top');
    $smtp = $config['smtp'] ?? null;
    if (is_array($smtp) && !empty($smtp['host'])) {
        return pdfmend_smtp($smtp, $from, $to, $subject, $body, $bcc);
    }
    $headers = "From: PDFMend <{$from}>\r\n"
        . ($bcc !== '' ? "Bcc: <{$bcc}>\r\n" : '')
        . "MIME-Version: 1.0\r\n"
        . "Content-Type: text/plain; charset=UTF-8\r\n";
    $encoded = '=?UTF-8?B?' . base64_encode($subject) . '?=';
    return @mail($to, $encoded, $body, $headers);
}

function pdfmend_smtp(array $smtp, string $from, string $to, string $subject, string $body, string $bcc = ''): bool
{
    $host = (string) $smtp['host'];
    $port = (int) ($smtp['port'] ?? 465);
    $secure = (string) ($smtp['secure'] ?? 'ssl');
    $user = (string) ($smtp['user'] ?? '');
    $pass = (string) ($smtp['pass'] ?? '');
    $target = ($secure === 'ssl' ? 'ssl://' : 'tcp://') . $host . ':' . $port;
    $socket = @stream_socket_client($target, $errno, $errstr, 15);
    if (!$socket) {
        error_log("pdfmend mail: connect failed {$errno} {$errstr}");
        return false;
    }
    stream_set_timeout($socket, 15);
    $read = static function () use ($socket): string {
        $data = '';
        while (($line = fgets($socket, 1024)) !== false) {
            $data .= $line;
            if (strlen($line) < 4 || $line[3] !== '-') {
                break;
            }
        }
        return $data;
    };
    $write = static function (string $line) use ($socket): void {
        fwrite($socket, $line . "\r\n");
    };
    $read();
    $write('EHLO pdfmend');
    $read();
    if ($secure === 'tls') {
        $write('STARTTLS');
        $read();
        if (!stream_socket_enable_crypto($socket, true, STREAM_CRYPTO_METHOD_TLS_CLIENT)) {
            fclose($socket);
            return false;
        }
        $write('EHLO pdfmend');
        $read();
    }
    if ($user !== '') {
        $write('AUTH LOGIN');
        $read();
        $write(base64_encode($user));
        $read();
        $write(base64_encode($pass));
        $auth = $read();
        if (strpos($auth, '235') !== 0) {
            error_log('pdfmend mail: auth rejected');
            fclose($socket);
            return false;
        }
    }
    $write('MAIL FROM:<' . $from . '>');
    $read();
    $write('RCPT TO:<' . $to . '>');
    $read();
    if ($bcc !== '') {
        $write('RCPT TO:<' . $bcc . '>');
        $read();
    }
    $write('DATA');
    $read();
    $headers = "From: PDFMend <{$from}>\r\n"
        . "To: <{$to}>\r\n"
        . 'Subject: =?UTF-8?B?' . base64_encode($subject) . "?=\r\n"
        . "MIME-Version: 1.0\r\n"
        . "Content-Type: text/plain; charset=UTF-8\r\n"
        . "Content-Transfer-Encoding: base64\r\n";
    $write($headers);
    $write(chunk_split(base64_encode($body)));
    $write('.');
    $result = $read();
    $write('QUIT');
    fclose($socket);
    return strpos($result, '250') === 0;
}

function pdfmend_require_admin(): void
{
    $config = pdfmend_config();
    $token = (string) ($config['admin_token'] ?? '');
    $given = (string) ($_GET['token'] ?? $_POST['token'] ?? '');
    if ($token === '' || $given === '') {
        pdfmend_reply(403, ['ok' => false, 'message' => 'missing admin token']);
    }
    if (!hash_equals($token, $given)) {
        pdfmend_reply(403, ['ok' => false, 'message' => 'bad admin token']);
    }
}
