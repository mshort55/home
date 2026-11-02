<?php
declare(strict_types=1);
require_once('config.inc');
// DHCP_LIBRARY
try {
    $mode = $argv[1] ?? '';
    dhcpRequire(in_array($mode, ['plan','apply','verify','complete'], true), 'Unknown DHCP action');
    $input = json_decode(base64_decode($argv[2] ?? '', true), true, 512, JSON_THROW_ON_ERROR);
    dhcpRequire(($input['version'] ?? null) === 1, 'Unsupported DHCP input');
    $config = \OPNsense\Core\Config::getInstance();
    if (in_array($mode, ['apply','complete'], true)) { $config->lock(); }
    $xml = $config->object();
    $seed = json_decode(file_get_contents('/conf/ansible-install.json'), true, 512, JSON_THROW_ON_ERROR);
    dhcpRequire($seed === json_decode(file_get_contents('/usr/local/share/ansible-opnsense/intent.json'), true, 512, JSON_THROW_ON_ERROR), 'Installed firewall identity differs');
    dhcpRequire($seed['address'] === (string)$xml->interfaces->lan->ipaddr, 'Management identity differs');
    dhcpRequire(preg_match('/^26\.7(?:[._]|$)/', json_decode(file_get_contents('/usr/local/opnsense/version/core'), true)['product_version']) === 1, 'This adapter requires OPNsense 26.7');
    $model = new \OPNsense\Dnsmasq\Dnsmasq();
    $before = $model->getNodeContent();
    $record = dhcpRecord();
    dhcpOwnership($before, $record, $seed['seed_id']);
    if (($record['phase'] ?? '') === 'pending') { dhcpRequire(dhcpIntentHash($input) === dhcpIntentHash($record['input']), 'Finish the pending DHCP target before changing desired state'); }
    dhcpCandidate($model, $input['model']);
    $errors = $model->performValidation(true);
    $messages = [];
    foreach ($errors as $error) { $messages[] = $error->getField().': '.$error->getMessage(); }
    dhcpRequire(count($errors) === 0, 'Vendor DHCP validation failed: '.implode('; ', $messages));
    $candidate = $model->getNodeContent();
    $blockers = [];
    $interface = $xml->interfaces->opt1;
    $device = (string)$interface->if;
    dhcpRequire(preg_match('/^[a-z][a-z0-9]+$/', $device) === 1, 'Invalid HOME device identity');
    $homeInfo = shell_exec('/sbin/ifconfig '.escapeshellarg($device)) ?? '';
    if (!isset($interface->enable) || (string)$interface->ipaddr !== $input['gateway'] || (string)$interface->subnet !== '24' || !str_contains($homeInfo, 'inet '.$input['gateway'].' netmask 0xffffff00')) { $blockers[] = 'HOME saved/runtime address must match the desired gateway /24'; }
    $wan = shell_exec('/sbin/ifconfig '.escapeshellarg((string)$xml->interfaces->wan->if)) ?? '';
    $prefix = substr($input['gateway'], 0, strrpos($input['gateway'], '.') + 1);
    if (preg_match('/inet '.preg_quote($prefix, '/').'[0-9]+\b/', $wan)) { $blockers[] = 'WAN still overlaps the desired HOME subnet'; }
    if ((string)(new \OPNsense\Kea\KeaDhcpv4())->general->enabled === '1' || trim(shell_exec('/usr/bin/pgrep -x kea-dhcp4') ?? '') !== '') { $blockers[] = 'Kea must be disabled and stopped by the separate transition workflow'; }
    foreach ($xml->dhcpd->children() ?? [] as $server) { if (isset($server->enable)) { $blockers[] = 'Legacy DHCP server is enabled'; } }
    if (trim(shell_exec('/usr/bin/pgrep -x dhcpd') ?? '') !== '') { $blockers[] = 'Legacy DHCP daemon is running'; }
    if (!empty(glob('/usr/local/etc/dnsmasq.conf.d/*.conf'))) { $blockers[] = 'Custom Dnsmasq snippets need review'; }
    $dns = is_file('/var/unbound/unbound.conf') ? file_get_contents('/var/unbound/unbound.conf') : '';
    if (!str_contains($dns, 'interface: '.$input['gateway']) || trim(shell_exec('/usr/bin/pgrep -x unbound') ?? '') === '') { $blockers[] = 'Unbound must already serve the desired HOME gateway'; }
    try { dhcpCheckLeases(is_file('/var/db/dnsmasq.leases') ? file('/var/db/dnsmasq.leases', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) : [], $input); }
    catch (RuntimeException $error) { $blockers[] = $error->getMessage(); }
    foreach ([new \OPNsense\Kea\KeaDhcpv6(), new \OPNsense\Kea\KeaDdns(), new \OPNsense\Kea\KeaCtrlAgent()] as $other) {
        if ((string)$other->general->enabled === '1') { $blockers[] = 'Other Kea services require separate review'; }
    }
    $changed = dhcpHash($before) !== dhcpHash($candidate);
    $ready = false;
    if (!$changed && empty($blockers)) {
        try { dhcpRuntime($input, $device); $ready = true; } catch (RuntimeException $error) { $runtimeError = $error->getMessage(); }
    }
    $reload = $changed || !$ready || ($record['phase'] ?? '') !== 'complete';
    $result = ['changed'=>$changed, 'reload_required'=>$reload, 'blockers'=>$blockers,
        'apply_ready'=>empty($blockers), 'runtime_ready'=>$ready, 'owned'=>$record !== null,
        'primary'=>$input['allocation']['primary'], 'reservations'=>$input['allocation']['reservations'],
        'dns'=>'Unbound retained; Dnsmasq DNS port 0', 'dhcpv6_ra'=>false];
    if ($mode !== 'plan') { dhcpRequire(empty($blockers), implode('; ', $blockers)); }
    if ($mode === 'apply' && $reload) {
        if (!is_dir('/conf/ansible-dhcp')) { dhcpRequire(mkdir('/conf/ansible-dhcp', 0700), 'Cannot create DHCP ownership directory'); }
        $backup = '/conf/ansible-dhcp/before-'.bin2hex(random_bytes(8)).'.xml';
        dhcpRequire(copy('/conf/config.xml', $backup) && chmod($backup, 0600), 'Cannot preserve pre-change DHCP configuration');
        dhcpWrite(['version'=>1, 'seed_id'=>$seed['seed_id'], 'phase'=>'pending', 'input'=>$input,
            'previous_sha256'=>dhcpHash($before), 'model_sha256'=>dhcpHash($candidate), 'backup'=>$backup]);
        if ($changed) { $model->serializeToConfig(true); $config->save(['description'=>'Ansible owned HOME DHCP configuration']); }
        $result['changed'] = true;
    } elseif (in_array($mode, ['verify','complete'], true)) {
        dhcpRequire($record !== null && !$changed && $ready, 'DHCP saved/runtime state is not converged: '.($runtimeError ?? 'missing ownership or model drift'));
        dhcpRequire(dhcpIntentHash($input) === dhcpIntentHash($record['input']), 'DHCP declaration differs from ownership record');
        if ($mode === 'complete' && $record['phase'] !== 'complete') { $record['phase'] = 'complete'; dhcpWrite($record); }
        elseif ($mode === 'verify') { dhcpRequire($record['phase'] === 'complete', 'DHCP transaction is incomplete'); }
    }
    $config->unlock();
    echo json_encode($result, JSON_THROW_ON_ERROR)."\n";
} catch (Throwable $error) { fwrite(STDERR, $error->getMessage()."\n"); exit(1); }
