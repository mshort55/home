// Injected into the existing SSH adapters by Ansible; no guest-side include path.
function labEnsure(bool $condition, string $message): void
{
    if (!$condition) { throw new RuntimeException($message); }
}
function labPrivate(string $path, bool $directory = false): void
{
    labEnsure(!is_link($path), 'Symlink lab artifact');
    if (file_exists($path)) {
        labEnsure(($directory ? is_dir($path) : is_file($path)) && fileowner($path) === 0 && (fileperms($path) & 0777) === ($directory ? 0700 : 0600), 'Unprotected lab artifact');
    }
}
function labSame(array $actual, array $expected): bool
{
    foreach ($expected as $key=>$value) {
        if (($actual[$key] ?? '') !== $value) { return false; }
    }
    return true;
}
function labUnifiRule(string $name, int $sequence, string $interface, string $source, string $destination, string $port): array
{
    return ['enabled'=>'1','description'=>'Home automation: UNIFI '.$name,'sequence'=>(string)$sequence,'quick'=>'1','action'=>'pass','interface'=>$interface,'interfacenot'=>'0','direction'=>'in','ipprotocol'=>'inet','protocol'=>'TCP','source_not'=>'0','source_net'=>$source.'/32','source_port'=>'','destination_not'=>'0','destination_net'=>$destination,'destination_port'=>$port,'gateway'=>'','replyto'=>'','disablereplyto'=>'0','statetype'=>'keep','log'=>'0'];
}
function labUnifiPolicy(array $input): array
{
    $address=explode('/', $input['address'])[0];
    return [
        'filter rules'=>[labUnifiRule('updates HTTP',131,'lan',$address,'any','80'),labUnifiRule('updates HTTPS',132,'lan',$address,'any','443'),labUnifiRule('tunnel SSH',800,'opt4',$input['tunnel_address'],$address.'/32','22'),labUnifiRule('tunnel HTTPS',810,'opt4',$input['tunnel_address'],$address.'/32','11443')],
        'DNS host records'=>[['enabled'=>'1','hostname'=>$input['name'],'domain'=>$input['domain'],'rr'=>'A','server'=>$address,'description'=>'Home automation: UNIFI DNS host']],
    ];
}
function labCompletedUnifiPolicy(SimpleXMLElement $xml, array $seed): array
{
    $directory='/conf/ansible-unifi'; $path=$directory.'/state.json';
    labPrivate($directory,true); labPrivate($path);
    if (!is_file($path)) { return []; }
    $record=json_decode(file_get_contents($path),true,512,JSON_THROW_ON_ERROR);
    labEnsure(($record['version'] ?? null) === 1 && ($record['seed_id'] ?? null) === $seed['seed_id'] && ($record['phase'] ?? null) === 'complete', 'Complete or reconcile the owned UniFi network workflow first');
    $backup=$record['backup'] ?? '';
    labEnsure(is_string($backup) && dirname($backup) === $directory && is_file($backup), 'Missing original UniFi policy backup');
    labPrivate($backup);
    $input=$record['input'];
    $prefix=substr($seed['address'],0,strrpos($seed['address'],'.')+1);
    labEnsure(str_starts_with($prefix,'10.') && $input['vmid'] === 110 && $input['name'] === 'unifi01' && $input['vlan'] === 10 && $input['address'] === $prefix.'20/24' && $input['recovery_address'] === $prefix.'250' && $input['gateway'] === $seed['address'] && (string)$xml->interfaces->lan->ipaddr === $input['gateway'], 'Recorded UniFi allocation conflicts');
    labEnsure(preg_match('/^[a-z0-9.-]+$/', $input['domain']) === 1 && $input['domain'] === (string)$xml->system->domain, 'Recorded UniFi DNS identity conflicts');
    labPrivate('/conf/ansible-wireguard',true); labPrivate('/conf/ansible-wireguard/state.json');
    $wg=json_decode(file_get_contents('/conf/ansible-wireguard/state.json'),true,512,JSON_THROW_ON_ERROR);
    labEnsure(($wg['version'] ?? null) === 1 && $wg['seed_id'] === $seed['seed_id'] && $wg['phase'] === 'complete' && filter_var($input['tunnel_address'],FILTER_VALIDATE_IP,FILTER_FLAG_IPV4) !== false && $wg['input']['settings']['peer_address'] === $input['tunnel_address'], 'Recorded UniFi WireGuard identity conflicts');
    return labUnifiPolicy($input);
}
function labRecords(SimpleXMLElement $xml, array $seed, ?string $ownZone = null): array
{
    labPrivate('/conf/ansible-lab', true);
    $records=[];
    foreach (['dev'=>'opt2','bmc'=>'opt3'] as $zone=>$section) {
        $path='/conf/ansible-lab/'.$zone.'.json'; labPrivate($path);
        if (!is_file($path)) {
            if ($zone !== $ownZone) { labEnsure(!isset($xml->interfaces->{$section}->enable), 'Unowned enabled '.$zone.' interface'); }
            continue;
        }
        $record=json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
        labEnsure(($record['version'] ?? null) === 1 && $record['seed_id'] === $seed['seed_id'] && $record['input']['zone'] === $zone, 'Lab record identity conflicts');
        if ($zone !== $ownZone) {
            labEnsure($record['phase'] === 'complete', 'Complete the interrupted '.$zone.' lab workflow first');
            if ($record['enabled']) {
                foreach ($record['interface'] as $field=>$value) { labEnsure((string)$xml->interfaces->{$section}->{$field} === $value, 'Owned '.$zone.' interface drift'); }
                foreach (['gateway','bridge','blockpriv','blockbogons'] as $field) { labEnsure(!isset($xml->interfaces->{$section}->{$field}), 'Unexpected owned lab interface service'); }
            } else { labEnsure(!isset($xml->interfaces->{$section}->enable), 'Disabled lab interface is enabled'); }
        }
        $records[$zone]=$record;
    }
    return $records;
}
function labListeners(array $records): array
{
    $result=[];
    foreach (['dev'=>'opt2','bmc'=>'opt3'] as $zone=>$section) {
        if (($records[$zone]['enabled'] ?? false) === true) { $result[]=$section; }
    }
    return $result;
}
function labWrite(string $path, array $value): void
{
    labPrivate($path);
    $temporary=tempnam(dirname($path), '.lab-'); labEnsure($temporary !== false, 'Cannot allocate lab record');
    try {
        chmod($temporary,0600);
        labEnsure(file_put_contents($temporary,json_encode($value,JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT)."\n") !== false, 'Cannot write lab record');
        labEnsure(rename($temporary,$path), 'Cannot replace lab record');
    } finally { if (file_exists($temporary)) { unlink($temporary); } }
}
