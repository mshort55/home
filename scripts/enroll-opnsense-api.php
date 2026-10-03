<?php
declare(strict_types=1);
require_once('config.inc');

const OWNERSHIP_MARKER = 'Managed by configure-opnsense-api.yml';
const LEGACY_OWNERSHIP_MARKER = 'Managed by configure-community-api.yml';

function ensure(bool $condition, string $message): void
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

function protect(string $path, int $mode): void
{
    ensure(!is_link($path), 'Symlink API artifact');
    if (file_exists($path)) {
        ensure(fileowner($path) === 0 && (fileperms($path) & 0777) === $mode, 'Unprotected API artifact');
    }
}

try {
    [$script, $operation, $address] = $argv;
    ensure(in_array($operation, ['plan', 'apply'], true), 'Unknown enrollment operation');
    ensure(filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false, 'Invalid inventory IP');
    $cnf = \OPNsense\Core\Config::getInstance();
    if ($operation === 'apply') {
        $cnf->lock();
    }
    $xml = $cnf->object();
    $seed = json_decode(file_get_contents('/conf/ansible-install.json'), true, 512, JSON_THROW_ON_ERROR);
    ensure($seed['address'] === $address && (string)$xml->interfaces->lan->ipaddr === $address, 'Guest identity conflicts');
    $directory = '/conf/ansible-api';
    $record = $directory . '/credentials.json';
    foreach ([$directory => 0700, $record => 0600, $directory . '/server.pem' => 0600, $directory . '/server.key' => 0600] as $path => $mode) {
        protect($path, $mode);
    }
    $mdl = new \OPNsense\Auth\User();
    $user = $mdl->getUserByName('home-ansible');
    $privileges = 'page-filter-api,page-services-unbound';
    if ($user !== null) {
        ensure(in_array((string)$user->descr, [OWNERSHIP_MARKER, LEGACY_OWNERSHIP_MARKER], true), 'Conflicting API user');
        ensure(file_exists($record), 'Missing original API credentials; refusing key rotation');
        ensure((string)$user->priv === $privileges && (string)$user->disabled === '0', 'API user privileges conflict');
    }
    $credentials = file_exists($record) ? json_decode(file_get_contents($record), true, 512, JSON_THROW_ON_ERROR) : null;
    if ($credentials !== null) {
        ensure($credentials['firewall'] === $address && $credentials['seed_id'] === $seed['seed_id'], 'Saved enrollment identity conflicts');
        if ($user !== null) {
            $stored = $user->apikeys->get($credentials['api_key']);
            ensure($stored !== null && hash_equals($stored['secret'], crypt($credentials['api_secret'], $stored['secret'])), 'Saved API key conflicts');
        }
    }
    // Later releases disable KTLS in the web GUI itself; leave those untouched.
    $version = trim((string)shell_exec('/usr/local/sbin/opnsense-version'));
    $ktlsAffected = preg_match('/^OPNsense 26\.7 \(/', $version) === 1;
    $tunables = null;
    $ktlsTunable = null;
    $ktlsConfigChanged = false;
    $ktlsRuntimeChanged = false;
    if ($ktlsAffected) {
        $tunables = new \OPNsense\Core\Tunables();
        foreach ($tunables->item->iterateItems() as $item) {
            if ((string)$item->tunable === 'kern.ipc.tls.enable') {
                ensure($ktlsTunable === null, 'Duplicate kernel TLS tunables');
                $ktlsTunable = $item;
                ensure(in_array((string)$item->value, ['', '0'], true), 'Conflicting kernel TLS tunable');
            }
        }
        $ktlsConfigChanged = $ktlsTunable === null || (string)$ktlsTunable->value !== '0';
        $ktlsRuntimeChanged = trim((string)shell_exec('/sbin/sysctl -n kern.ipc.tls.enable')) !== '0';
    }
    $certificateMatches = $credentials !== null && (string)$xml->system->webgui->{'ssl-certref'} === ($credentials['certificate_ref'] ?? '');
    if ($certificateMatches) {
        ensure(is_file($directory . '/server.pem') && is_file($directory . '/server.key'), 'Missing original enrolled certificate; refusing replacement');
    }
    $changed = $user === null || !$certificateMatches || $ktlsConfigChanged || $ktlsRuntimeChanged;
    $restartRequired = !$certificateMatches || $ktlsRuntimeChanged;
    if ($certificateMatches) {
        exec('/usr/local/bin/openssl s_client -connect 127.0.0.1:443 -verify_return_error -verify_ip ' . escapeshellarg($address) . ' -CAfile ' . escapeshellarg($directory . '/server.pem') . ' -brief < /dev/null 2>/dev/null', $unused, $verifyRc);
        $restartRequired = $restartRequired || $verifyRc !== 0;
    }
    if ($operation === 'apply') {
        if (!is_dir($directory)) {
            ensure(mkdir($directory, 0700), 'Cannot create enrollment directory');
        }
        if ($credentials === null) {
            $credentials = ['firewall' => $address, 'seed_id' => $seed['seed_id'], 'api_key' => base64_encode(random_bytes(60)), 'api_secret' => base64_encode(random_bytes(60)), 'certificate_ref' => bin2hex(random_bytes(6)) . 'a'];
            // Persist recoverable key material before saving any vendor configuration.
            $handle = fopen($record, 'x');
            ensure($handle !== false, 'Cannot create enrollment record');
            chmod($record, 0600);
            fwrite($handle, json_encode($credentials, JSON_THROW_ON_ERROR));
            fclose($handle);
        }
        if (!file_exists($directory . '/server.pem')) {
            $fqdn = (string)$xml->system->hostname . '.' . (string)$xml->system->domain;
            ensure(preg_match('/^[A-Za-z0-9.-]+$/', $fqdn) === 1, 'Invalid certificate hostname');
            $command = '/usr/local/bin/openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 825 -subj ' . escapeshellarg('/CN=' . $fqdn)
                . ' -addext ' . escapeshellarg('subjectAltName=IP:' . $address . ',DNS:' . $fqdn)
                . ' -addext ' . escapeshellarg('basicConstraints=critical,CA:FALSE')
                . ' -addext ' . escapeshellarg('extendedKeyUsage=serverAuth')
                . ' -keyout ' . escapeshellarg($directory . '/server.key') . ' -out ' . escapeshellarg($directory . '/server.pem') . ' 2>/dev/null';
            exec($command, $unused, $rc);
            ensure($rc === 0, 'Cannot generate API certificate');
            chmod($directory . '/server.key', 0600);
            chmod($directory . '/server.pem', 0600);
        }
        $parsed = openssl_x509_parse(file_get_contents($directory . '/server.pem'));
        ensure($parsed !== false && str_contains($parsed['extensions']['subjectAltName'] ?? '', 'IP Address:' . $address), 'Certificate IP conflicts');
        if ($changed) {
            if (!file_exists($directory . '/before.xml')) {
                ensure(copy('/conf/config.xml', $directory . '/before.xml'), 'Cannot preserve original configuration');
                chmod($directory . '/before.xml', 0600);
            }
            if ($user === null) {
                $user = $mdl->user->add();
                $user->setNodes(['name' => 'home-ansible', 'descr' => OWNERSHIP_MARKER, 'disabled' => '0', 'scope' => 'user', 'shell' => '', 'password' => $mdl->generatePasswordHash(bin2hex(random_bytes(32))), 'priv' => $privileges]);
                $user->apikeys->setValue($credentials['api_key'] . '|' . crypt($credentials['api_secret'], '$6$'));
                $errors = $mdl->performValidation(true);
                $messages = [];
                foreach ($errors as $error) {
                    $messages[] = $error->getField() . ': ' . $error->getMessage();
                }
                ensure(count($errors) === 0, 'API user model validation failed: ' . implode('; ', $messages));
                $mdl->serializeToConfig(true);
            }
            $certs = new \OPNsense\Trust\Cert();
            $cert = null;
            foreach ($certs->cert->iterateItems() as $item) {
                if ((string)$item->refid === $credentials['certificate_ref']) {
                    $cert = $item;
                }
            }
            if ($cert === null) {
                $cert = $certs->cert->add();
                $cert->setNodes(['refid' => $credentials['certificate_ref'], 'descr' => 'Managed API and GUI certificate', 'crt' => base64_encode(file_get_contents($directory . '/server.pem')), 'prv' => base64_encode(file_get_contents($directory . '/server.key'))]);
                ensure(count($certs->performValidation(true)) === 0, 'Certificate model validation failed');
                $certs->serializeToConfig(true);
            }
            if ($ktlsConfigChanged) {
                $ktlsTunable ??= $tunables->item->add();
                $ktlsTunable->setNodes(['tunable' => 'kern.ipc.tls.enable', 'value' => '0', 'descr' => 'Ansible: OPNsense 26.7 HTTPS response corruption workaround']);
                ensure(count($tunables->performValidation(true)) === 0, 'Kernel TLS tunable validation failed');
                $tunables->serializeToConfig(true);
            }
            $xml->system->webgui->{'ssl-certref'} = $credentials['certificate_ref'];
            $cnf->save(['description' => 'Ansible community API enrollment']);
        }
    }
    $cnf->unlock();
    if ($operation === 'apply' && $ktlsRuntimeChanged) {
        exec('/sbin/sysctl kern.ipc.tls.enable=0 >/dev/null', $unused, $ktlsRc);
        ensure($ktlsRc === 0, 'Cannot apply kernel TLS workaround');
    }
    echo json_encode(['changed' => $changed, 'restart_required' => $restartRequired], JSON_THROW_ON_ERROR) . "\n";
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . "\n");
    exit(1);
}
