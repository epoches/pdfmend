-- PDFMend registration database (MySQL / MariaDB).
--
--   mysql -u root -p < schema.sql
--
-- A pair is valid only when the exact (username, regcode) row exists.
-- `admin` / `admin` is the built-in test pair; delete it in production.

CREATE DATABASE IF NOT EXISTS `fileconverter`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `fileconverter`;

CREATE TABLE IF NOT EXISTS `reg` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username`   VARCHAR(64)  NOT NULL,
  `regcode`    VARCHAR(64)  NOT NULL,
  `machine`    VARCHAR(32)  DEFAULT NULL COMMENT 'MAC the code was issued for, for the vendor',
  `note`       VARCHAR(255) DEFAULT NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_code` (`username`, `regcode`),
  KEY `idx_user` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `reg` (`username`, `regcode`, `note`)
VALUES ('admin', 'admin', 'built-in test pair — remove in production')
ON DUPLICATE KEY UPDATE `note` = VALUES(`note`);
