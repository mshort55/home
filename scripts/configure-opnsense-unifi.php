<?php
declare(strict_types=1);
require_once('config.inc');
// LAB_EXTENSION_LIBRARY

function unifiRequire(bool $condition, string $message): void
{
    if (!$condition) { throw new RuntimeException($message); }
}
function unifiProtect(string $path, bool $directory = false): void
{
    unifiRequire(!is_link($path), 'Symlink controller policy artifact');
    if (file_exists($path)) {
        unifiRequire(($directory ? is_dir($path) : is_file($path)) && fileowner($path) === 0 && (fileperms($path) & 0777) === ($directory ? 0700 : 0600), 'Unprotected controller policy artifact');
    }
}
function unifiWrite(string $path, array $value): void
{
    $temporary = tempnam(dirname($path), '.state-');
    unifiRequire($temporary !== false, 'Cannot allocate controller policy record');
    try {
        chmod($temporary, 0600);
        unifiRequire(file_put_contents($temporary, json_encode($value, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT)."\n") !== false && rename($temporary, $path), 'Cannot preserve controller policy record');
    } finally { if (file_exists($temporary)) { unlink($temporary); } }
}
function unifiSame(array $actual, array $expected): bool
{
    foreach ($expected as $key=>$value) { if (($actual[$key] ?? '') !== $value) { return false; } }
    return true;
}
try {
    unifiRequire(count($argv) === 3 && in_array($argv[1], ['plan','stage','verify','complete'], true), 'Use an explicit controller policy operation');
    $operation=$argv[1];
    $input=json_decode(base64_decode($argv[2], true), true, 512, JSON_THROW_ON_ERROR);
    foreach (['address','gateway','tunnel_address','recovery_address'] as $field) {
        $address=$field === 'address' ? explode('/', $input[$field])[0] : $input[$field];
        unifiRequire(filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false, 'Invalid controller address');
    }
    $address=explode('/', $input['address'])[0];
    $prefix=substr($input['gateway'],0,strrpos($input['gateway'],'.')+1);
    unifiRequire($input['vmid'] === 110 && $input['name'] === 'unifi01' && $input['vlan'] === 10 && $input['address'] === $prefix.'20/24' && $input['recovery_address'] === $prefix.'250', 'Unexpected permanent controller allocation');
    unifiRequire(preg_match('/^[a-z0-9.-]+$/', $input['domain']) === 1 && str_starts_with($prefix,'10.'), 'Unexpected controller DNS identity');
    $config=\OPNsense\Core\Config::getInstance();
    if (in_array($operation,['stage','complete'],true)) { $config->lock(); }
    $xml=$config->object();
    $seed=json_decode(file_get_contents('/conf/ansible-install.json'),true,512,JSON_THROW_ON_ERROR);
    $wg=json_decode(file_get_contents('/conf/ansible-wireguard/state.json'),true,512,JSON_THROW_ON_ERROR);
    unifiRequire($seed['address'] === $input['gateway'] && (string)$xml->interfaces->lan->ipaddr === $input['gateway'] && $wg['phase'] === 'complete' && $wg['input']['settings']['peer_address'] === $input['tunnel_address'], 'Complete the matching MGMT and WireGuard pilot first');
    $directory='/conf/ansible-unifi'; $record=$directory.'/state.json';
    unifiProtect($directory,true); unifiProtect($record);
    $previous=is_file($record) ? json_decode(file_get_contents($record),true,512,JSON_THROW_ON_ERROR) : [];
    if ($previous !== []) {
        unifiRequire($previous['version'] === 1 && $previous['seed_id'] === $seed['seed_id'] && $previous['input'] === $input && in_array($previous['phase'],['pending','complete'],true), 'Recorded controller policy allocation conflicts');
        unifiProtect($previous['backup']);
        unifiRequire(dirname($previous['backup']) === $directory && is_file($previous['backup']), 'Missing original controller policy backup');
    }
    $policy=labUnifiPolicy($input);
    $rules=$policy['filter rules']; $host=$policy['DNS host records'][0];
    $filter=new \OPNsense\Firewall\Filter(); $unbound=new \OPNsense\Unbound\Unbound();
    $objects=[]; $changes=[]; $runtime=true;
    $loaded=shell_exec('/sbin/pfctl -sr 2>/dev/null') ?? '';
    foreach (['rules'=>[$filter->rules->rule,$rules],'hosts'=>[$unbound->hosts->host,[$host]]] as $kind=>[$container,$desired]) {
        $objects[$kind]=[];
        foreach ($desired as $values) {
            $matches=[];
            foreach ($container->iterateItems() as $uuid=>$node) {
                if ((string)$node->description === $values['description'] || ($kind === 'hosts' && (string)$node->hostname === $host['hostname'] && (string)$node->domain === $host['domain'] && (string)$node->rr === 'A')) { $matches[$uuid]=$node; }
            }
            unifiRequire(count($matches) <= 1 && ($matches === [] || $previous !== []), 'Unowned or duplicate named controller policy');
            $uuid=$matches === [] ? '' : array_key_first($matches);
            $current=$uuid !== '' ? $matches[$uuid]->getNodeContent() : [];
            if (!unifiSame($current,$values)) { $changes[]=$kind; }
            if ($kind === 'rules' && ($uuid === '' || !str_contains($loaded,$uuid))) { $runtime=false; }
            $objects[$kind][]=['uuid'=>$uuid,'values'=>$values];
            if ($uuid !== '') { $container->del($uuid); }
            $container->add($uuid !== '' ? $uuid : null)->setNodes($values);
        }
    }
    foreach ([$filter,$unbound] as $model) { unifiRequire(count($model->performValidation()) === 0, 'Vendor rejected the candidate controller policy'); }
    // Preserve the private-range denies and ensure the new update rules precede default deny.
    $privateCount=0; $mgmtDefault=false; $wgDefault=false;
    foreach ($filter->rules->rule->iterateItems() as $node) {
        $description=(string)$node->description;
        if (str_starts_with($description,'Home automation: MGMT private deny ')) {
            unifiRequire((string)$node->enabled === '1' && (string)$node->action === 'block' && (string)$node->quick === '1' && (string)$node->interface === 'lan' && (int)(string)$node->sequence < 131, 'Preserve MGMT private-network denial ahead of controller updates');
            $privateCount++;
        }
        if ($description === 'Home automation: MGMT default deny') { $mgmtDefault=(string)$node->enabled === '1' && (string)$node->action === 'block' && (int)(string)$node->sequence > 132; }
        if ($description === 'Home automation: WG default deny') { $wgDefault=(string)$node->enabled === '1' && (string)$node->action === 'block' && (int)(string)$node->sequence > 810; }
    }
    unifiRequire($privateCount === 5 && $mgmtDefault && $wgDefault, 'Existing MGMT/WireGuard deny policy conflicts');
    $resolved=shell_exec('/usr/bin/drill '.escapeshellarg($input['name'].'.'.$input['domain']).' @127.0.0.1 2>/dev/null') ?? '';
    $dnsReady=preg_match('/^'.preg_quote($input['name'].'.'.$input['domain'].'.','/').'\s+\d+\s+IN\s+A\s+'.preg_quote($address,'/').'\s*$/m',$resolved) === 1;
    $reload=$changes !== [] || !$runtime || !$dnsReady || ($previous['phase'] ?? '') !== 'complete';
    $changed=false;
    if ($operation === 'stage' && $reload) {
        if (!is_dir($directory)) { unifiRequire(mkdir($directory,0700),'Cannot create controller policy directory'); }
        $backup=$previous['backup'] ?? $directory.'/before-'.gmdate('Ymd\THis\Z').'-'.bin2hex(random_bytes(4)).'.xml';
        if (!is_file($backup)) {
            $handle=fopen($backup,'x'); unifiRequire($handle !== false,'Cannot preserve original firewall configuration'); chmod($backup,0600);
            unifiRequire(fwrite($handle,file_get_contents('/conf/config.xml')) !== false,'Cannot export original configuration'); fclose($handle);
        }
        $previous=['version'=>1,'phase'=>'pending','seed_id'=>$seed['seed_id'],'input'=>$input,'backup'=>$backup];
        unifiWrite($record,$previous); $changed=true;
    }
    if (in_array($operation,['verify','complete'],true)) {
        unifiRequire($previous !== [] && $changes === [] && $runtime && $dnsReady,'Controller network policy needs reconciliation; saved: '.implode(',',array_unique($changes)).'; loaded rules: '.($runtime ? 'ready' : 'missing').'; DNS: '.($dnsReady ? 'ready' : 'missing'));
        if ($operation === 'complete' && $previous['phase'] !== 'complete') { $previous['phase']='complete'; unifiWrite($record,$previous); $changed=true; }
        if ($operation === 'verify') { unifiRequire($previous['phase'] === 'complete','Complete the controller network transaction first'); }
    }
    echo json_encode(['changed'=>$changed,'rules'=>array_column($objects['rules'],'values'),'host'=>$host,'reload_required'=>$reload,'backup'=>$previous['backup'] ?? null,'changes'=>array_values(array_unique($changes))],JSON_THROW_ON_ERROR)."\n";
} catch (Throwable $error) { fwrite(STDERR,$error->getMessage()."\n"); exit(1); }
