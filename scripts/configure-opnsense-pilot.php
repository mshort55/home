<?php
declare(strict_types=1);

// Execute through pinned SSH. Plan changes only the in-memory vendor models.
require_once('config.inc');
// LAB_EXTENSION_LIBRARY

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
    $field = ['filter rules'=>'description', 'DNS access lists'=>'name', 'DNS host records'=>'hostname', 'DHCP subnets'=>'description'][$label];
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
            $previous = $before[$fieldName] ?? '';
            if (is_array($value) && is_array($previous)) {
                $previous = array_intersect_key($previous, $value);
            }
            if ($previous !== $value) {
                $changes[] = $label;
            }
        }
        $remapped[$key] = $values;
    }
    // A separate, protected workflow owns WireGuard rules and its DNS ACL.
    // Preserve only the UUIDs and exact fields recorded by that workflow.
    $retained = [];
    foreach (['/conf/ansible-wireguard/state.json', '/conf/ansible-wireguard-wifi/state.json', '/conf/ansible-lab/dev.json', '/conf/ansible-lab/bmc.json'] as $wireguardRecord) {
      if (is_file($wireguardRecord)) {
        privatePath(dirname($wireguardRecord), true);
        privatePath($wireguardRecord, false);
        $wireguard = json_decode(file_get_contents($wireguardRecord), true, 512, JSON_THROW_ON_ERROR);
        global $seed;
        $wifiRecord = str_contains($wireguardRecord, 'wireguard-wifi');
        requireCondition(($wireguard['version'] ?? null) === 1 && $wireguard['seed_id'] === $seed['seed_id'] && in_array($wireguard['phase'], $wifiRecord ? ['complete','absent'] : ['complete'], true), 'Complete or remove the owned WireGuard/Wi-Fi workflow first');
        if ($wifiRecord && $wireguard['phase'] === 'complete') {
            $wan = shell_exec('/sbin/ifconfig '.escapeshellarg((string)\OPNsense\Core\Config::getInstance()->object()->interfaces->wan->if)) ?? '';
            $route = shell_exec('/sbin/route -n get default') ?? '';
            requireCondition(preg_match('/\binet '.preg_quote($wireguard['input']['wifi']['wan_address'], '/').' netmask 0xffffff00\b/', $wan) === 1 && preg_match('/gateway:\s+'.preg_quote($wireguard['input']['wifi']['wan_gateway'], '/').'\b/', $route) === 1, 'Remove the Wi-Fi exception before changing the private WAN');
        }
        $owned = $wifiRecord ? ($label === 'filter rules' && $wireguard['phase'] === 'complete' ? [$wireguard['object']] : []) : ($wireguard['objects'][$label] ?? []);
        foreach ($owned as $object) {
            $identity = $object['values'][$field];
            requireCondition(isset($existing[$identity]) && $existing[$identity]['uuid'] === $object['uuid'], 'Missing or replaced owned WireGuard ' . $label);
            foreach ($object['values'] as $name => $value) {
                requireCondition(($existing[$identity]['values'][$name] ?? '') === $value, 'Owned WireGuard policy drift; run its WireGuard or private Wi-Fi configuration workflow');
            }
            $retained[$object['uuid']] = $existing[$identity]['values'];
            unset($existing[$identity]);
        }
      }
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
    foreach ($retained as $key => $values) {
        $container->add($key)->setNodes($values);
    }
}

function homeSettings(array $home, string $managementPrefix, string $wanGateway): array
{
    $keys = array_keys($home);
    sort($keys);
    requireCondition($keys === ['address', 'lease_seconds', 'pool_end', 'pool_start', 'subnet'], 'Unexpected HOME settings');
    $address = ipv4($home['address']);
    $prefix = substr($address, 0, strrpos($address, '.') + 1);
    $wanPrefix = substr($wanGateway, 0, strrpos($wanGateway, '.') + 1);
    requireCondition(str_starts_with($address, '10.') && $prefix !== $managementPrefix && $prefix !== $wanPrefix,
        'HOME must use a private /24 distinct from MGMT and pilot WAN');
    requireCondition($home['subnet'] === $prefix . '0/24', 'HOME subnet must match its /24 gateway');
    foreach ([$address, $home['pool_start'], $home['pool_end']] as $host) {
        requireCondition(str_starts_with(ipv4($host), $prefix) && !in_array($host, [$prefix . '0', $prefix . '255'], true), 'Invalid HOME host address');
    }
    requireCondition(ip2long($home['pool_start']) <= ip2long($home['pool_end']) &&
        (ip2long($address) < ip2long($home['pool_start']) || ip2long($address) > ip2long($home['pool_end'])), 'Invalid DHCP pool or gateway inside pool');
    requireCondition(is_int($home['lease_seconds']) && $home['lease_seconds'] >= 600 && $home['lease_seconds'] <= 86400, 'Invalid lease lifetime');
    return ['address'=>$address, 'subnet'=>$home['subnet'], 'pool_start'=>$home['pool_start'], 'pool_end'=>$home['pool_end'], 'lease_seconds'=>$home['lease_seconds']];
}

function homeRuntime(array $home, string $device): bool
{
    $info = shell_exec('/sbin/ifconfig ' . escapeshellarg($device)) ?? '';
    $dns = is_file('/var/unbound/unbound.conf') ? file_get_contents('/var/unbound/unbound.conf') : '';
    if (!str_contains($info, 'inet ' . $home['address'] . ' netmask 0xffffff00') ||
        !str_contains($dns, 'interface: ' . $home['address']) ||
        trim(shell_exec('/usr/bin/pgrep -x kea-dhcp4') ?? '') === '' || !is_file('/usr/local/etc/kea/kea-dhcp4.conf')) {
        return false;
    }
    $configuration = json_decode(file_get_contents('/usr/local/etc/kea/kea-dhcp4.conf'), true, 512, JSON_THROW_ON_ERROR)['Dhcp4'];
    $subnets = $configuration['subnet4'] ?? [];
    if (($configuration['interfaces-config']['interfaces'] ?? []) !== [$device] || count($subnets) !== 1 ||
        $subnets[0]['subnet'] !== $home['subnet'] || ($configuration['valid-lifetime'] ?? null) !== $home['lease_seconds'] ||
        count($subnets[0]['pools'] ?? []) !== 1 || preg_replace('/\s+/', '', $subnets[0]['pools'][0]['pool']) !== $home['pool_start'] . '-' . $home['pool_end']) {
        return false;
    }
    $options = array_column($subnets[0]['option-data'] ?? [], 'data', 'name');
    if (($options['routers'] ?? '') !== $home['address'] || ($options['domain-name-servers'] ?? '') !== $home['address'] ||
        ($options['ntp-servers'] ?? '') !== $home['address']) {
        return false;
    }
    $nat = shell_exec('/sbin/pfctl -sn') ?? '';
    // OPNsense emits dynamic interface networks in automatic outbound NAT.
    $source = '(?:' . preg_quote($home['subnet'], '/') . '|\(' . preg_quote($device, '/') . ':network\))';
    return preg_match('/^nat on \S+ inet from ' . $source . ' to any -> /m', $nat) === 1;
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
    $wireguardSource = null;
    if (is_file('/conf/ansible-wireguard/state.json')) {
        privatePath('/conf/ansible-wireguard', true);
        privatePath('/conf/ansible-wireguard/state.json', false);
        $wireguardIdentity = json_decode(file_get_contents('/conf/ansible-wireguard/state.json'), true, 512, JSON_THROW_ON_ERROR);
        requireCondition(($wireguardIdentity['version'] ?? null) === 1 && $wireguardIdentity['seed_id'] === $seed['seed_id'] && $wireguardIdentity['phase'] === 'complete', 'Complete or reconcile the owned WireGuard workflow first');
        $wireguardSource = $wireguardIdentity['input']['settings']['peer_address'];
    }
    requireCondition(in_array($ssh[0], $admins, true) || ($wireguardSource !== null && $ssh[0] === $wireguardSource), 'Current SSH controller is absent from the explicit wired or enrolled WireGuard administrator addresses');
    requireCondition(count($input['dns_servers']) === 2 && count(array_unique($input['dns_servers'])) === 2, 'Specify two distinct pinned DNS resolvers');
    foreach ($input['dns_servers'] as $server) {
        ipv4($server);
        requireCondition(!str_starts_with($server, $subnet), 'Upstream DNS must not point back to management');
    }
    requireCondition(count($input['ntp_servers']) >= 1, 'Specify upstream NTP servers');
    foreach ($input['ntp_servers'] as $server) {
        requireCondition(preg_match('/^[a-z0-9][a-z0-9.-]+[a-z0-9]$/i', $server) === 1, 'Invalid NTP server');
    }
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
    $home = $input['home_pilot'] ?? $state['home_pilot'] ?? null;
    if ($home !== null) {
        requireCondition(is_array($home), 'Invalid HOME settings');
        $home = homeSettings($home, $subnet, $wanGateway);
        requireCondition(!isset($state['home_pilot']) || $state['home_pilot'] == $home, 'Changing an existing HOME allocation requires a separate migration');
        requireCondition(isset($state['home_pilot']) || ($state['phase'] ?? '') === 'complete', 'Complete the management pilot before enabling HOME');
        $input['home_pilot'] = $home;
    }
    $labRecords=labRecords($xml,$seed);
    foreach ($seed['networks'] as $nic) {
        $iface = $xml->interfaces->{$nic['section']};
        $name = (string)$iface->if;
        requireCondition(preg_match('/^vtnet[0-9]+$/', $name) === 1, 'Unexpected NIC name');
        $info = shell_exec('/sbin/ifconfig ' . escapeshellarg($name));
        requireCondition(preg_match('/ether\s+([0-9a-f:]+)/i', $info, $matches) === 1 && strtolower($matches[1]) === $nic['mac'], 'Live NIC MAC-to-role mapping conflicts');
        if ($nic['section'] === 'opt1' && $home !== null) {
            requireCondition(!isset($iface->enable) || (isset($state['home_pilot']) && (string)$iface->ipaddr === $home['address'] && (string)$iface->subnet === '24'), 'Unowned or conflicting enabled HOME interface');
            requireCondition(!isset($iface->gateway) && !isset($iface->bridge) && !isset($iface->blockpriv) && !isset($iface->blockbogons), 'Unexpected HOME interface services');
        } elseif (in_array($nic['section'], ['opt1', 'opt2', 'opt3'], true)) {
            requireCondition(!isset($iface->enable) || in_array($nic['section'], labListeners($labRecords), true), 'Optional interfaces require a completed owned lab workflow');
        }
    }
    requireCondition((string)$xml->interfaces->lan->ipaddr === $address && (string)$xml->interfaces->lan->subnet === '24', 'Management SVI conflicts');
    requireCondition((string)$xml->interfaces->wan->ipaddr === 'dhcp' && isset($xml->interfaces->wan->enable), 'Pilot WAN must use DHCP');
    requireCondition(!isset($xml->system->ipv6allow), 'IPv6 forwarding must stay disabled');
    requireCondition(isset($xml->system->ssh->enabled) && !isset($xml->system->ssh->passwordauth) && (string)$xml->system->ssh->interfaces === 'lan', 'Preserve key-only management SSH');
    requireCondition(!isset($xml->filter->rule) && !isset($xml->nat->rule) && !isset($xml->nat->onetoone), 'Legacy firewall or port-forward entries require separate review');
    requireCondition(!isset($xml->dnsmasq->enable) || (string)$xml->dnsmasq->enable !== '1', 'DHCP/Dnsmasq must stay disabled');

    $digest = hash('sha256', json_encode($input, JSON_THROW_ON_ERROR));
    $changes = [];
    $homeInterfaceReload = false;
    if ($home !== null) {
        setValue($xml->interfaces->opt1, 'enable', '1', $changes);
        setValue($xml->interfaces->opt1, 'ipaddr', $home['address'], $changes);
        setValue($xml->interfaces->opt1, 'subnet', '24', $changes);
        setValue($xml->interfaces->opt1, 'ipaddrv6', 'none', $changes);
        $homeDevice = (string)$xml->interfaces->opt1->if;
        $homeInfo = shell_exec('/sbin/ifconfig ' . escapeshellarg($homeDevice)) ?? '';
        $homeInterfaceReload = !str_contains($homeInfo, 'inet ' . $home['address'] . ' netmask 0xffffff00');
    }
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
    setValue($xml->ntpd, 'interface', implode(',', array_merge($home === null ? ['lan','wan'] : ['lan','wan','opt1'], labListeners($labRecords))), $changes);
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
    if ($home !== null) {
        $sequence = 300;
        foreach (['TCP', 'UDP'] as $protocol) {
            $addRule('HOME DNS ' . $protocol, $home['subnet'], $home['address'] . '/32', $protocol, '53', 'pass', 'opt1');
        }
        $addRule('HOME NTP', $home['subnet'], $home['address'] . '/32', 'UDP', '123', 'pass', 'opt1');
        $addRule('HOME gateway ICMP', $home['subnet'], $home['address'] . '/32', 'ICMP', '', 'pass', 'opt1');
        $addRule('HOME firewall deny', 'any', '(self)', 'any', '', 'block', 'opt1');
        foreach (['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '100.64.0.0/10'] as $private) {
            $addRule('HOME private deny ' . $private, 'any', $private, 'any', '', 'block', 'opt1');
        }
        foreach (['TCP', 'UDP'] as $protocol) {
            $addRule('HOME external DNS deny ' . $protocol, 'any', 'any', $protocol, '53', 'block', 'opt1');
        }
        $addRule('HOME internet', $home['subnet'], 'any', 'any', '', 'pass', 'opt1');
        $addRule('HOME default deny', 'any', 'any', 'any', '', 'block', 'opt1');
    }
    collection($filter->rules->rule, $rules, 'filter rules', $changes);

    $unbound = new \OPNsense\Unbound\Unbound();
    $before = $unbound->getNodeContent();
    $dnsInterfaces = array_merge($home === null ? ['lan'] : ['lan', 'opt1'], labListeners($labRecords));
    $unbound->setNodes(['general'=>['enabled'=>'1', 'port'=>'53', 'active_interface'=>implode(',', $dnsInterfaces), 'outgoing_interface'=>'wan', 'regdhcp'=>'0', 'regdhcpstatic'=>'0', 'noreglladdr6'=>'1', 'noregrecords'=>'1'], 'forwarding'=>['enabled'=>'1'], 'acls'=>['default_action'=>'refuse']]);
    if ($before !== $unbound->getNodeContent()) {
        $changes[] = 'Unbound settings';
    }
    $acls = [uuid('acl MGMT')=>['enabled'=>'1', 'name'=>'MGMT', 'action'=>'allow', 'networks'=>$cidr], uuid('acl loopback')=>['enabled'=>'1', 'name'=>'loopback', 'action'=>'allow', 'networks'=>'127.0.0.0/8,::1/128']];
    if ($home !== null) {
        $acls[uuid('acl HOME')] = ['enabled'=>'1', 'name'=>'HOME', 'action'=>'allow', 'networks'=>$home['subnet']];
    }
    collection($unbound->acls->acl, $acls, 'DNS access lists', $changes);
    requireCondition(iterator_count($unbound->dots->dot->iterateItems()) === 0 && iterator_count($unbound->dnsbl->blocklist->iterateItems()) === 0 && iterator_count($unbound->aliases->alias->iterateItems()) === 0, 'Extra DNS forwarding, aliases or blocklist entries require review');
    $hosts = [];
    foreach ($input['dns_hosts'] as $host) {
        requireCondition(preg_match('/^[a-z0-9][a-z0-9-]*$/i', $host['hostname']) === 1, 'Invalid local host name');
        ipv4($host['address']);
        $hosts[uuid('host ' . $host['hostname'])] = ['enabled'=>'1', 'hostname'=>$host['hostname'], 'domain'=>(string)$xml->system->domain, 'rr'=>'A', 'server'=>$host['address']];
    }
    collection($unbound->hosts->host, $hosts, 'DNS host records', $changes);
    $models = [$filter, $unbound];
    $dhcpSubnet = null;
    $dhcpReady = false;
    if ($home !== null) {
        if (isset($xml->dhcpd)) {
            foreach ($xml->dhcpd->children() as $dhcp) {
                requireCondition(!isset($dhcp->enable), 'Legacy DHCP server must remain disabled');
            }
        }
        $dnsmasq = new \OPNsense\Dnsmasq\Dnsmasq();
        requireCondition((string)$dnsmasq->general->enabled !== '1', 'Dnsmasq must remain disabled');
        foreach ([new \OPNsense\Kea\KeaDhcpv6(), new \OPNsense\Kea\KeaDdns(), new \OPNsense\Kea\KeaCtrlAgent()] as $other) {
            requireCondition((string)$other->general->enabled !== '1', 'Unrelated Kea services must remain disabled');
        }
        $kea = new \OPNsense\Kea\KeaDhcpv4();
        requireCondition((string)$kea->general->manual_config !== '1' && (string)$kea->ha->enabled !== '1', 'Manual or HA DHCP requires separate review');
        requireCondition((string)$kea->general->enabled !== '1' || (isset($state['home_pilot']) && (string)$kea->general->interfaces === 'opt1'), 'Unowned DHCP service requires separate review');
        foreach (['reservations'=>'reservation', 'options'=>'option', 'ha_peers'=>'peer'] as $section=>$field) {
            requireCondition(iterator_count($kea->$section->$field->iterateItems()) === 0, 'Extra DHCP reservations, options or peers require separate review');
        }
        $before = $kea->getNodeContent();
        $kea->setNodes(['general'=>['enabled'=>'1', 'interfaces'=>'opt1', 'dhcp_socket_type'=>'raw', 'fwrules'=>'1', 'valid_lifetime'=>(string)$home['lease_seconds']]]);
        if ($before !== $kea->getNodeContent()) {
            $changes[] = 'Kea settings';
        }
        $dhcpSubnet = ['subnet'=>$home['subnet'], 'description'=>'Home automation: HOME pilot',
            'pools'=>$home['pool_start'] . ' - ' . $home['pool_end'], 'option_data_autocollect'=>'0', 'next_server'=>'',
            'option_data'=>['domain_name_servers'=>$home['address'], 'domain_search'=>(string)$xml->system->domain,
                'routers'=>$home['address'], 'static_routes'=>'', 'domain_name'=>(string)$xml->system->domain,
                'ntp_servers'=>$home['address'], 'time_servers'=>'', 'tftp_server_name'=>'', 'boot_file_name'=>'', 'v6_only_preferred'=>'']];
        foreach ($kea->subnets->subnet4->iterateItems() as $node) {
            $values = $node->getNodeContent();
            foreach (['valid_lifetime', 'allocator', 'option', 'ddns_forward_zone', 'ddns_dns_server'] as $key) {
                requireCondition(($values[$key] ?? '') === '', 'Unexpected DHCP subnet customization requires separate review');
            }
        }
        $dhcpSubnets = [uuid('subnet HOME')=>$dhcpSubnet];
        collection($kea->subnets->subnet4, $dhcpSubnets, 'DHCP subnets', $changes);
        $models[] = $kea;
        $auth = new \OPNsense\Auth\User();
        $user = $auth->getUserByName('home-ansible');
        $dhcpReady = $user !== null && in_array('page-dhcp-kea-v4', explode(',', (string)$user->priv), true);
    }
    foreach ($models as $model) {
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
    if ($home !== null) {
        $runtimeReady = $runtimeReady && homeRuntime($home, $homeDevice);
    }
    $reload = ($argv[3] ?? '') === 'api-change' || count($changes) > 0 || !$runtimeReady || ($state['phase'] ?? '') !== 'complete' || ($state['digest'] ?? '') !== $digest;
    $result = ['rules'=>$rules, 'acls'=>array_values($acls), 'hosts'=>array_values($hosts), 'domain'=>(string)$xml->system->domain, 'bootstrap_rule'=>$bootstrapRule, 'changed'=>count($changes) > 0, 'reload_required'=>$reload, 'changes'=>array_values(array_unique($changes)), 'management'=>$address, 'rule_count'=>count($rules), 'seed_id'=>$seed['seed_id']];
    $result += ['home_pilot'=>$home, 'dns_interfaces'=>$dnsInterfaces, 'dhcp_subnet'=>$dhcpSubnet, 'dhcp_api_ready'=>$dhcpReady, 'home_interface_reload'=>$homeInterfaceReload];

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
        if ($home !== null) {
            requireCondition(homeRuntime($home, $homeDevice), 'HOME address, DNS, DHCP or automatic NAT is not loaded');
        }
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
        $nextState = ['seed_id'=>$seed['seed_id'], 'digest'=>$digest, 'phase'=>'pending', 'backup'=>$backup];
        if ($home !== null) {
            $nextState['home_pilot'] = $home;
        }
        writePrivate($statePath, $nextState);
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
