<?php
/**
 * Copy this file to config.php on the server and fill in the real credentials.
 * config.php must never be committed; chmod 600, chown apache.
 */

return [
    // database `fileconverter` on the same host as jyang.top
    'dsn' => 'mysql:host=127.0.0.1;dbname=fileconverter;charset=utf8mb4',
    'user' => 'fileconverter',
    'password' => 'CHANGE-ME',

    // protects api/regadmin.php; long random string, e.g.
    //   python -c "import secrets; print(secrets.token_urlsafe(24))"
    'admin_token' => 'CHANGE-ME-TOO',

    // From: address for registration mails
    'mail_from' => 'no-reply@jyang.top',

    // Real mailbox for sending. Leave host empty to fall back to PHP mail()
    // (needs a working local MTA; Aliyun ECS blocks port 25 by default).
    'smtp' => [
        'host' => '',
        'port' => 465,
        'secure' => 'ssl',   // ssl (465) or tls (587)
        'user' => '',
        'pass' => '',        // authorization code, not the login password
    ],
];
