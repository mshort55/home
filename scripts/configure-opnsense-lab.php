<?php
declare(strict_types=1);
require_once('config.inc');
// LAB_EXTENSION_LIBRARY

function labAddress(string $address): string
{
    labEnsure(filter_var($address,FILTER_VALIDATE_IP,FILTER_FLAG_IPV4) !== false && str_starts_with($address,'10.'), 'Lab addresses must be private IPv4 hosts');
    $prefix=substr($address,0,strrpos($address,'.')+1);
    labEnsure(!in_array(substr($address,strlen($prefix)),['0','255'],true), 'Invalid lab host address');
    return $prefix;
}
function labRule(string $zone, string $name, int $sequence, string $interface, string $source, string $destination, string $protocol, string $port='', string $action='pass', bool $enabled=true): array
{
    return ['enabled'=>$enabled ? '1' : '0','description'=>'Home automation: LAB '.strtoupper($zone).' '.$name,'sequence'=>(string)$sequence,'quick'=>'1','action'=>$action,'interface'=>$interface,'interfacenot'=>'0','direction'=>'in','ipprotocol'=>'inet','protocol'=>$protocol,'source_not'=>'0','source_net'=>$source,'source_port'=>'','destination_not'=>'0','destination_net'=>$destination,'destination_port'=>$port,'gateway'=>'','replyto'=>'','disablereplyto'=>'0','statetype'=>'keep','log'=>$action === 'block' ? '1' : '0'];
}
function labLoadedRule(string $loaded, array $object, string $device): bool
{
    $lines=array_values(array_filter(explode("\n",$loaded),static fn(string $line): bool => str_contains($line,'label "'.$object['uuid'].'"')));
    if (count($lines) !== 1) { return false; }
    $line=$lines[0]; $values=$object['values'];
    if (!str_starts_with($line,$values['action'].' ') || !str_contains($line,' quick on '.$device.' inet ')) { return false; }
    $all=$values['source_net'] === 'any' && $values['destination_net'] === 'any' && preg_match('/\binet all(?=\s|$)/',$line) === 1;
    foreach (['source_net'=>'from','destination_net'=>'to'] as $field=>$word) {
        if ($all) { continue; }
        // The vendor expands its self alias; its exact saved alias is checked separately.
        if ($values[$field] === '(self)') { continue; }
        $address=preg_replace('/\/32$/','',$values[$field]);
        if (preg_match('/\b'.$word.' '.preg_quote($address,'/').'(?=\s|$)/',$line) !== 1) { return false; }
    }
    if ($values['protocol'] !== 'any' && !str_contains($line,' proto '.strtolower($values['protocol']).' ')) { return false; }
    if ($values['destination_port'] !== '') {
        $port=$values['destination_port']; $service=getservbyport((int)$port,strtolower($values['protocol']));
        $names=array_filter([$port,$service]);
        if (preg_match('/\bport = (?:'.implode('|',array_map(static fn(string $name): string => preg_quote($name,'/'),$names)).')(?=\s|$)/',$line) !== 1) { return false; }
    }
    return true;
}
function labPolicyReady(string $loaded, array $objects, string $section, string $device, bool $enabled, bool $interfaceEnabled): bool
{
    foreach ($objects as $object) {
        if ($object['uuid'] === '') { return false; }
        $present=str_contains($loaded,$object['uuid']);
        if (!$enabled) { if ($present) { return false; } continue; }
        // OPNsense omits native rules for a disabled interface. Tunnel rules must
        // already be loaded; all native rules are required after activation.
        if (!$present && !$interfaceEnabled && $object['values']['interface'] === $section) { continue; }
        $ruleDevice=$object['values']['interface'] === 'opt4' ? 'wg0' : $device;
        if (!labLoadedRule($loaded,$object,$ruleDevice)) { return false; }
    }
    return true;
}
function labDnsHost(string $address, string $hostname, string $expected, bool $ready): bool
{
    if (!$ready) { return false; }
    // Raw SSH can combine stderr with stdout. Keep probe failures inside the
    // runtime result and bound queries to unavailable listeners.
    $answer=shell_exec('/usr/bin/timeout 5 /usr/local/bin/drill -Q @'.escapeshellarg($address).' '.escapeshellarg($hostname).' A 2>/dev/null') ?? '';
    return trim($answer) === $expected;
}
function labOutboundNat(string $loaded, string $subnet, string $device, string $wanDevice): bool
{
    // Automatic NAT may use a dynamic interface network instead of a literal CIDR.
    // Require the general egress rule; an IKE-only static-port rule is insufficient.
    $source='(?:'.preg_quote($subnet,'/').'|\('.preg_quote($device,'/').':network\))';
    $wan=preg_quote($wanDevice,'/');
    return preg_match('/^nat on '.$wan.' inet from '.$source.' to any -> \('.$wan.':0\)(?=\s|$)/m',$loaded) === 1;
}
function labRuntime(array $input, array $interface, array $objects): array
{
    $info=shell_exec('/sbin/ifconfig '.escapeshellarg($interface['if']).' 2>/dev/null') ?? '';
    $loaded=shell_exec('/sbin/pfctl -sr 2>/dev/null') ?? '';
    $dns=shell_exec('/usr/local/sbin/unbound-checkconf -o interface /var/unbound/unbound.conf 2>/dev/null') ?? '';
    $acls=shell_exec('/usr/local/sbin/unbound-checkconf -o access-control /var/unbound/unbound.conf 2>/dev/null') ?? '';
    $hasAddress=preg_match('/\binet '.preg_quote($input['settings']['address'],'/').' netmask 0xffffff00\b/',$info) === 1;
    $checks=['interface'=>$hasAddress === $input['enabled'],'firewall_rules'=>true,'dns_listener'=>str_contains($dns,$input['settings']['address']) === $input['enabled'],'dns_acl'=>preg_match('/^'.preg_quote($input['settings']['subnet'],'/').'\s+allow\s*$/m',$acls) === ($input['enabled'] ? 1 : 0),'ntp'=>trim(shell_exec('/usr/bin/pgrep -x ntpd') ?? '') !== ''];
    foreach ($objects['filter rules'] as $object) {
        if ($object['uuid'] === '' || str_contains($loaded,$object['uuid']) !== $input['enabled']) { $checks['firewall_rules']=false; }
        if ($input['enabled'] && !labLoadedRule($loaded,$object,$object['values']['interface'] === 'opt4' ? 'wg0' : $interface['if'])) { $checks['firewall_rules']=false; }
    }
    if ($input['enabled'] && $input['zone'] === 'dev') {
        $nat=shell_exec('/sbin/pfctl -sn 2>/dev/null') ?? '';
        $checks['outbound_nat']=labOutboundNat($nat,$input['settings']['subnet'],$interface['if'],$input['wan_device']);
        $checks['dns_host']=labDnsHost($input['settings']['address'],$input['settings']['hostname'].'.'.$input['domain'],$input['settings']['target'],$hasAddress && $checks['dns_listener']);
    }
    return $checks;
}

try {
    labEnsure(count($argv) === 3 && in_array($argv[1],['plan','stage','activate','complete','verify','routes'],true), 'Unknown lab operation');
    $operation=$argv[1]; $input=json_decode(base64_decode($argv[2],true),true,512,JSON_THROW_ON_ERROR);
    $config=\OPNsense\Core\Config::getInstance();
    // lock() reloads the XML; acquire it before retaining references or validating
    // the saved policy that activation will update.
    if (in_array($operation,['stage','activate','complete'],true)) { $config->lock(); }
    $xml=$config->object(); $seed=json_decode(file_get_contents('/conf/ansible-install.json'),true,512,JSON_THROW_ON_ERROR);
    if ($operation === 'routes') {
        $records=labRecords($xml,$seed); $routes=[];
        foreach ($records as $record) { if ($record['enabled']) { $routes[]=$record['input']['settings']['subnet']; } }
        echo json_encode(['routes'=>$routes],JSON_THROW_ON_ERROR)."\n"; exit(0);
    }
    labEnsure(is_array($input) && count($input) === 4 && isset($input['zone'],$input['settings'],$input['wireguard'],$input['enabled']) && is_bool($input['enabled']), 'Invalid lab payload');
    $zone=$input['zone']; labEnsure(in_array($zone,['dev','bmc'],true),'Unknown lab zone');
    $section=$zone === 'dev' ? 'opt2' : 'opt3'; $settings=$input['settings']; $wg=$input['wireguard'];
    $prefix=labAddress($settings['address']); labEnsure($settings['subnet'] === $prefix.'0/24' && labAddress($settings['target']) === $prefix && $settings['target'] !== $settings['address'], 'Invalid lab subnet or target');
    labEnsure(preg_match('/^[a-z][a-z0-9-]{0,62}$/',$settings['hostname']) === 1, 'Invalid lab hostname');
    $records=labRecords($xml,$seed,$zone); $previous=$records[$zone] ?? [];
    $pilot=json_decode(file_get_contents('/conf/ansible-pilot/state.json'),true,512,JSON_THROW_ON_ERROR);
    labEnsure($pilot['phase'] === 'complete' && $pilot['seed_id'] === $seed['seed_id'] && isset($pilot['home_pilot']), 'Complete the HOME pilot first');
    labPrivate('/conf/ansible-wireguard',true); labPrivate('/conf/ansible-wireguard/state.json');
    $wgRecord=json_decode(file_get_contents('/conf/ansible-wireguard/state.json'),true,512,JSON_THROW_ON_ERROR);
    labEnsure($wgRecord['phase'] === 'complete' && $wgRecord['seed_id'] === $seed['seed_id'] && $wgRecord['input']['settings'] === $wg,'Complete the existing WireGuard workflow first');
    labEnsure((string)$xml->interfaces->lan->ipaddr === $wg['management_address'] && (string)$xml->interfaces->opt4->if === 'wg0' && isset($xml->interfaces->opt4->enable), 'Installed administration identity conflicts');
    $blocked=[$wg['management_subnet'],$wg['tunnel_subnet'],$pilot['home_pilot']['subnet']];
    foreach ($records as $key=>$record) { if ($key !== $zone) { $blocked[]=$record['input']['settings']['subnet']; } }
    $wan=shell_exec('/sbin/ifconfig '.escapeshellarg((string)$xml->interfaces->wan->if)) ?? '';
    labEnsure(preg_match('/\binet ([0-9.]+) netmask 0xffffff00\b/',$wan,$match) === 1 && !in_array($settings['subnet'],$blocked,true) && labAddress($match[1]) !== $prefix, 'Lab subnet overlaps an installed network or WAN is unavailable');
    if ($previous !== []) {
        $identity=$previous['input']; unset($identity['enabled']); $candidate=$input; unset($candidate['enabled']);
        labEnsure($identity === $candidate && in_array($previous['phase'],['pending','complete'],true),'Recorded lab allocation conflicts');
        labEnsure(dirname($previous['backup']) === '/conf/ansible-lab' && is_file($previous['backup']), 'Missing lab backup'); labPrivate($previous['backup']);
    } else { labEnsure(!isset($xml->interfaces->{$section}->enable),'Unowned enabled lab interface'); }
    $nic=array_values(array_filter($seed['networks'],static fn(array $nic): bool => $nic['section'] === $section));
    labEnsure(count($nic) === 1 && $nic[0]['role'] === strtoupper($zone),'Seed role mapping conflicts');
    $device=(string)$xml->interfaces->{$section}->if; labEnsure(preg_match('/^vtnet[0-9]+$/',$device) === 1,'Unexpected lab NIC');
    $info=shell_exec('/sbin/ifconfig '.escapeshellarg($device)) ?? '';
    labEnsure(preg_match('/ether\s+([0-9a-f:]+)/i',$info,$mac) === 1 && strtolower($mac[1]) === strtolower($nic[0]['mac']),'Lab NIC MAC conflicts');
    foreach (['gateway','bridge','blockpriv','blockbogons'] as $field) { labEnsure(!isset($xml->interfaces->{$section}->{$field}),'Unexpected lab interface services'); }
    labEnsure(!isset($xml->system->ipv6allow) && !isset($xml->filter->rule) && !isset($xml->nat->rule),'Unexpected IPv6, legacy firewall or NAT');
    $interface=['if'=>$device,'descr'=>strtoupper($zone),'enable'=>$input['enabled'] ? '1' : '','ipaddr'=>$input['enabled'] ? $settings['address'] : 'none','subnet'=>$input['enabled'] ? '24' : '','ipaddrv6'=>'none'];
    $rules=[]; $peer=$wg['peer_address'].'/32'; $enabled=$input['enabled'];
    if ($zone === 'bmc') {
        $rules[]=labRule($zone,'iDRAC HTTPS',700,'opt4',$peer,$settings['target'].'/32','TCP','443','pass',$enabled);
        $rules[]=labRule($zone,'iDRAC ICMP',710,'opt4',$peer,$settings['target'].'/32','ICMP','','pass',$enabled);
    } else {
        $rules[]=labRule($zone,'tunnel firewall deny',720,'opt4','any','(self)','any','','block',$enabled);
        $rules[]=labRule($zone,'workloads',730,'opt4',$peer,$settings['subnet'],'any','','pass',$enabled);
    }
    foreach ([['DNS TCP','TCP','53'],['DNS UDP','UDP','53'],['NTP','UDP','123']] as $offset=>[$name,$protocol,$port]) {
        $rules[]=labRule($zone,$name,100+$offset*10,$section,$settings['subnet'],$settings['address'].'/32',$protocol,$port,'pass',$enabled);
    }
    $rules[]=labRule($zone,'firewall deny',200,$section,'any','(self)','any','','block',$enabled);
    if ($zone === 'dev') {
        // Private, link-local, CGNAT, loopback, multicast and reserved destinations are not internet egress.
        foreach (['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','192.0.0.0/24','192.0.2.0/24','198.18.0.0/15','198.51.100.0/24','203.0.113.0/24','224.0.0.0/4','240.0.0.0/4'] as $offset=>$subnet) {
            $rules[]=labRule($zone,'private deny '.$subnet,220+$offset,$section,'any',$subnet,'any','','block',$enabled);
        }
        $rules[]=labRule($zone,'external DNS TCP deny',280,$section,'any','any','TCP','53','block',$enabled);
        $rules[]=labRule($zone,'external DNS UDP deny',281,$section,'any','any','UDP','53','block',$enabled);
        $rules[]=labRule($zone,'internet',300,$section,$settings['subnet'],'any','any','','pass',$enabled);
    }
    $rules[]=labRule($zone,'default deny',900,$section,'any','any','any','','block',$enabled);
    $acl=['enabled'=>$enabled ? '1' : '0','name'=>'LAB_'.strtoupper($zone),'description'=>'Home automation: LAB '.strtoupper($zone).' DNS ACL','action'=>'allow','networks'=>$settings['subnet']];
    $hosts=$zone === 'dev' ? [['enabled'=>$enabled ? '1' : '0','hostname'=>$settings['hostname'],'domain'=>(string)$xml->system->domain,'rr'=>'A','server'=>$settings['target'],'description'=>'Home automation: LAB DEV DNS host']] : [];
    $filter=new \OPNsense\Firewall\Filter(); $unbound=new \OPNsense\Unbound\Unbound(); $objects=[]; $changes=[];
    foreach (['filter rules'=>[$filter->rules->rule,$rules,'description'],'DNS access lists'=>[$unbound->acls->acl,[$acl],'name'],'DNS host records'=>[$unbound->hosts->host,$hosts,'hostname']] as $label=>[$container,$desired,$identity]) {
        $identities=array_column($desired,$identity);
        labEnsure(count(array_unique($identities)) === count($desired),'Duplicate desired '.$label.' identity');
        $found=[]; foreach ($container->iterateItems() as $uuid=>$node) { $key=(string)$node->{$identity}; labEnsure(!isset($found[$key]),'Duplicate policy identity'); $found[$key]=['uuid'=>$uuid,'values'=>$node->getNodeContent()]; }
        $objects[$label]=[];
        foreach ($desired as $values) {
            $existing=$found[$values[$identity]] ?? null; labEnsure($existing === null || $previous !== [],'Unowned named lab policy');
            $id=$existing['uuid'] ?? '';
            foreach ($previous['objects'][$label] ?? [] as $owned) {
                if ($owned['values'][$identity] === $values[$identity] && $owned['uuid'] !== '') {
                    labEnsure($existing === null || $id === $owned['uuid'], 'Owned lab policy UUID changed');
                }
            }
            if ($existing === null || !labSame($existing['values'],$values)) { $changes[]=$label; }
            $objects[$label][]=['uuid'=>$id,'values'=>$values];
            if ($existing !== null) { $container->del($id); } $container->add($id !== '' ? $id : null)->setNodes($values);
        }
    }
    foreach ($interface as $field=>$value) { if ((string)$xml->interfaces->{$section}->{$field} !== $value) { $changes[]='interface'; } }
    $records[$zone]=['enabled'=>$enabled]; $listeners=array_merge(['lan','opt1'],labListeners($records));
    $ntp=implode(',',array_merge(['lan','wan','opt1'],labListeners($records)));
    if ((string)$xml->ntpd->interface !== $ntp) { $changes[]='NTP listeners'; }
    if ((string)$unbound->general->active_interface !== implode(',',$listeners)) { $changes[]='DNS listeners'; }
    $unbound->general->active_interface=implode(',',$listeners);
    foreach ([$filter,$unbound] as $model) { labEnsure(count($model->performValidation()) === 0,'Vendor model rejected lab policy'); }
    $runtimeInput=$input+['domain'=>(string)$xml->system->domain,'wan_device'=>(string)$xml->interfaces->wan->if]; $checks=labRuntime($runtimeInput,$interface,$objects);
    $reload=count($changes)>0 || in_array(false,$checks,true) || ($previous['phase'] ?? '') !== 'complete' || ($previous['enabled'] ?? null) !== $enabled; $changed=false;
    $path='/conf/ansible-lab/'.$zone.'.json';
    if ($operation === 'stage' && $reload) {
        if (!is_dir('/conf/ansible-lab')) { labEnsure(mkdir('/conf/ansible-lab',0700),'Cannot create lab records'); }
        $backup=$previous['backup'] ?? '/conf/ansible-lab/before-'.$zone.'-'.gmdate('Ymd\THis\Z').'-'.bin2hex(random_bytes(4)).'.xml';
        if (!is_file($backup)) { $file=fopen($backup,'x'); labEnsure($file !== false,'Cannot preserve lab backup'); chmod($backup,0600); fwrite($file,file_get_contents('/conf/config.xml')); fclose($file); }
        $previous=['version'=>1,'seed_id'=>$seed['seed_id'],'input'=>$input,'enabled'=>$enabled,'phase'=>'pending','backup'=>$backup,'interface'=>$interface,'objects'=>$objects];
        labWrite($path,$previous); $changed=true;
    }
    if ($operation === 'activate') {
        labEnsure($previous !== [] && $previous['enabled'] === $enabled,'Stage the lab transaction first');
        // The API policy must already be saved AND loaded before native routing activates.
        labEnsure(!in_array('filter rules',$changes,true),'Save exact lab firewall rules first');
        $loaded=shell_exec('/sbin/pfctl -sr 2>/dev/null') ?? '';
        labEnsure(labPolicyReady($loaded,$objects['filter rules'],$section,$device,$enabled,isset($xml->interfaces->{$section}->enable)), 'Load the scoped firewall policy before interface activation');
        foreach ($interface as $field=>$value) { if ($value === '') { unset($xml->interfaces->{$section}->{$field}); } else { $xml->interfaces->{$section}->{$field}=$value; } }
        $xml->ntpd->interface=$ntp;
        if (in_array('interface',$changes,true) || in_array('NTP listeners',$changes,true)) { $config->save(); $changed=true; }
        $config->unlock();
        if (!$checks['interface']) {
            $output=[]; $status=0; exec('/usr/local/sbin/configctl interface reconfigure '.escapeshellarg($section).' 2>&1',$output,$status);
            labEnsure($status === 0,'Vendor interface activation failed'); $changed=true;
        }
        if (!$enabled) {
            foreach ($objects['filter rules'] as $object) {
                labEnsure(preg_match('/^[0-9a-f-]{36}$/',$object['uuid']) === 1,'Invalid owned rule UUID');
                $output=[]; $status=0;
                exec('/sbin/pfctl -k label -k '.escapeshellarg($object['uuid']).' 2>&1',$output,$status);
                labEnsure($status === 0,'Cannot clear scoped lab connection states');
            }
        }
    }
    if (in_array($operation,['verify','complete'],true)) {
        labEnsure($previous !== [] && count($changes) === 0 && !in_array(false,$checks,true),'Lab reconciliation needed; saved: '.implode(',',array_unique($changes)).'; runtime: '.implode(',',array_keys(array_filter($checks,static fn(bool $ok): bool => !$ok))));
        if ($operation === 'verify') { labEnsure($previous['phase'] === 'complete','Lab apply was interrupted'); }
        if ($operation === 'complete' && $previous['phase'] !== 'complete') { $previous['phase']='complete'; $previous['objects']=$objects; labWrite($path,$previous); $changed=true; }
    }
    echo json_encode(['changed'=>$changed,'enabled'=>$enabled,'changes'=>array_values(array_unique($changes)),'reload_required'=>$reload,'rules'=>$rules,'acl'=>$acl,'hosts'=>$hosts,'listeners'=>$listeners,'section'=>$section,'backup'=>$previous['backup'] ?? null,'runtime_checks'=>$checks],JSON_THROW_ON_ERROR)."\n";
} catch (Throwable $error) { fwrite(STDERR,$error->getMessage()."\n"); exit(1); }
