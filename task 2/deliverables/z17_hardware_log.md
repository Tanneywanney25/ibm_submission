# IBM z17 hardware execution log (Workstream 2, measured on the real project files)

- Machine: `processor 0: version = FF,  identification = 09DFD8,  machine = 9175`, `uname -m` = s390x, 3 virtual cores, kernel 6.8.0-147-generic
- Facilities: dflt (on-chip deflate) = True, nnpa (Telum AI accelerator) = True, vx = True
- zlib 1.3 (DFLTCC build), OpenSSL 3.0.13 30 Jan 2024 (Library: OpenSSL 3.0.13 30 Jan 2024), Python 3.12.3; Crypto Express: no Crypto Express cards

## 2. Apartment pseudonymization (HMAC-SHA256, per row)

- 2,219,844 complaint rows hashed in 5.85 s = 379,380 rows/s (3.5 MB/s of message bytes, Python call overhead dominates)
- 15,885 distinct raw apartment labels became 502,141 distinct 64-bit tags; the raw column is dropped from every working table
- 223,430 violation rows hashed in 0.63 s

## 3. Compression and encryption of the staged extracts, hardware on vs off

| variant | file | operation | in MB | out MB | ratio | seconds | MB/s |
|---|---|---|---|---|---|---|---|
| hardware on (DFLTCC default, CPACF on) | raw complaints ygpa-z7cr.csv | zlib compress level 1 | 344.8 | 106.9 | 3.22 | 0.191 | 1,801 |
| hardware on (DFLTCC default, CPACF on) | raw complaints ygpa-z7cr.csv | zlib decompress level 1 | 106.9 | 344.8 | 3.22 | 0.495 | 696 |
| hardware on (DFLTCC default, CPACF on) | raw complaints ygpa-z7cr.csv | zlib compress level 6 | 344.8 | 106.9 | 3.22 | 0.164 | 2,104 |
| hardware on (DFLTCC default, CPACF on) | raw complaints ygpa-z7cr.csv | zlib decompress level 6 | 106.9 | 344.8 | 3.22 | 0.499 | 691 |
| hardware on (DFLTCC default, CPACF on) | raw complaints ygpa-z7cr.csv | AES-256-GCM encrypt (64 MB chunks) | 344.8 | 344.8 | 1.00 | 0.481 | 717 |
| hardware on (DFLTCC default, CPACF on) | raw complaints ygpa-z7cr.csv | SHA-256 digest (hashlib/OpenSSL) | 344.8 | 0.0 | 1.00 | 0.243 | 1,418 |
| hardware on (DFLTCC default, CPACF on) | raw complaints ygpa-z7cr.csv | HMAC-SHA256 digest | 344.8 | 0.0 | 1.00 | 0.250 | 1,378 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | zlib compress level 1 | 266.6 | 111.5 | 2.39 | 0.150 | 1,776 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | zlib decompress level 1 | 111.5 | 266.6 | 2.39 | 0.367 | 726 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | zlib compress level 6 | 266.6 | 111.5 | 2.39 | 0.134 | 1,995 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | zlib decompress level 6 | 111.5 | 266.6 | 2.39 | 0.374 | 712 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv (zlib-6 stream) | AES-256-GCM encrypt (OpenSSL via python cryptography) | 111.5 | 111.5 | 1.00 | 0.135 | 823 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv (zlib-6 stream) | AES-256-GCM decrypt+verify | 111.5 | 111.5 | 1.00 | 0.134 | 830 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | AES-256-GCM encrypt (64 MB chunks) | 266.6 | 266.6 | 1.00 | 0.357 | 746 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | SHA-256 digest (hashlib/OpenSSL) | 266.6 | 0.0 | 1.00 | 0.187 | 1,425 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | HMAC-SHA256 digest | 266.6 | 0.0 | 1.00 | 0.201 | 1,324 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv | zlib compress level 1 | 25.8 | 9.5 | 2.73 | 0.010 | 2,490 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv | zlib decompress level 1 | 9.5 | 25.8 | 2.73 | 0.038 | 685 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv | zlib compress level 6 | 25.8 | 9.5 | 2.73 | 0.003 | 8,510 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv | zlib decompress level 6 | 9.5 | 25.8 | 2.73 | 0.021 | 1,256 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv (zlib-6 stream) | AES-256-GCM encrypt (OpenSSL via python cryptography) | 9.5 | 9.5 | 1.00 | 0.010 | 932 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv (zlib-6 stream) | AES-256-GCM decrypt+verify | 9.5 | 9.5 | 1.00 | 0.010 | 942 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv | AES-256-GCM encrypt (64 MB chunks) | 25.8 | 25.8 | 1.00 | 0.022 | 1,177 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv | SHA-256 digest (hashlib/OpenSSL) | 25.8 | 0.0 | 1.00 | 0.006 | 4,085 |
| hardware on (DFLTCC default, CPACF on) | staged violations_pseud.csv | HMAC-SHA256 digest | 25.8 | 0.0 | 1.00 | 0.006 | 4,290 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | openssl enc -aes-256-ctr -pbkdf2 (CLI; enc has no GCM mode) | 266.6 | 266.6 | 1.00 | 0.187 | 1,423 |
| hardware on (DFLTCC default, CPACF on) | staged complaints_pseud.csv | openssl dgst -sha256 -hmac (CLI) | 266.6 | 0.0 | 1.00 | 0.122 | 2,191 |
| DFLTCC=0 (deflate in software) | raw complaints ygpa-z7cr.csv | zlib compress level 1 | 344.8 | 91.2 | 3.78 | 2.842 | 121 |
| DFLTCC=0 (deflate in software) | raw complaints ygpa-z7cr.csv | zlib decompress level 1 | 91.2 | 344.8 | 3.78 | 1.313 | 263 |
| DFLTCC=0 (deflate in software) | raw complaints ygpa-z7cr.csv | zlib compress level 6 | 344.8 | 70.7 | 4.88 | 10.261 | 34 |
| DFLTCC=0 (deflate in software) | raw complaints ygpa-z7cr.csv | zlib decompress level 6 | 70.7 | 344.8 | 4.88 | 1.188 | 290 |
| DFLTCC=0 (deflate in software) | raw complaints ygpa-z7cr.csv | AES-256-GCM encrypt (64 MB chunks) | 344.8 | 344.8 | 1.00 | 0.472 | 731 |
| DFLTCC=0 (deflate in software) | raw complaints ygpa-z7cr.csv | SHA-256 digest (hashlib/OpenSSL) | 344.8 | 0.0 | 1.00 | 0.244 | 1,415 |
| DFLTCC=0 (deflate in software) | raw complaints ygpa-z7cr.csv | HMAC-SHA256 digest | 344.8 | 0.0 | 1.00 | 0.245 | 1,406 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | zlib compress level 1 | 266.6 | 88.5 | 3.01 | 2.466 | 108 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | zlib decompress level 1 | 88.5 | 266.6 | 3.01 | 1.139 | 234 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | zlib compress level 6 | 266.6 | 75.5 | 3.53 | 8.161 | 33 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | zlib decompress level 6 | 75.5 | 266.6 | 3.53 | 1.114 | 239 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv (zlib-6 stream) | AES-256-GCM encrypt (OpenSSL via python cryptography) | 75.5 | 75.5 | 1.00 | 0.089 | 851 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv (zlib-6 stream) | AES-256-GCM decrypt+verify | 75.5 | 75.5 | 1.00 | 0.086 | 880 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | AES-256-GCM encrypt (64 MB chunks) | 266.6 | 266.6 | 1.00 | 0.365 | 730 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | SHA-256 digest (hashlib/OpenSSL) | 266.6 | 0.0 | 1.00 | 0.205 | 1,298 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | HMAC-SHA256 digest | 266.6 | 0.0 | 1.00 | 0.189 | 1,408 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv | zlib compress level 1 | 25.8 | 7.7 | 3.34 | 0.221 | 117 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv | zlib decompress level 1 | 7.7 | 25.8 | 3.34 | 0.105 | 245 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv | zlib compress level 6 | 25.8 | 6.5 | 4.00 | 0.739 | 35 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv | zlib decompress level 6 | 6.5 | 25.8 | 4.00 | 0.091 | 283 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv (zlib-6 stream) | AES-256-GCM encrypt (OpenSSL via python cryptography) | 6.5 | 6.5 | 1.00 | 0.007 | 974 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv (zlib-6 stream) | AES-256-GCM decrypt+verify | 6.5 | 6.5 | 1.00 | 0.006 | 1,059 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv | AES-256-GCM encrypt (64 MB chunks) | 25.8 | 25.8 | 1.00 | 0.022 | 1,157 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv | SHA-256 digest (hashlib/OpenSSL) | 25.8 | 0.0 | 1.00 | 0.006 | 4,221 |
| DFLTCC=0 (deflate in software) | staged violations_pseud.csv | HMAC-SHA256 digest | 25.8 | 0.0 | 1.00 | 0.006 | 4,320 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | openssl enc -aes-256-ctr -pbkdf2 (CLI; enc has no GCM mode) | 266.6 | 266.6 | 1.00 | 0.187 | 1,428 |
| DFLTCC=0 (deflate in software) | staged complaints_pseud.csv | openssl dgst -sha256 -hmac (CLI) | 266.6 | 0.0 | 1.00 | 0.125 | 2,128 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | raw complaints ygpa-z7cr.csv | zlib compress level 1 | 344.8 | 106.9 | 3.22 | 0.168 | 2,046 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | raw complaints ygpa-z7cr.csv | zlib decompress level 1 | 106.9 | 344.8 | 3.22 | 0.506 | 681 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | raw complaints ygpa-z7cr.csv | zlib compress level 6 | 344.8 | 106.9 | 3.22 | 0.165 | 2,091 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | raw complaints ygpa-z7cr.csv | zlib decompress level 6 | 106.9 | 344.8 | 3.22 | 0.506 | 682 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | raw complaints ygpa-z7cr.csv | AES-256-GCM encrypt (64 MB chunks) | 344.8 | 344.8 | 1.00 | 3.181 | 108 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | raw complaints ygpa-z7cr.csv | SHA-256 digest (hashlib/OpenSSL) | 344.8 | 0.0 | 1.00 | 1.320 | 261 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | raw complaints ygpa-z7cr.csv | HMAC-SHA256 digest | 344.8 | 0.0 | 1.00 | 1.325 | 260 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | zlib compress level 1 | 266.6 | 111.5 | 2.39 | 0.158 | 1,692 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | zlib decompress level 1 | 111.5 | 266.6 | 2.39 | 0.373 | 715 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | zlib compress level 6 | 266.6 | 111.5 | 2.39 | 0.133 | 1,999 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | zlib decompress level 6 | 111.5 | 266.6 | 2.39 | 0.352 | 757 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv (zlib-6 stream) | AES-256-GCM encrypt (OpenSSL via python cryptography) | 111.5 | 111.5 | 1.00 | 0.992 | 112 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv (zlib-6 stream) | AES-256-GCM decrypt+verify | 111.5 | 111.5 | 1.00 | 0.977 | 114 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | AES-256-GCM encrypt (64 MB chunks) | 266.6 | 266.6 | 1.00 | 2.431 | 110 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | SHA-256 digest (hashlib/OpenSSL) | 266.6 | 0.0 | 1.00 | 1.034 | 258 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | HMAC-SHA256 digest | 266.6 | 0.0 | 1.00 | 1.038 | 257 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv | zlib compress level 1 | 25.8 | 9.5 | 2.73 | 0.010 | 2,479 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv | zlib decompress level 1 | 9.5 | 25.8 | 2.73 | 0.039 | 668 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv | zlib compress level 6 | 25.8 | 9.5 | 2.73 | 0.003 | 8,651 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv | zlib decompress level 6 | 9.5 | 25.8 | 2.73 | 0.022 | 1,149 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv (zlib-6 stream) | AES-256-GCM encrypt (OpenSSL via python cryptography) | 9.5 | 9.5 | 1.00 | 0.085 | 111 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv (zlib-6 stream) | AES-256-GCM decrypt+verify | 9.5 | 9.5 | 1.00 | 0.085 | 111 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv | AES-256-GCM encrypt (64 MB chunks) | 25.8 | 25.8 | 1.00 | 0.223 | 116 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv | SHA-256 digest (hashlib/OpenSSL) | 25.8 | 0.0 | 1.00 | 0.101 | 257 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged violations_pseud.csv | HMAC-SHA256 digest | 25.8 | 0.0 | 1.00 | 0.100 | 258 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | openssl enc -aes-256-ctr -pbkdf2 (CLI; enc has no GCM mode) | 266.6 | 266.6 | 1.00 | 1.525 | 175 |
| CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap) | staged complaints_pseud.csv | openssl dgst -sha256 -hmac (CLI) | 266.6 | 0.0 | 1.00 | 1.116 | 239 |

## 4. openssl speed, 16 KB blocks, one core

| algorithm | mode | GB/s |
|---|---|---|
| aes-256-gcm | CPACF on | 14.18 |
| aes-256-gcm | CPACF masked | 0.13 |
| sha256 | CPACF on | 4.18 |
| sha256 | CPACF masked | 0.26 |
