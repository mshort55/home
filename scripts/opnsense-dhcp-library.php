// DHCP ownership and runtime checks shared by configuration and service verification.
function dhcpRequire(bool $condition, string $message): void
{
    if (!$condition) { throw new RuntimeException($message); }
}
function dhcpCanonical(array $value): array
{
    unset($value['dns_port']); // Vendor's volatile effective-port field is not persisted.
    foreach ($value as &$item) { if (is_array($item)) { $item = dhcpCanonical($item); } }
    unset($item);
    ksort($value);
    return $value;
}
function dhcpHash(array $value): string
{
    return hash('sha256', json_encode(dhcpCanonical($value), JSON_THROW_ON_ERROR));
}
function dhcpIntentHash(array $input): string
{
    // Equivalent explicit/default range declarations must converge to one service.
    return dhcpHash(['gateway'=>$input['gateway'], 'subnet'=>$input['subnet'], 'model'=>$input['model']]);
}
function dhcpProtected(string $path, int $mode): void
{
    dhcpRequire(!is_link($path), 'Symlink DHCP ownership artifact');
    if (file_exists($path)) {
        dhcpRequire(fileowner($path) === 0 && (fileperms($path) & 0777) === $mode, 'Unprotected DHCP ownership artifact');
        dhcpRequire($mode === 0700 ? is_dir($path) : is_file($path), 'Wrong DHCP artifact type');
    }
}
function dhcpRecord(): ?array
{
    dhcpProtected('/conf/ansible-dhcp', 0700);
    dhcpProtected('/conf/ansible-dhcp/state.json', 0600);
    return is_file('/conf/ansible-dhcp/state.json') ? json_decode(file_get_contents('/conf/ansible-dhcp/state.json'), true, 512, JSON_THROW_ON_ERROR) : null;
}
function dhcpWrite(array $record): void
{
    $path = '/conf/ansible-dhcp/state.json';
    dhcpProtected($path, 0600);
    $temp = tempnam(dirname($path), '.state-');
    dhcpRequire($temp !== false, 'Cannot allocate DHCP record');
    try {
        chmod($temp, 0600);
        dhcpRequire(file_put_contents($temp, json_encode($record, JSON_THROW_ON_ERROR)) !== false, 'Cannot write DHCP record');
        dhcpRequire(rename($temp, $path), 'Cannot commit DHCP record');
    } finally { if (file_exists($temp)) { unlink($temp); } }
}
function dhcpOwnership(array $current, ?array $record, string $seed): void
{
    if ($record === null) {
        dhcpRequire(($current['enable'] ?? '0') !== '1', 'Enabled Dnsmasq has no ownership record');
        foreach (['hosts','domainoverrides','dhcp_tags','dhcp_ranges','dhcp_options','dhcp_boot'] as $field) {
            dhcpRequire(empty($current[$field]), 'Existing Dnsmasq entries require explicit review');
        }
        return;
    }
    dhcpRequire(($record['version'] ?? null) === 1 && ($record['seed_id'] ?? null) === $seed, 'DHCP ownership identity differs');
    dhcpRequire(in_array($record['phase'] ?? '', ['pending','complete'], true), 'Invalid DHCP transaction phase');
    $allowed = [$record['model_sha256']];
    if ($record['phase'] === 'pending') { $allowed[] = $record['previous_sha256']; }
    dhcpRequire(in_array(dhcpHash($current), $allowed, true), 'Dnsmasq configuration changed outside the owned transaction');
}
function dhcpCandidate($model, array $desired): array
{
    // Ownership was checked first. Rebuild only this role's complete Dnsmasq model.
    $scalars = $desired;
    foreach (['hosts','domainoverrides','dhcp_tags','dhcp_ranges','dhcp_options','dhcp_boot'] as $field) {
        foreach (iterator_to_array($model->$field->iterateItems()) as $id=>$node) { $model->$field->del($id); }
        foreach ($desired[$field] as $id=>$values) { $model->$field->add($id)->setNodes($values); }
        unset($scalars[$field]);
    }
    $model->setNodes($scalars);
    return $model->getNodeContent();
}
function dhcpConfigLines(array $input, string $device): array
{
    $model = $input['model'];
    $result = ['port'=>['0'], 'interface'=>[$device], 'dhcp-range'=>[], 'dhcp-host'=>[], 'dhcp-option'=>[],
        'dhcp-lease-max'=>[$model['dhcp']['lease_max']]];
    foreach ($model['dhcp_ranges'] as $range) {
        $result['dhcp-range'][] = 'tag:'.$device.','.$range['start_addr'].','.$range['end_addr'].','.$range['subnet_mask'].','.$range['lease_time'];
    }
    foreach ($model['hosts'] as $host) {
        $result['dhcp-host'][] = 'id:*,'.$host['hwaddr'].','.$host['ip'].','.$host['host'].','.$host['lease_time'];
    }
    foreach ($model['dhcp_options'] as $option) { $result['dhcp-option'][] = 'tag:'.$device.','.$option['option'].','.$option['value']; }
    // Vendor adds these defaults even when interface-specific DNS options exist.
    $result['dhcp-option'][] = '6,0.0.0.0';
    $result['dhcp-option'][] = 'option6:23,[::]';
    return $result;
}
function dhcpCheckRendered(string $configuration, array $input, string $device): void
{
    $lines = [];
    foreach (explode("\n", $configuration) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') { continue; }
        [$key, $value] = array_pad(explode('=', $line, 2), 2, '');
        $lines[$key][] = $value;
    }
    foreach (dhcpConfigLines($input, $device) as $key=>$expected) {
        $actual = $lines[$key] ?? [];
        sort($expected); sort($actual);
        dhcpRequire($actual === $expected, 'Loaded DHCP configuration differs: '.$key);
    }
    foreach (['enable-ra','enable-tftp','dhcp-boot','dhcp-option-force','dhcp-hostsfile','dhcp-hostsdir','dhcp-optsfile','dhcp-optsdir','dhcp-script','conf-file','dhcp-relay','no-dhcp-interface'] as $key) {
        dhcpRequire(!isset($lines[$key]), 'Unexpected DHCP runtime directive: '.$key);
    }
    dhcpRequire(($lines['conf-dir'] ?? []) === ['/usr/local/etc/dnsmasq.conf.d,*.conf'], 'Unexpected DHCP include directory');
    dhcpRequire(isset($lines['bind-interfaces'], $lines['dhcp-authoritative']), 'Missing DHCP binding/authority policy');
}
function dhcpRuntime(array $input, string $device): void
{
    $info = shell_exec('/sbin/ifconfig '.escapeshellarg($device)) ?? '';
    dhcpRequire(str_contains($info, 'inet '.$input['gateway'].' netmask 0xffffff00'), 'Runtime HOME address differs');
    $dns = is_file('/var/unbound/unbound.conf') ? file_get_contents('/var/unbound/unbound.conf') : '';
    dhcpRequire(str_contains($dns, 'interface: '.$input['gateway']) && trim(shell_exec('/usr/bin/pgrep -x unbound') ?? '') !== '', 'Unbound must serve HOME DNS');
    dhcpRequire(empty(glob('/usr/local/etc/dnsmasq.conf.d/*.conf')), 'Custom Dnsmasq snippets require review');
    dhcpRequire(trim(shell_exec('/usr/bin/pgrep -x kea-dhcp4') ?? '') === '' && trim(shell_exec('/usr/bin/pgrep -x dhcpd') ?? '') === '', 'Another DHCP daemon is running');
    $path = '/usr/local/etc/dnsmasq.conf';
    dhcpRequire(is_file($path), 'Generated DHCP configuration missing');
    dhcpCheckRendered(file_get_contents($path), $input, $device);
    $pids = trim(shell_exec('/usr/bin/pgrep -x dnsmasq') ?? '');
    dhcpRequire(ctype_digit($pids), 'Require exactly one Dnsmasq daemon');
    $command = trim(shell_exec('/bin/ps -ww -p '.escapeshellarg($pids).' -o command=') ?? '');
    dhcpRequire(preg_split('/\s+/', $command) === ['/usr/local/sbin/dnsmasq', '-x', '/var/run/dnsmasq.pid', '-C', $path], 'Dnsmasq uses unexpected command-line overrides');
    $started = strtotime(trim(shell_exec('/bin/ps -p '.escapeshellarg($pids).' -o lstart=') ?? ''));
    dhcpRequire($started !== false && $started >= filemtime($path), 'Dnsmasq must restart after its configuration changes');
    $sockets = shell_exec('/usr/bin/sockstat -4 -l') ?? '';
    dhcpRequire(preg_match('/\bdnsmasq\s+'.$pids.'\s+\S+\s+udp4\s+\S+:67\s/', $sockets) === 1, 'Dnsmasq DHCP socket missing');
    dhcpRequire(preg_match('/\bdnsmasq\s+'.$pids.'\s+\S+\s+\S+\s+\S+:53\s/', $sockets) !== 1, 'Dnsmasq must not serve DNS');
    dhcpCheckLeases(is_file('/var/db/dnsmasq.leases') ? file('/var/db/dnsmasq.leases', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) : [], $input);
}
function dhcpCheckLeases(array $lines, array $input): void
{
    foreach ($lines as $line) {
        $parts = preg_split('/\s+/', trim($line));
        if (count($parts) < 5 || !ctype_digit($parts[0]) || ((int)$parts[0] !== 0 && (int)$parts[0] <= time())) { continue; }
        $address = ip2long($parts[2]); $allowed = false;
        foreach ($input['allocation']['primary']['ranges'] as $range) { $allowed = $allowed || ($address >= ip2long($range['start']) && $address <= ip2long($range['end'])); }
        foreach ($input['allocation']['reservations'] as $reservation) { $allowed = $allowed || ($parts[2] === $reservation['address'] && strtolower($parts[1]) === strtolower($reservation['mac'])); }
        dhcpRequire($allowed, 'Active lease outside the owned dynamic/reserved allocation');
    }
}
function dhcpOwnedHome(array $home): bool
{
    $record = dhcpRecord();
    if ($record === null) { return false; }
    $seed = json_decode(file_get_contents('/conf/ansible-install.json'), true, 512, JSON_THROW_ON_ERROR);
    $model = new \OPNsense\Dnsmasq\Dnsmasq();
    dhcpOwnership($model->getNodeContent(), $record, $seed['seed_id']);
    dhcpRequire($record['phase'] === 'complete', 'Complete the owned DHCP transaction first');
    dhcpRequire($record['input']['gateway'] === $home['address'] && $record['input']['subnet'] === $home['subnet'], 'Owned DHCP HOME allocation differs');
    dhcpRequire((string)(new \OPNsense\Kea\KeaDhcpv4())->general->enabled !== '1', 'Kea must remain disabled with owned Dnsmasq');
    dhcpRequire(trim(shell_exec('/usr/bin/pgrep -x kea-dhcp4') ?? '') === '', 'Kea must remain stopped with owned Dnsmasq');
    return true;
}
