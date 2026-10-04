<?php
declare(strict_types=1);
require_once('config.inc');

function wifiEnsure(bool $condition, string $message): void
{
    if (!$condition) { throw new RuntimeException($message); }
}
function wifiPrivate(string $path, bool $directory = false): void
{
    wifiEnsure(!is_link($path), 'Symlink Wi-Fi ownership artifact');
    if (file_exists($path)) {
        wifiEnsure(($directory ? is_dir($path) : is_file($path)) && fileowner($path) === 0 && (fileperms($path) & 0777) === ($directory ? 0700 : 0600), 'Unprotected Wi-Fi ownership artifact');
    }
}
function wifiWrite(string $path, array $data): void
{
    $temporary = tempnam(dirname($path), '.state-');
    wifiEnsure($temporary !== false, 'Cannot allocate Wi-Fi record');
    try {
        chmod($temporary, 0600);
        wifiEnsure(file_put_contents($temporary, json_encode($data, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT)."\n") !== false, 'Cannot write Wi-Fi record');
        wifiEnsure(rename($temporary, $path), 'Cannot replace Wi-Fi record');
    } finally { if (file_exists($temporary)) { unlink($temporary); } }
}
function wifiCommand(string $command): string
{
    $output = []; $status = 0;
    exec($command, $output, $status);
    wifiEnsure($status === 0, 'Wi-Fi runtime inspection failed: '.$command);
    return implode("\n", $output);
}
function wifiPrefix(string $address): string
{
    wifiEnsure(filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false, 'Invalid Wi-Fi IPv4 address');
    return substr($address, 0, strrpos($address, '.') + 1);
}
function wifiRule(array $input): array
{
    return ['enabled'=>'1','description'=>'Home automation: WG private Wi-Fi handshake','sequence'=>'5','quick'=>'1','action'=>'pass','interface'=>'wan','interfacenot'=>'0','direction'=>'in','ipprotocol'=>'inet','protocol'=>'UDP','source_not'=>'0','source_net'=>$input['wifi']['wifi_address'].'/32','source_port'=>'','destination_not'=>'0','destination_net'=>$input['wifi']['wan_address'].'/32','destination_port'=>(string)$input['wireguard']['port'],'gateway'=>'','replyto'=>'','disablereplyto'=>'1','statetype'=>'keep','log'=>'1'];
}
function wifiSame(array $actual, array $expected): bool
{
    foreach ($expected as $name=>$value) { if (($actual[$name] ?? '') !== $value) { return false; } }
    return true;
}
function wifiStates(array $input): array
{
    $source=preg_quote($input['wifi']['wifi_address'], '/');
    $destination=preg_quote($input['wifi']['wan_address'].':'.$input['wireguard']['port'], '/');
    return array_values(array_filter(explode("\n", wifiCommand('/sbin/pfctl -ss')), static fn(string $line): bool => preg_match('/\budp\b/', $line) === 1 && preg_match('/(?<![0-9.])'.$source.':/', $line) === 1 && preg_match('/(?<![0-9.])'.$destination.'\b/', $line) === 1));
}
function wifiLoaded(string $uuid, array $input, string $device): bool
{
    if ($uuid === '') { return false; }
    $source=preg_quote($input['wifi']['wifi_address'], '/');
    $destination=preg_quote($input['wifi']['wan_address'], '/');
    $port=(string)$input['wireguard']['port'];
    $pattern='/^pass in log quick on '.preg_quote($device, '/').' inet proto udp from '.$source.' to '.$destination.' port = '.$port.' .*label "'.preg_quote($uuid, '/').'"/m';
    return preg_match($pattern, wifiCommand('/sbin/pfctl -sr')) === 1;
}
function wifiLoadedLabels(array $input, string $rules): array
{
    // A submission interrupted before UUID capture can leave a loaded rule
    // after its saved API object disappeared. Match its exact transport tuple.
    $source=preg_quote($input['wifi']['wifi_address'], '/');
    $destination=preg_quote($input['wifi']['wan_address'], '/');
    $port=(string)$input['wireguard']['port'];
    preg_match_all('/^pass in(?: log)? quick on \S+ inet proto udp from '.$source.' to '.$destination.' port = '.$port.' .*label "([^"]+)"/m', $rules, $matches);
    return array_values(array_unique($matches[1]));
}

try {
    wifiEnsure(count($argv) === 3, 'Supply operation and bounded Wi-Fi payload');
    $operation=$argv[1];
    wifiEnsure(in_array($operation, ['inspect','plan','stage','complete','verify','plan_remove','stage_remove','complete_remove','verify_absent'], true), 'Unknown Wi-Fi operation');
    $removing=in_array($operation, ['plan_remove','stage_remove','complete_remove','verify_absent'], true);
    $input=json_decode(base64_decode($argv[2], true), true, 512, JSON_THROW_ON_ERROR);
    wifiEnsure(is_array($input) && isset($input['wireguard']), 'Missing installed WireGuard identity');
    $config=\OPNsense\Core\Config::getInstance();
    $seed=json_decode(file_get_contents('/conf/ansible-install.json'), true, 512, JSON_THROW_ON_ERROR);
    $xml=$config->object();
    wifiEnsure($seed['address'] === $input['wireguard']['management_address'] && (string)$xml->interfaces->lan->ipaddr === $seed['address'], 'Wrong installed management guest');
    $device=(string)$xml->interfaces->wan->if;
    wifiEnsure(preg_match('/^vtnet[0-9]+$/', $device) === 1, 'Unexpected WAN interface');
    $wan=$removing ? '' : wifiCommand('/sbin/ifconfig '.escapeshellarg($device));
    $route=$removing ? '' : wifiCommand('/sbin/route -n get default');
    preg_match('/\binet ([0-9.]+) netmask (0x[0-9a-f]+)/', $wan, $wanMatch);
    preg_match('/\bether ([0-9a-f:]+)/', $wan, $macMatch);
    preg_match('/gateway:\s+([0-9.]+)/', $route, $routeMatch);
    if ($operation === 'inspect') {
        echo json_encode(['wan_address'=>$wanMatch[1] ?? null,'wan_mac'=>$macMatch[1] ?? null,'wan_gateway'=>$routeMatch[1] ?? null,'home_endpoint'=>$input['wireguard']['endpoint'],'wireguard_port'=>$input['wireguard']['port']], JSON_THROW_ON_ERROR)."\n";
        exit(0);
    }
    $directory='/conf/ansible-wireguard-wifi'; $record=$directory.'/state.json';
    wifiPrivate($directory, true); wifiPrivate($record);
    $previous=is_file($record) ? json_decode(file_get_contents($record), true, 512, JSON_THROW_ON_ERROR) : [];
    if ($previous !== []) {
        wifiEnsure(($previous['version'] ?? null) === 1 && $previous['seed_id'] === $seed['seed_id'] && in_array($previous['phase'], ['pending','complete','removing','absent'], true), 'Invalid Wi-Fi ownership record');
        wifiEnsure(dirname($previous['backup']) === $directory && is_file($previous['backup']), 'Missing Wi-Fi pre-change backup');
        wifiPrivate($previous['backup']);
        wifiEnsure($previous['object']['values'] === wifiRule($previous['input']), 'Wi-Fi record does not describe the bounded ingress rule');
    }
    $filter=new \OPNsense\Firewall\Filter(); $found=null; $uuid=''; $name='Home automation: WG private Wi-Fi handshake';
    foreach ($filter->rules->rule->iterateItems() as $id=>$node) {
        if ((string)$node->description === $name) {
            wifiEnsure($found === null && $previous !== [], 'Unowned or duplicate Wi-Fi rule');
            wifiEnsure($previous['object']['uuid'] === '' || $previous['object']['uuid'] === $id, 'Wi-Fi rule UUID changed');
            $found=$node; $uuid=$id;
        }
    }
    if ($removing) {
        $changed=false;
        $savedAbsent=$found === null;
        $loaded=wifiCommand('/sbin/pfctl -sr');
        $recordUuid=$uuid !== '' ? $uuid : ($previous['object']['uuid'] ?? '');
        $loadedLabels=$previous === [] ? [] : wifiLoadedLabels($previous['input'], $loaded);
        if ($recordUuid === '' && count($loadedLabels) === 1) { $recordUuid=$loadedLabels[0]; }
        $loadedAbsent=($recordUuid === '' || !str_contains($loaded, $recordUuid)) && $loadedLabels === [] && !str_contains($loaded, $name);
        $states=$previous === [] ? [] : wifiStates($previous['input']);
        if ($operation === 'stage_remove' && $previous !== [] && ($previous['phase'] !== 'absent' || !$savedAbsent || !$loadedAbsent || $states !== [])) {
            // Record removal before API deletion so an interrupted run can resume.
            $previous['phase']='removing'; $previous['object']['uuid']=$recordUuid; wifiWrite($record, $previous);
            $changed=true;
        }
        if ($operation === 'complete_remove') {
            wifiEnsure($savedAbsent && $loadedAbsent, 'Reload the firewall after removing the Wi-Fi rule');
            if ($states !== []) {
                wifiEnsure(preg_match('/^[0-9a-f-]{36}$/', $recordUuid) === 1, 'Invalid Wi-Fi rule UUID');
                wifiCommand('/sbin/pfctl -k label -k '.escapeshellarg($recordUuid));
                $changed=true;
                wifiEnsure(wifiStates($previous['input']) === [], 'Wi-Fi UDP states remain after scoped removal');
            }
            if ($previous !== [] && $previous['phase'] !== 'absent') {
                $previous['phase']='absent'; wifiWrite($record, $previous); $changed=true;
            }
        }
        if ($operation === 'verify_absent') { wifiEnsure($savedAbsent && $loadedAbsent && $states === [] && ($previous === [] || $previous['phase'] === 'absent'), 'Remove the Wi-Fi pilot rule and states before ISP attachment'); }
        echo json_encode(['changed'=>$changed,'rule_absent'=>$savedAbsent,'loaded_absent'=>$loadedAbsent,'states'=>count($states),'phase'=>$previous['phase'] ?? 'absent','description'=>$name,'backup'=>$previous['backup'] ?? null,'reload_required'=>!$savedAbsent || !$loadedAbsent || ($previous['phase'] ?? 'absent') === 'removing'], JSON_THROW_ON_ERROR)."\n";
        exit(0);
    }
    wifiEnsure(isset($input['wifi']) && is_array($input['wifi']) && count($input['wifi']) === 4, 'Supply the explicit reserved Wi-Fi addresses, gateway and WAN MAC');
    $wifi=$input['wifi']; $prefix=wifiPrefix($wifi['wan_gateway']);
    wifiEnsure(str_starts_with($prefix, '10.') && $prefix !== wifiPrefix($input['wireguard']['endpoint']) && $prefix !== wifiPrefix($seed['address']) && $prefix !== wifiPrefix($input['wireguard']['server_address']), 'Private WAN must be separate from HOME, MGMT and WireGuard');
    foreach (['wifi_address','wan_address','wan_gateway'] as $field) { wifiEnsure(wifiPrefix($wifi[$field]) === $prefix && !in_array(explode('.', $wifi[$field])[3], ['0','255'], true), 'Invalid private Wi-Fi host address'); }
    wifiEnsure(count(array_unique([$wifi['wifi_address'],$wifi['wan_address'],$wifi['wan_gateway']])) === 3, 'Duplicate private WAN identities');
    wifiEnsure(($wanMatch[1] ?? null) === $wifi['wan_address'] && ($wanMatch[2] ?? null) === '0xffffff00' && ($routeMatch[1] ?? null) === $wifi['wan_gateway'] && ($macMatch[1] ?? null) === strtolower($wifi['wan_mac']), 'WAN differs from the reviewed private pilot; removal remains available');
    wifiEnsure((string)$xml->interfaces->wan->ipaddr === 'dhcp' && isset($xml->interfaces->wan->enable) && !isset($xml->interfaces->wan->blockpriv) && !isset($xml->interfaces->wan->blockbogons), 'Expected DHCP private WAN is not configured');
    wifiPrivate('/conf/ansible-wireguard', true); wifiPrivate('/conf/ansible-wireguard/state.json');
    $wg=json_decode(file_get_contents('/conf/ansible-wireguard/state.json'), true, 512, JSON_THROW_ON_ERROR);
    wifiEnsure($wg['seed_id'] === $seed['seed_id'] && $wg['phase'] === 'complete' && $wg['input']['settings'] === $input['wireguard'], 'Complete the exact HOME WireGuard workflow first');
    wifiPrivate('/conf/ansible-pilot', true); wifiPrivate('/conf/ansible-pilot/state.json');
    $pilot=json_decode(file_get_contents('/conf/ansible-pilot/state.json'), true, 512, JSON_THROW_ON_ERROR);
    wifiEnsure($pilot['phase'] === 'complete' && $pilot['seed_id'] === $seed['seed_id'] && ($pilot['home_pilot']['address'] ?? null) === $input['wireguard']['endpoint'], 'Complete the matching private HOME pilot first');
    wifiEnsure($previous === [] || $previous['phase'] === 'absent' && $found === null || $previous['input'] === $input && in_array($previous['phase'], ['pending','complete'], true), 'Remove the previous Wi-Fi exception before changing its allocation');
    $values=wifiRule($input); $deny=null;
    foreach ($filter->rules->rule->iterateItems() as $id=>$node) {
        if ((string)$node->description === 'Home automation: WAN default deny') { wifiEnsure($deny === null, 'Duplicate WAN deny'); $deny=$node; }
        if ((string)$node->interface === 'wan' && (string)$node->action === 'pass') { wifiEnsure($id === $uuid, 'Unowned WAN pass rule requires review'); }
    }
    wifiEnsure($deny !== null && (string)$deny->enabled === '1' && (string)$deny->action === 'block' && (string)$deny->quick === '1' && (string)$deny->source_net === 'any' && (string)$deny->destination_net === 'any' && (int)(string)$deny->sequence > 5, 'Expected WAN default deny is missing');
    $matches=$found !== null && wifiSame($found->getNodeContent(), $values);
    $runtime=$matches && wifiLoaded($uuid, $input, $device);
    $reload=!$matches || !$runtime || ($previous['phase'] ?? '') !== 'complete';
    $changed=false;
    if ($operation === 'stage' && $reload) {
        if (!is_dir($directory)) { wifiEnsure(mkdir($directory, 0700), 'Cannot create Wi-Fi record directory'); }
        $backup=$previous !== [] && $previous['phase'] !== 'absent' ? $previous['backup'] : $directory.'/before-'.gmdate('Ymd\THis\Z').'-'.bin2hex(random_bytes(4)).'.xml';
        if (!is_file($backup)) {
            $file=fopen($backup, 'x'); wifiEnsure($file !== false, 'Cannot preserve Wi-Fi pre-change configuration'); chmod($backup, 0600);
            wifiEnsure(fwrite($file, file_get_contents('/conf/config.xml')) !== false, 'Cannot write Wi-Fi backup'); fclose($file);
        }
        $next=['version'=>1,'seed_id'=>$seed['seed_id'],'phase'=>'pending','input'=>$input,'backup'=>$backup,'object'=>['uuid'=>$uuid,'values'=>$values]];
        if ($previous !== $next) { wifiWrite($record, $next); $changed=true; }
        $previous=$next;
    }
    if (in_array($operation, ['complete','verify'], true)) {
        wifiEnsure($previous !== [] && $matches && $runtime, 'Saved or loaded Wi-Fi ingress rule needs reconciliation');
        if ($operation === 'complete' && $previous['phase'] !== 'complete') {
            $previous['phase']='complete'; $previous['object']=['uuid'=>$uuid,'values'=>$values]; wifiWrite($record, $previous); $changed=true;
        }
        wifiEnsure($previous['phase'] === 'complete', 'Wi-Fi apply was interrupted');
    }
    echo json_encode(['changed'=>$changed,'rule'=>$values,'reload_required'=>$reload,'runtime_ready'=>$runtime,'mtu'=>$wg['input']['mtu'],'backup'=>$previous['backup'] ?? null,'phase'=>$previous['phase'] ?? 'unconfigured'], JSON_THROW_ON_ERROR)."\n";
} catch (Throwable $error) { fwrite(STDERR, $error->getMessage()."\n"); exit(1); }
