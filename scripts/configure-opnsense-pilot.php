<?php
declare(strict_types=1);

// Execute through pinned SSH. Plan changes only the in-memory vendor models.
require_once('config.inc');

function requireCondition(bool $condition, string $message): void
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

function ipv4(string $address): string
{
    requireCondition(filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false, 'Invalid IPv4 address');
    return $address;
}

function uuid(string $identity): string
{
    $hex = hash('sha256', 'home-opnsense-pilot:' . $identity);
    return substr($hex, 0, 8) . '-' . substr($hex, 8, 4) . '-5' . substr($hex, 13, 3) . '-a' . substr($hex, 17, 3) . '-' . substr($hex, 20, 12);
}

function setValue(SimpleXMLElement $parent, string $key, string $value, array &$changes): void
{
    if (!isset($parent->$key) || (string)$parent->$key !== $value) {
        $parent->$key = $value;
        $changes[] = $key;
    }
}

function removeValue(SimpleXMLElement $parent, string $key, array &$changes): void
{
    if (isset($parent->$key)) {
        unset($parent->$key);
        $changes[] = $key;
    }
}

function privatePath(string $path, bool $directory): void
{
    requireCondition(!is_link($path), 'Refusing a symlink artifact');
    if (file_exists($path)) {
        requireCondition(($directory ? is_dir($path) : is_file($path)) && fileowner($path) === 0, 'Unowned pilot artifact');
        requireCondition((fileperms($path) & 0777) === ($directory ? 0700 : 0600), 'Unprotected pilot artifact');
    }
}

function writePrivate(string $path, array $content): void
{
    privatePath($path, false);
    $temp = tempnam(dirname($path), '.state-');
    requireCondition($temp !== false, 'Cannot allocate private state');
    try {
        chmod($temp, 0600);
        requireCondition(file_put_contents($temp, json_encode($content, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT) . "\n") !== false, 'Cannot write pilot state');
        requireCondition(rename($temp, $path), 'Cannot replace pilot state');
    } finally {
        if (file_exists($temp)) {
            unlink($temp);
        }
    }
}

function collection(\OPNsense\Base\FieldTypes\ArrayField $container, array &$desired, string $label, array &$changes): void
{
    $field = ['filter rules'=>'description', 'DNS access lists'=>'name', 'DNS host records'=>'hostname'][$label];
    $existing = [];
    foreach ($container->iterateItems() as $key => $node) {
        $values = $node->getNodeContent();
        $identity = $values[$field];
        requireCondition(!isset($existing[$identity]), 'Duplicate ' . $label . ' identity');
        $existing[$identity] = ['uuid'=>$key, 'values'=>$values];
    }
    $remapped = [];
    foreach ($desired as $key => $values) {
        $identity = $values[$field];
        if (isset($existing[$identity])) {
            $key = $existing[$identity]['uuid'];
            $before = $existing[$identity]['values'];
            unset($existing[$identity]);
        } else {
            $before = [];
        }
        // Compare only explicitly managed fields; collection defaults may add model fields.
        foreach ($values as $fieldName => $value) {
            if (($before[$fieldName] ?? '') !== $value) {
                $changes[] = $label;
            }
        }
        $remapped[$key] = $values;
    }
    requireCondition(count($existing) === 0, 'Unmanaged ' . $label . ' entry requires separate review');
    $desired = $remapped;
    // Build the candidate in memory for vendor validation; OXL performs the saves.
    foreach ($container->iterateItems() as $key => $node) {
        $container->del($key);
    }
    foreach ($desired as $key => $values) {
        $container->add($key)->setNodes($values);
    }
}

try {
    $mode = $argv[1] ?? '';
    requireCondition(in_array($mode, ['plan', 'apply', 'verify', 'complete', 'network'], true), 'Unknown operation');
    $input = json_decode(base64_decode($argv[2] ?? '', true), true, 512, JSON_THROW_ON_ERROR);
    requireCondition(is_array($input), 'Expected pilot inputs');
    $cnf = \OPNsense\Core\Config::getInstance();
    if ($mode === 'apply') {
        $cnf->lock();
    }
    $xml = $cnf->object();
    $version = json_decode(file_get_contents('/usr/local/opnsense/version/core'), true, 512, JSON_THROW_ON_ERROR);
    requireCondition(preg_match('/^26\.7(?:[._]|$)/', $version['product_version']) === 1, 'This pilot supports OPNsense 26.7');
    $seed = json_decode(file_get_contents('/conf/ansible-install.json'), true, 512, JSON_THROW_ON_ERROR);
    requireCondition($seed === json_decode(file_get_contents('/usr/local/share/ansible-opnsense/intent.json'), true, 512, JSON_THROW_ON_ERROR), 'Installed seed identity conflicts');
    requireCondition(trim(shell_exec("/sbin/mount -p | /usr/bin/awk '$2 == \"/\" {print $3}'")) === 'zfs', 'Pilot requires the installed ZFS disk');
    requireCondition($seed['address'] === $input['management_address'], 'Management address conflicts with installation');
    requireCondition($seed['networks'] == $input['networks'], 'Pilot NIC allocation conflicts');
    $address = ipv4($input['management_address']);
    $subnet = substr($address, 0, strrpos($address, '.') + 1);
    $cidr = $subnet . '0/24';
    $wanGateway = ipv4($input['wan_gateway']);
    requireCondition(str_starts_with($wanGateway, '10.') && !str_starts_with($wanGateway, $subnet), 'Pilot gateway must use a distinct private 10/8 subnet');
    $admins = $input['admin_addresses'];
    $updates = $input['update_addresses'];
    requireCondition(count($admins) >= 1 && count($updates) >= 1, 'Name the administrator and update hosts');
    foreach (array_merge($admins, $updates) as $host) {
        requireCondition(str_starts_with(ipv4($host), $subnet) && !in_array($host, [$subnet . '0', $subnet . '255', $address], true), 'Hosts must be ordinary addresses on management /24');
    }
    $ssh = explode(' ', getenv('SSH_CONNECTION') ?: '');
    requireCondition(in_array($ssh[0], $admins, true), 'Current SSH controller is absent from the explicit admin addresses');
    requireCondition(count($input['dns_servers']) === 2 && count(array_unique($input['dns_servers'])) === 2, 'Specify two distinct pinned DNS resolvers');
    foreach ($input['dns_servers'] as $server) {
        ipv4($server);
        requireCondition(!str_starts_with($server, $subnet), 'Upstream DNS must not point back to management');
    }
    requireCondition(count($input['ntp_servers']) >= 1, 'Specify upstream NTP servers');
    foreach ($input['ntp_servers'] as $server) {
        requireCondition(preg_match('/^[a-z0-9][a-z0-9.-]+[a-z0-9]$/i', $server) === 1, 'Invalid NTP server');
    }
    foreach ($seed['networks'] as $nic) {
        $iface = $xml->interfaces->{$nic['section']};
        $name = (string)$iface->if;
        requireCondition(preg_match('/^vtnet[0-9]+$/', $name) === 1, 'Unexpected NIC name');
        $info = shell_exec('/sbin/ifconfig ' . escapeshellarg($name));
        requireCondition(preg_match('/ether\s+([0-9a-f:]+)/i', $info, $matches) === 1 && strtolower($matches[1]) === $nic['mac'], 'Live NIC MAC-to-role mapping conflicts');
        if (in_array($nic['section'], ['opt1', 'opt2', 'opt3'], true)) {
            requireCondition(!isset($iface->enable), 'Optional interfaces must remain disabled in this management pilot');
        }
    }
    requireCondition((string)$xml->interfaces->lan->ipaddr === $address && (string)$xml->interfaces->lan->subnet === '24', 'Management SVI conflicts');
    requireCondition((string)$xml->interfaces->wan->ipaddr === 'dhcp' && isset($xml->interfaces->wan->enable), 'Pilot WAN must use DHCP');
    requireCondition(!isset($xml->system->ipv6allow), 'IPv6 forwarding must stay disabled');
    requireCondition(isset($xml->system->ssh->enabled) && !isset($xml->system->ssh->passwordauth) && (string)$xml->system->ssh->interfaces === 'lan', 'Preserve key-only management SSH');
    requireCondition(!isset($xml->filter->rule) && !isset($xml->nat->rule) && !isset($xml->nat->onetoone), 'Legacy firewall or port-forward entries require separate review');
    requireCondition(!isset($xml->dnsmasq->enable) || (string)$xml->dnsmasq->enable !== '1', 'DHCP/Dnsmasq must stay disabled');

    $directory = '/conf/ansible-pilot';
    $statePath = $directory . '/state.json';
    privatePath($directory, true);
    privatePath($statePath, false);
    $state = file_exists($statePath) ? json_decode(file_get_contents($statePath), true, 512, JSON_THROW_ON_ERROR) : [];
    requireCondition(empty($state) || $state['seed_id'] === $seed['seed_id'], 'Pilot record belongs to another seed');
    if (!empty($state)) {
        requireCondition(in_array($state['phase'], ['pending', 'complete'], true), 'Unknown pilot record phase');
        requireCondition(str_starts_with($state['backup'], $directory . '/before-') && dirname($state['backup']) === $directory && file_exists($state['backup']), 'Missing original pilot backup');
        privatePath($state['backup'], false);
    }
    $digest = hash('sha256', json_encode($input, JSON_THROW_ON_ERROR));
    $changes = [];
    setValue($xml->system->webgui, 'noantilockout', '1', $changes);
    removeValue($xml->system, 'dnsallowoverride', $changes);
    removeValue($xml->system, 'dnslocalhost', $changes);
    $oldDns = [];
    foreach ($xml->system->dnsserver as $server) {
        $oldDns[] = (string)$server;
    }
    if ($oldDns !== $input['dns_servers']) {
        unset($xml->system->dnsserver);
        foreach ($input['dns_servers'] as $server) {
            $xml->system->addChild('dnsserver', $server);
        }
        $changes[] = 'system DNS';
    }
    setValue($xml->system, 'timeservers', implode(' ', $input['ntp_servers']), $changes);
    if (!isset($xml->ntpd)) {
        $xml->addChild('ntpd');
    }
    // WAN is needed for upstream NTP replies; filter rules expose NTP only on MGMT.
    setValue($xml->ntpd, 'interface', 'lan,wan', $changes);
    setValue($xml->ntpd, 'iburst', implode(' ', $input['ntp_servers']), $changes);
    setValue($xml->ntpd, 'ispool', implode(' ', $input['ntp_servers']), $changes);
    removeValue($xml->ntpd, 'clientmode', $changes);
    setValue($xml->nat->outbound, 'mode', 'automatic', $changes);
    removeValue($xml->interfaces->wan, 'blockpriv', $changes);
    removeValue($xml->interfaces->wan, 'blockbogons', $changes);

    $legacyChanges = $changes;
    // These two settings have no equivalent in the pinned OXL modules.
    $nativeUnbound = new \OPNsense\Unbound\Unbound();
    $beforeNative = $nativeUnbound->getNodeContent();
    $nativeUnbound->setNodes(['forwarding'=>['enabled'=>'1'], 'acls'=>['default_action'=>'refuse']]);
    if ($beforeNative !== $nativeUnbound->getNodeContent()) {
        $changes[] = 'Unbound forwarding/default ACL';
        $legacyChanges[] = 'Unbound forwarding/default ACL';
    }
    $filter = new \OPNsense\Firewall\Filter();
    $bootstrapRule = null;
    foreach (['snatrules', 'npt', 'onetoone'] as $section) {
        requireCondition(iterator_count($filter->$section->rule->iterateItems()) === 0, 'Unexpected NAT rule requires review');
    }
    foreach ($filter->rules->rule->iterateItems() as $key => $rule) {
        if ((string)$rule->description === 'Bootstrap MGMT to firewall') {
            requireCondition((string)$rule->interface === 'lan' && (string)$rule->source_net === 'lan' && (string)$rule->destination_net === '(self)' && (string)$rule->action === 'pass' && (string)$rule->ipprotocol === 'inet', 'Bootstrap rule conflicts');
            $bootstrapRule = $key;
            $filter->rules->rule->del($key);
            $changes[] = 'bootstrap filter rule';
        }
    }
    $rules = [];
    $sequence = 10;
    $addRule = function (string $name, string $source, string $destination, string $protocol, string $port = '', string $action = 'pass', string $interface = 'lan') use (&$rules, &$sequence): void {
        $rules[uuid($name)] = ['enabled'=>'1', 'sequence'=>(string)$sequence, 'action'=>$action, 'quick'=>'1', 'interface'=>$interface, 'direction'=>'in', 'ipprotocol'=>'inet', 'protocol'=>$protocol, 'source_net'=>$source, 'destination_net'=>$destination, 'destination_port'=>$port, 'log'=>$action === 'block' ? '1' : '0', 'description'=>'Home automation: ' . $name];
        $sequence += 10;
    };
    foreach ($admins as $host) {
        foreach (['22', '443'] as $port) {
            $addRule('admin ' . $host . ':' . $port, $host . '/32', '(self)', 'TCP', $port);
        }
        $addRule('admin ICMP ' . $host, $host . '/32', '(self)', 'ICMP');
    }
    foreach (['TCP', 'UDP'] as $protocol) {
        $addRule('MGMT DNS ' . $protocol, $cidr, '(self)', $protocol, '53');
    }
    $addRule('MGMT NTP', $cidr, '(self)', 'UDP', '123');
    foreach (['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '100.64.0.0/10'] as $private) {
        $addRule('MGMT private deny ' . $private, $cidr, $private, 'any', '', 'block');
    }
    foreach ($updates as $host) {
        foreach (['80', '443'] as $port) {
            $addRule('updates ' . $host . ':' . $port, $host . '/32', 'any', 'TCP', $port);
        }
    }
    $addRule('MGMT default deny', $cidr, 'any', 'any', '', 'block');
    $addRule('WAN default deny', 'any', 'any', 'any', '', 'block', 'wan');
    collection($filter->rules->rule, $rules, 'filter rules', $changes);

    $unbound = new \OPNsense\Unbound\Unbound();
    $before = $unbound->getNodeContent();
    $unbound->setNodes(['general'=>['enabled'=>'1', 'port'=>'53', 'active_interface'=>'lan', 'outgoing_interface'=>'wan', 'regdhcp'=>'0', 'regdhcpstatic'=>'0', 'noreglladdr6'=>'1', 'noregrecords'=>'1'], 'forwarding'=>['enabled'=>'1'], 'acls'=>['default_action'=>'refuse']]);
    if ($before !== $unbound->getNodeContent()) {
        $changes[] = 'Unbound settings';
    }
    $acls = [uuid('acl MGMT')=>['enabled'=>'1', 'name'=>'MGMT', 'action'=>'allow', 'networks'=>$cidr], uuid('acl loopback')=>['enabled'=>'1', 'name'=>'loopback', 'action'=>'allow', 'networks'=>'127.0.0.0/8,::1/128']];
    collection($unbound->acls->acl, $acls, 'DNS access lists', $changes);
    requireCondition(iterator_count($unbound->dots->dot->iterateItems()) === 0 && iterator_count($unbound->dnsbl->blocklist->iterateItems()) === 0 && iterator_count($unbound->aliases->alias->iterateItems()) === 0, 'Extra DNS forwarding, aliases or blocklist entries require review');
    $hosts = [];
    foreach ($input['dns_hosts'] as $host) {
        requireCondition(preg_match('/^[a-z0-9][a-z0-9-]*$/i', $host['hostname']) === 1, 'Invalid local host name');
        ipv4($host['address']);
        $hosts[uuid('host ' . $host['hostname'])] = ['enabled'=>'1', 'hostname'=>$host['hostname'], 'domain'=>(string)$xml->system->domain, 'rr'=>'A', 'server'=>$host['address']];
    }
    collection($unbound->hosts->host, $hosts, 'DNS host records', $changes);
    foreach ([$filter, $unbound] as $model) {
        $errors = $model->performValidation(true);
        if (count($errors) > 0) {
            $messages = [];
            foreach ($errors as $error) {
                $messages[] = $error->getField() . ': ' . $error->getMessage();
            }
            throw new RuntimeException('Vendor model validation failed: ' . implode('; ', $messages));
        }
    }
    $loadedRules = shell_exec('/sbin/pfctl -sr') ?? '';
    $runtimeReady = trim(shell_exec('/usr/bin/pgrep -x ntpd') ?? '') !== '' && trim(shell_exec('/usr/bin/pgrep -x unbound') ?? '') !== '';
    foreach (array_keys($rules) as $key) {
        $runtimeReady = $runtimeReady && str_contains($loadedRules, $key);
    }
    $loadedDns = is_file('/var/unbound/unbound.conf') ? file_get_contents('/var/unbound/unbound.conf') : '';
    foreach ($input['dns_servers'] as $server) {
        $runtimeReady = $runtimeReady && str_contains($loadedDns, 'forward-addr: ' . $server);
    }
    $runtimeReady = $runtimeReady && str_contains($loadedDns, 'interface: ' . $address) && !str_contains($loadedDns, 'forward-first: yes');
    $reload = ($argv[3] ?? '') === 'api-change' || count($changes) > 0 || !$runtimeReady || ($state['phase'] ?? '') !== 'complete' || ($state['digest'] ?? '') !== $digest;
    $result = ['rules'=>$rules, 'acls'=>array_values($acls), 'hosts'=>array_values($hosts), 'domain'=>(string)$xml->system->domain, 'bootstrap_rule'=>$bootstrapRule, 'changed'=>count($changes) > 0, 'reload_required'=>$reload, 'changes'=>array_values(array_unique($changes)), 'management'=>$address, 'rule_count'=>count($rules), 'seed_id'=>$seed['seed_id']];

    if (in_array($mode, ['verify', 'complete', 'network'], true)) {
        requireCondition(count($changes) === 0, 'Saved pilot configuration has drifted');
        $runtimeRules = shell_exec('/sbin/pfctl -sr');
        foreach (array_keys($rules) as $key) {
            requireCondition(str_contains($runtimeRules, $key), 'Missing loaded firewall rule ' . $key);
        }
        requireCondition(!str_contains($runtimeRules, 'anti-lockout') && !str_contains($runtimeRules, 'Bootstrap MGMT'), 'Broad bootstrap administration rule remains loaded');
        require_once('filter.lib.inc');
        requireCondition(filter_core_get_antilockout() === [], 'Automatic broad management access remains configured');
        $runtimeDns = file_get_contents('/var/unbound/unbound.conf');
        foreach ($input['dns_servers'] as $server) {
            requireCondition(str_contains($runtimeDns, 'forward-addr: ' . $server), 'Missing pinned DNS forwarder');
        }
        requireCondition(!str_contains($runtimeDns, 'forward-first: yes'), 'Recursive DNS fallback is forbidden');
        requireCondition(str_contains($runtimeDns, 'interface: ' . $address), 'Missing MGMT DNS listener');
        requireCondition(trim(shell_exec('/usr/bin/pgrep -x ntpd')) !== '', 'NTP service is not running');
        foreach ($input['dns_hosts'] as $host) {
            $answer = shell_exec('/usr/local/bin/drill -Q @' . escapeshellarg($address) . ' ' . escapeshellarg($host['hostname'] . '.' . (string)$xml->system->domain) . ' A');
            requireCondition(trim($answer ?? '') === $host['address'], 'Local DNS host verification failed');
        }
        if ($mode === 'network') {
            $wan = shell_exec('/sbin/ifconfig ' . escapeshellarg((string)$xml->interfaces->wan->if));
            requireCondition(preg_match('/inet ([0-9.]+) netmask 0xffffff00/', $wan, $match) === 1, 'WAN DHCP /24 is not ready');
            $prefix = substr(ipv4($input['wan_gateway']), 0, strrpos($input['wan_gateway'], '.') + 1);
            requireCondition(str_starts_with($match[1], $prefix) && $match[1] !== $input['wan_gateway'], 'WAN is not on the intended Fortinet pilot subnet');
            $route = shell_exec('/sbin/route -n get default');
            requireCondition(preg_match('/gateway:\s+([0-9.]+)/', $route, $gateway) === 1 && $gateway[1] === $input['wan_gateway'], 'Default route does not use the intended pilot gateway');
            $result['wan_address'] = $match[1];
            $result['ntp_synchronized'] = preg_match('/^\*\S+/m', shell_exec('/usr/local/sbin/ntpq -pn') ?? '') === 1;
        }
        if ($mode === 'complete') {
            requireCondition(isset($state['backup']), 'Missing pre-change backup record');
            $state['digest'] = $digest;
            $state['phase'] = 'complete';
            if ($reload) {
                writePrivate($statePath, $state);
            }
        }
    } elseif ($mode === 'apply' && $reload) {
        if (!file_exists($directory)) {
            requireCondition(mkdir($directory, 0700), 'Cannot create private pilot record directory');
        }
        if (($state['phase'] ?? '') === 'pending' && ($state['digest'] ?? '') === $digest) {
            $backup = $state['backup'];
        } else {
            $backup = $directory . '/before-' . gmdate('Ymd\THis\Z') . '-' . bin2hex(random_bytes(4)) . '.xml';
            $handle = fopen($backup, 'x');
            requireCondition($handle !== false, 'Cannot create pre-change backup');
            chmod($backup, 0600);
            fwrite($handle, file_get_contents('/conf/config.xml'));
            fclose($handle);
        }
        writePrivate($statePath, ['seed_id'=>$seed['seed_id'], 'digest'=>$digest, 'phase'=>'pending', 'backup'=>$backup]);
        if (count($legacyChanges) > 0) {
            $nativeUnbound->serializeToConfig(true);
            $cnf->save(['description'=>'Ansible management pilot configuration']);
        }
        $result['backup'] = $backup;
        $result['changed'] = true;
    }
    $cnf->unlock();
    echo json_encode($result, JSON_THROW_ON_ERROR) . "\n";
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . "\n");
    exit(1);
}
