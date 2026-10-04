<?php
declare(strict_types=1);
require_once('config.inc');

function wgEnsure(bool $condition, string $message): void
{
    if (!$condition) { throw new RuntimeException($message); }
}
function wgProtect(string $path, bool $directory = false): void
{
    wgEnsure(!is_link($path), 'Symlink WireGuard artifact');
    if (file_exists($path)) {
        wgEnsure(($directory ? is_dir($path) : is_file($path)) && fileowner($path) === 0 && (fileperms($path) & 0777) === ($directory ? 0700 : 0600), 'Unprotected WireGuard artifact');
    }
}
function wgWrite(string $path, array $value): void
{
    $temporary = tempnam(dirname($path), '.state-');
    wgEnsure($temporary !== false, 'Cannot allocate WireGuard state');
    try {
        chmod($temporary, 0600);
        wgEnsure(file_put_contents($temporary, json_encode($value, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT)."\n") !== false, 'Cannot write WireGuard state');
        wgEnsure(rename($temporary, $path), 'Cannot replace WireGuard state');
    } finally { if (file_exists($temporary)) { unlink($temporary); } }
}
function wgPrefix(string $address): string
{
    wgEnsure(filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false, 'Invalid WireGuard IPv4 address');
    return substr($address, 0, strrpos($address, '.') + 1);
}
function wgOrdinary(string $address, string $prefix): void
{
    wgEnsure(wgPrefix($address) === $prefix && !in_array(explode('.', $address)[3], ['0', '255'], true), 'Address must be an ordinary host on the declared /24');
}
function wgRule(string $name, int $sequence, string $source, string $destination, string $protocol, string $port = '', string $action = 'pass', string $interface = 'opt4'): array
{
    return ['enabled'=>'1', 'description'=>'Home automation: WG '.$name, 'sequence'=>(string)$sequence, 'quick'=>'1', 'action'=>$action, 'interface'=>$interface, 'interfacenot'=>'0', 'direction'=>'in', 'ipprotocol'=>'inet', 'protocol'=>$protocol, 'source_not'=>'0', 'source_net'=>$source, 'source_port'=>'', 'destination_not'=>'0', 'destination_net'=>$destination, 'destination_port'=>$port, 'gateway'=>'', 'replyto'=>'', 'disablereplyto'=>'0', 'statetype'=>'keep', 'log'=>$action === 'block' ? '1' : '0'];
}
function wgSame(array $actual, array $expected): bool
{
    foreach ($expected as $field=>$value) {
        if (($actual[$field] ?? '') !== $value) { return false; }
    }
    return true;
}
function wgRuntimeChecks(array $input, array $objects, array $observed): array
{
    $settings = $input['settings'];
    $checks = [
        'public_key'=>trim($observed['public_key']) === $input['server_public'],
        'listen_port'=>trim($observed['listen_port']) === (string)$settings['port'],
        'peer_allowed_ips'=>preg_split('/\s+/', trim($observed['allowed_ips'])) === [$input['peer_public'], $settings['peer_address'].'/32'],
        'tunnel_address'=>preg_match('/\binet '.preg_quote($settings['server_address'], '/').' netmask 0xffffff00\b/', $observed['interface']) === 1,
        'firewall_rules'=>true,
        'dns_acl'=>preg_match('/^'.preg_quote($settings['peer_address'].'/32', '/').'\s+allow\s*$/m', $observed['dns_acls']) === 1,
    ];
    foreach ($objects['filter rules'] as $object) {
        if ($object['uuid'] === '' || !str_contains($observed['rules'], $object['uuid'])) { $checks['firewall_rules'] = false; }
    }
    return $checks;
}
function wgRuntime(array $input, array $objects): array
{
    return wgRuntimeChecks($input, $objects, [
        'public_key'=>shell_exec('/usr/bin/wg show wg0 public-key 2>/dev/null') ?? '',
        'listen_port'=>shell_exec('/usr/bin/wg show wg0 listen-port 2>/dev/null') ?? '',
        'allowed_ips'=>shell_exec('/usr/bin/wg show wg0 allowed-ips 2>/dev/null') ?? '',
        'interface'=>shell_exec('/sbin/ifconfig wg0 2>/dev/null') ?? '',
        'rules'=>shell_exec('/sbin/pfctl -sr 2>/dev/null') ?? '',
        // The vendor parser resolves included files and rejects invalid configuration.
        'dns_acls'=>shell_exec('/usr/local/sbin/unbound-checkconf -o access-control /var/unbound/unbound.conf 2>/dev/null') ?? '',
    ]);
}

try {
    wgEnsure(count($argv) === 3, 'Supply operation and bounded WireGuard payload');
    $operation = $argv[1];
    wgEnsure(in_array($operation, ['plan','stage','activate','verify','complete'], true), 'Unknown WireGuard action');
    $input = json_decode(base64_decode($argv[2], true), true, 512, JSON_THROW_ON_ERROR);
    wgEnsure(is_array($input) && count($input) === 4 && isset($input['settings'],$input['server_public'],$input['peer_public'],$input['mtu']), 'Unexpected WireGuard payload');
    $settings = $input['settings'];
    foreach (['name','peer_name'] as $name) { wgEnsure(preg_match('/^[A-Za-z0-9_.-]{1,64}$/', $settings[$name]) === 1, 'Invalid owned WireGuard name'); }
    foreach (['server_public','peer_public'] as $key) { wgEnsure(strlen(base64_decode($input[$key], true) ?: '') === 32, 'Invalid WireGuard public key'); }
    wgEnsure($input['server_public'] !== $input['peer_public'] && is_int($settings['port']) && $settings['port'] >= 1 && $settings['port'] <= 65535, 'Invalid WireGuard keys or listener');
    wgEnsure(is_int($input['mtu']) && $input['mtu'] >= 1280 && $input['mtu'] <= 1500, 'Invalid WireGuard MTU');
    $tunnelPrefix = wgPrefix($settings['server_address']);
    $managementPrefix = wgPrefix($settings['management_address']);
    wgEnsure($settings['tunnel_subnet'] === $tunnelPrefix.'0/24' && $settings['management_subnet'] === $managementPrefix.'0/24', 'Subnets must be canonical /24 networks');
    wgOrdinary($settings['server_address'], $tunnelPrefix);
    wgOrdinary($settings['peer_address'], $tunnelPrefix);
    wgEnsure($settings['peer_address'] !== $settings['server_address'], 'Duplicate tunnel addresses');
    foreach (['management_address','proxmox_address','switch_address'] as $field) { wgOrdinary($settings[$field], $managementPrefix); }
    wgEnsure(count(array_unique([$settings['management_address'],$settings['proxmox_address'],$settings['switch_address']])) === 3, 'Duplicate administration targets');
    $config = \OPNsense\Core\Config::getInstance();
    // Activation invokes another vendor process that must read config.xml;
    // only configuration/record writes hold the exclusive configuration lock.
    if (in_array($operation, ['stage','complete'], true)) { $config->lock(); }
    $xml = $config->object();
    $seed = json_decode(file_get_contents('/conf/ansible-install.json'), true, 512, JSON_THROW_ON_ERROR);
    $pilot = json_decode(file_get_contents('/conf/ansible-pilot/state.json'), true, 512, JSON_THROW_ON_ERROR);
    wgEnsure($pilot['phase'] === 'complete' && $pilot['seed_id'] === $seed['seed_id'] && isset($pilot['home_pilot']), 'Complete the installed HOME pilot first');
    wgEnsure($seed['address'] === $settings['management_address'] && (string)$xml->interfaces->lan->ipaddr === $settings['management_address'] && (string)$xml->interfaces->lan->subnet === '24', 'Installed MGMT identity conflicts');
    wgEnsure($pilot['home_pilot']['address'] === $settings['endpoint'] && (string)$xml->interfaces->opt1->ipaddr === $settings['endpoint'], 'WireGuard must listen on the installed HOME pilot');
    $homePrefix = wgPrefix($settings['endpoint']);
    wgEnsure(count(array_unique([$tunnelPrefix,$managementPrefix,$homePrefix])) === 3, 'Tunnel overlaps an existing network');
    foreach ([$tunnelPrefix,$managementPrefix,$homePrefix] as $prefix) { wgEnsure(str_starts_with($prefix, '10.'), 'Use private 10/8 networks'); }
    wgEnsure(!isset($xml->interfaces->opt2->enable) && !isset($xml->interfaces->opt3->enable), 'DEV and BMC require separate routing workflows');
    $wan = shell_exec('/sbin/ifconfig '.escapeshellarg((string)$xml->interfaces->wan->if)) ?? '';
    wgEnsure(preg_match('/inet ([0-9.]+)/', $wan, $wanMatch) === 1 && wgPrefix($wanMatch[1]) !== $tunnelPrefix, 'Tunnel overlaps WAN or WAN is unavailable');
    $directory='/conf/ansible-wireguard'; $record=$directory.'/state.json';
    wgProtect($directory, true); wgProtect($record);
    $previous=is_file($record) ? json_decode(file_get_contents($record), true, 512, JSON_THROW_ON_ERROR) : [];
    if ($previous !== []) {
        wgEnsure(($previous['version'] ?? null) === 1 && $previous['seed_id'] === $seed['seed_id'] && $previous['input'] == $input && in_array($previous['phase'], ['pending','complete'], true), 'Recorded WireGuard allocation or keys conflict; migration/rotation requires separate review');
        wgEnsure(dirname($previous['backup']) === $directory && is_file($previous['backup']), 'Missing original WireGuard backup');
        wgProtect($previous['backup']);
    }
    $serverModel=new \OPNsense\Wireguard\Server(); $clientModel=new \OPNsense\Wireguard\Client();
    $server=null; $serverUuid=''; $peer=null; $peerUuid=''; $changes=[]; $actionChanged=false;
    foreach ($clientModel->clients->client->iterateItems() as $uuid=>$node) {
        wgEnsure($peer === null && (string)$node->name === $settings['peer_name'] && $previous !== [], 'Unowned or additional WireGuard peer');
        wgEnsure((string)$node->pubkey === $input['peer_public'] && (string)$node->psk === '', 'Peer key conflicts');
        $peer=$node; $peerUuid=$uuid;
    }
    foreach ($serverModel->servers->server->iterateItems() as $uuid=>$node) {
        wgEnsure($server === null && (string)$node->name === $settings['name'] && $previous !== [], 'Unowned or additional WireGuard instance');
        wgEnsure((string)$node->pubkey === $input['server_public'] && (string)$node->instance === '0', 'Instance key or interface conflicts');
        $server=$node; $serverUuid=$uuid;
    }
    if ($peer === null || !wgSame($peer->getNodeContent(), ['enabled'=>'1','tunneladdress'=>$settings['peer_address'].'/32','serveraddress'=>'','serverport'=>'','keepalive'=>''])) { $changes[]='WireGuard peer'; }
    if ($server === null || !wgSame($server->getNodeContent(), ['enabled'=>'1','port'=>(string)$settings['port'],'mtu'=>(string)$input['mtu'],'tunneladdress'=>$settings['server_address'].'/24','dns'=>'','disableroutes'=>'0','gateway'=>'','peers'=>$peerUuid])) { $changes[]='WireGuard instance'; }
    if ((string)(new \OPNsense\Wireguard\General())->enabled !== '1') { $changes[]='WireGuard service'; }
    // The GUI's "None" mode is empty; literal "none" causes interface_configure()
    // to flush the addresses assigned by the WireGuard instance on startup.
    $interfaceExpected=['if'=>'wg0','descr'=>'WG_ADMIN','enable'=>'1','ipaddr'=>'','ipaddrv6'=>''];
    $interfaceExists=isset($xml->interfaces->opt4);
    if ($interfaceExists) {
        wgEnsure($previous !== [] && (string)$xml->interfaces->opt4->if === 'wg0' && (string)$xml->interfaces->opt4->descr === 'WG_ADMIN', 'Unowned WireGuard interface assignment');
        foreach (['gateway','bridge','blockpriv','blockbogons'] as $field) { wgEnsure(!isset($xml->interfaces->opt4->{$field}), 'Unexpected WireGuard interface service'); }
    }
    $nativeChanged=!$interfaceExists;
    if ($interfaceExists) {
        foreach ($interfaceExpected as $field=>$value) { if ((string)$xml->interfaces->opt4->{$field} !== $value) { $nativeChanged=true; } }
    }
    if ($nativeChanged) { $changes[]='WG_ADMIN interface'; }
    // Candidate interface exists only in memory during plan; API modules save supported models.
    if (!$interfaceExists) { $xml->interfaces->addChild('opt4'); }
    foreach ($interfaceExpected as $field=>$value) {
        if ($value === '') { unset($xml->interfaces->opt4->{$field}); }
        else { $xml->interfaces->opt4->{$field}=$value; }
    }
    $source=$settings['peer_address'].'/32'; $gateway=$settings['management_address'].'/32'; $rules=[];
    $rules[]=wgRule('HOME handshake',335,$pilot['home_pilot']['subnet'],$settings['endpoint'].'/32','UDP',(string)$settings['port'],'pass','opt1');
    $rules[]=wgRule('switch gateway probe',65,$settings['switch_address'].'/32',$gateway,'ICMP','','pass','lan');
    $sequence=500;
    foreach ([['firewall HTTPS',$gateway,'TCP','443'],['firewall SSH',$gateway,'TCP','22'],['DNS TCP',$gateway,'TCP','53'],['DNS UDP',$gateway,'UDP','53'],['NTP',$gateway,'UDP','123'],['firewall ICMP',$gateway,'ICMP',''],['tunnel ICMP',$settings['server_address'].'/32','ICMP',''],['Proxmox SSH',$settings['proxmox_address'].'/32','TCP','22'],['Proxmox UI',$settings['proxmox_address'].'/32','TCP','8006'],['switch SSH',$settings['switch_address'].'/32','TCP','22'],['Proxmox ICMP',$settings['proxmox_address'].'/32','ICMP',''],['switch ICMP',$settings['switch_address'].'/32','ICMP','']] as [$name,$destination,$protocol,$port]) {
        $rules[]=wgRule($name,$sequence,$source,$destination,$protocol,$port); $sequence+=10;
    }
    $rules[]=wgRule('default deny',900,'any','any','any','','block');
    $acl=['enabled'=>'1','name'=>'WG_ADMIN','action'=>'allow','description'=>'Home automation: WG DNS ACL','networks'=>$source];
    $filter=new \OPNsense\Firewall\Filter(); $unbound=new \OPNsense\Unbound\Unbound(); $objects=[];
    foreach (['filter rules'=>[$filter->rules->rule,$rules,'description'],'DNS access lists'=>[$unbound->acls->acl,[$acl],'name']] as $label=>[$container,$desired,$identity]) {
        $found=[];
        foreach ($container->iterateItems() as $uuid=>$node) { $key=(string)$node->{$identity}; wgEnsure(!isset($found[$key]), 'Duplicate policy identity'); $found[$key]=['uuid'=>$uuid,'values'=>$node->getNodeContent()]; }
        $objects[$label]=[];
        foreach ($desired as $values) {
            $existing=$found[$values[$identity]] ?? null;
            wgEnsure($existing === null || $previous !== [], 'Unowned named WireGuard policy');
            $uuid=$existing['uuid'] ?? '';
            if ($existing === null || !wgSame($existing['values'],$values)) { $changes[]=$label; }
            $objects[$label][]= ['uuid'=>$uuid,'values'=>$values];
            if ($existing !== null) { $container->del($uuid); }
            $container->add($uuid !== '' ? $uuid : null)->setNodes($values);
        }
    }
    foreach ([$filter,$unbound] as $model) { wgEnsure(count($model->performValidation()) === 0, 'Vendor policy model rejected WireGuard settings'); }
    $apiUser=(new \OPNsense\Auth\User())->getUserByName('home-ansible');
    $apiReady=$apiUser !== null && in_array('page-wireguard-config', explode(',',(string)$apiUser->priv),true);
    $runtimeChecks=wgRuntime($input,$objects);
    $runtimeReady=$previous !== [] && !in_array(false,$runtimeChecks,true);
    $reload=count($changes)>0 || !$runtimeReady || ($previous['phase'] ?? '') !== 'complete';
    if ($operation === 'stage' && $reload) {
        if (!is_dir($directory)) { wgEnsure(mkdir($directory,0700), 'Cannot create WireGuard record directory'); }
        $backup=$previous['backup'] ?? $directory.'/before-'.gmdate('Ymd\THis\Z').'-'.bin2hex(random_bytes(4)).'.xml';
        if (!is_file($backup)) {
            $descriptor=fopen($backup,'x'); wgEnsure($descriptor !== false,'Cannot preserve pre-change configuration'); chmod($backup,0600);
            fwrite($descriptor,file_get_contents('/conf/config.xml')); fclose($descriptor);
        }
        $next=['version'=>1,'seed_id'=>$seed['seed_id'],'input'=>$input,'phase'=>'pending','backup'=>$backup,'objects'=>$objects];
        wgWrite($record,$next);
        // Candidate API models above are not serialized. Only the native interface is saved here.
        if ($nativeChanged) { $config->save(); }
        $previous=$next;
        $actionChanged=true;
    }
    if ($operation === 'activate') {
        wgEnsure($previous !== [] && count($changes) === 0, 'Save the owned WireGuard settings before activating the tunnel');
        if (!$runtimeChecks['tunnel_address']) {
            wgEnsure($runtimeChecks['public_key'] && $runtimeChecks['listen_port'] && $runtimeChecks['peer_allowed_ips'], 'Reload the owned WireGuard instance before restoring its tunnel address');
            wgEnsure(preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $serverUuid) === 1, 'Invalid owned WireGuard instance UUID');
            // Reconfigure may skip an unchanged cached instance after its address
            // was flushed. The vendor's scoped start reapplies this instance only.
            $output=[]; $status=0;
            exec('/usr/local/sbin/configctl wireguard start '.escapeshellarg($serverUuid).' 2>&1', $output, $status);
            wgEnsure($status === 0, 'Vendor WireGuard activation failed');
            $actionChanged=true;
            $runtimeChecks=wgRuntime($input,$objects);
            $runtimeReady=!in_array(false,$runtimeChecks,true);
            wgEnsure($runtimeChecks['tunnel_address'], 'Vendor WireGuard activation did not restore the tunnel address');
        }
    }
    if (in_array($operation,['verify','complete'],true)) {
        $failedChecks=array_keys(array_filter($runtimeChecks, static fn(bool $ready): bool => !$ready));
        wgEnsure($previous !== [] && count($changes) === 0 && $runtimeReady, 'WireGuard needs reconciliation; saved changes: '.implode(', ',array_unique($changes)).'; runtime checks: '.implode(', ',$failedChecks));
        if ($operation === 'complete' && $previous['phase'] !== 'complete') {
            $previous['phase']='complete'; $previous['objects']=$objects; wgWrite($record,$previous);
            $actionChanged=true;
        }
        if ($operation === 'verify') { wgEnsure($previous['phase'] === 'complete', 'WireGuard apply was interrupted'); }
    }
    echo json_encode(['changed'=>$actionChanged,'changes'=>array_values(array_unique($changes)),'reload_required'=>$reload,'api_ready'=>$apiReady,'interface_exists'=>$interfaceExists,'peer_exists'=>$peer !== null,'rules'=>$rules,'acl'=>$acl,'backup'=>$previous['backup'] ?? null,'runtime_ready'=>$runtimeReady,'runtime_checks'=>$runtimeChecks], JSON_THROW_ON_ERROR)."\n";
} catch (Throwable $error) {
    fwrite(STDERR,$error->getMessage()."\n"); exit(1);
}
