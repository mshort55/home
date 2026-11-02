<?php
declare(strict_types=1);

// Exercise the actual PHP collection guard with synthetic vendor models and
// protected fixtures. No device, network, or external process is involved.
namespace OPNsense\Base\FieldTypes {
    class Node {
        public function __construct(public array $values) {}
        public function getNodeContent(): array { return $this->values; }
        public function setNodes(array $values): void { $this->values=$values; }
    }
    class ArrayField {
        public array $nodes=[];
        public int $deletions=0;
        public function __construct(array $values) {
            foreach ($values as $uuid=>$value) { $this->nodes[$uuid]=new Node($value); }
        }
        public function iterateItems(): array { return $this->nodes; }
        public function del(string $uuid): void { unset($this->nodes[$uuid]); $this->deletions++; }
        public function add(string $uuid): Node { return $this->nodes[$uuid]=new Node([]); }
    }
}
namespace OPNsense\Core {
    class Config {
        public static \SimpleXMLElement $xml;
        public static function getInstance(): self { return new self(); }
        public function object(): \SimpleXMLElement { return self::$xml; }
    }
}
namespace {
    if (!class_exists(\SimpleXMLElement::class)) {
        fwrite(STDERR, "PHP validation requires SimpleXML. On Ubuntu/Debian install php-cli and php-xml, then rerun validation.\n");
        exit(1);
    }
    function check(bool $condition, string $message): void {
        if (!$condition) { throw new \RuntimeException($message); }
    }
    function fixture(string $path, array $value): void {
        file_put_contents($path,json_encode($value,JSON_THROW_ON_ERROR)); chmod($path,0600);
    }
    function exercise(array $entries, string $label='filter rules', ?string $failure=null): void {
        global $cases;
        $container=new \OPNsense\Base\FieldTypes\ArrayField($entries);
        $desired=[]; $changes=[];
        try {
            collection($container,$desired,$label,$changes);
            check($failure === null,'Expected refusal: '.$failure);
            $actual=[];
            foreach ($container->iterateItems() as $uuid=>$node) { $actual[$uuid]=$node->getNodeContent(); }
            ksort($actual); ksort($entries);
            check($actual === $entries,'Owned UUIDs or vendor fields changed');
            check($desired === [] && $changes === [],'Retention changed service policy');
        } catch (\RuntimeException $error) {
            if ($failure === null || !str_contains($error->getMessage(),$failure)) { throw $error; }
            check($container->deletions === 0,'Refusal mutated the candidate collection');
        }
        $cases++;
    }
    $root=dirname(__DIR__,2);
    $directory=tempnam(sys_get_temp_dir(),'services-ownership-');
    check($directory !== false,'Cannot allocate test directory'); unlink($directory); mkdir($directory,0700);
    try {
        foreach (['ansible-unifi','ansible-wireguard','ansible-lab'] as $name) { mkdir($directory.'/'.$name,0700); }
        $library=file_get_contents($root.'/scripts/opnsense-lab-library.php');
        $services=file_get_contents($root.'/scripts/configure-opnsense-services.php');
        $services=explode("\ntry {\n    \$mode",$services)[0];
        $services=str_replace(["<?php", "declare(strict_types=1);", "require_once('config.inc');", '// LAB_EXTENSION_LIBRARY', '// SERVICES_LIBRARY', '// DHCP_LIBRARY'],['','','',$library,file_get_contents($root.'/scripts/opnsense-services-library.php'),file_get_contents($root.'/scripts/opnsense-dhcp-library.php')],$services);
        // Root owns real artifacts; the invoking user owns these temporary fixtures.
        $services=str_replace(['\'/conf/','fileowner($path) === 0'],['\''.$directory.'/','fileowner($path) === '.posix_geteuid()],$services);
        eval($services);
        $seed=['seed_id'=>'synthetic-seed','address'=>'10.77.10.254']; $cases=0;
        // The reusable helper must preserve omitted WAN policy, enforce explicit
        // booleans and converge without disturbing unrelated interface fields.
        $wan=new \SimpleXMLElement('<wan><if>vtnet0</if><blockpriv>1</blockpriv><blockbogons>1</blockbogons></wan>');
        $changes=[];
        configureWanPolicy($wan, [], $changes);
        check(isset($wan->blockpriv, $wan->blockbogons) && $changes === [], 'Omitted WAN policy changed configuration'); $cases++;
        configureWanPolicy($wan, ['wan_block_private'=>false,'wan_block_bogons'=>false], $changes);
        check(!isset($wan->blockpriv) && !isset($wan->blockbogons) && (string)$wan->if === 'vtnet0', 'Explicit WAN policy failed'); $cases++;
        $changes=[];
        configureWanPolicy($wan, ['wan_block_private'=>false,'wan_block_bogons'=>false], $changes);
        check($changes === [], 'WAN policy did not converge'); $cases++;
        configureWanPolicy($wan, ['wan_block_private'=>true,'wan_block_bogons'=>true], $changes);
        check((string)$wan->blockpriv === '1' && (string)$wan->blockbogons === '1', 'WAN blocking could not be enabled'); $cases++;
        foreach (['false', 0, null] as $invalid) {
            try {
                configureWanPolicy($wan, ['wan_block_private'=>$invalid], $changes);
                throw new \RuntimeException('Expected invalid WAN policy refusal');
            } catch (\RuntimeException $error) {
                check(str_contains($error->getMessage(), 'must be booleans'), 'Invalid WAN policy accepted');
            }
            $cases++;
        }
        $home=['address'=>'10.77.200.254','subnet'=>'10.77.200.0/24','pool_start'=>'10.77.200.100','pool_end'=>'10.77.200.199','lease_seconds'=>3600];
        foreach (['', '192.0.2.1', '10.77.55.254'] as $gateway) {
            check(homeSettings($home, '10.77.10.', $gateway) === $home, 'Optional/public/private WAN gateway rejected'); $cases++;
        }
        $finalHome=['address'=>'10.77.55.254','subnet'=>'10.77.55.0/24','dhcp_backend'=>'dnsmasq'];
        check(homeSettings($finalHome, '10.77.10.', '') === $finalHome, 'Final HOME without legacy pool fields rejected'); $cases++;
        foreach (['dhcp_backend'=>'kea','subnet'=>'10.77.88.0/24','address'=>'10.77.55.255'] as $key=>$value) {
            $bad=$finalHome; $bad[$key]=$value; $refused=false;
            try { homeSettings($bad,'10.77.10.',''); } catch (\RuntimeException $error) { $refused=true; }
            check($refused, 'Invalid final HOME accepted'); $cases++;
        }
        \OPNsense\Core\Config::$xml=new \SimpleXMLElement('<opnsense><interfaces><lan><ipaddr>10.77.10.254</ipaddr></lan></interfaces><system><domain>lab.home.arpa</domain></system></opnsense>');
        $input=['vmid'=>110,'name'=>'unifi01','vlan'=>10,'address'=>'10.77.10.20/24','gateway'=>'10.77.10.254','recovery_address'=>'10.77.10.250','tunnel_address'=>'10.77.99.2','domain'=>'lab.home.arpa'];
        $path=$directory.'/ansible-unifi/state.json'; $backup=$directory.'/ansible-unifi/before.xml';
        file_put_contents($backup,'synthetic backup'); chmod($backup,0600);
        $record=['version'=>1,'phase'=>'complete','seed_id'=>$seed['seed_id'],'input'=>$input,'backup'=>$backup];
        $wg=['version'=>1,'phase'=>'complete','seed_id'=>$seed['seed_id'],'input'=>['settings'=>['peer_address'=>$input['tunnel_address']]],'objects'=>[]];
        fixture($directory.'/ansible-wireguard/state.json',$wg);
        $policy=labUnifiPolicy($input); $rules=[];
        foreach ($policy['filter rules'] as $index=>$values) { $rules['synthetic-uuid-'.$index]=$values+['vendor_default'=>'preserved']; }
        $hosts=['synthetic-host-uuid'=>$policy['DNS host records'][0]+['vendor_default'=>'preserved']];
        exercise($rules,'filter rules','Unmanaged filter rules');
        fixture($path,$record);
        exercise($rules); exercise($hosts,'DNS host records');
        exercise([],'DNS access lists'); exercise([],'DHCP subnets');
        foreach (array_keys($policy['filter rules'][0]) as $field) {
            $drift=$rules; $drift['synthetic-uuid-0'][$field]='drift';
            exercise($drift,'filter rules',$field === 'description' ? 'Missing or conflicting owned UniFi' : 'Owned UniFi policy drift');
        }
        foreach (array_keys($policy['DNS host records'][0]) as $field) {
            $drift=$hosts; $drift['synthetic-host-uuid'][$field]='drift';
            exercise($drift,'DNS host records',$field === 'hostname' ? 'Missing or conflicting owned UniFi' : 'Owned UniFi policy drift');
        }
        $missing=$rules; unset($missing['synthetic-uuid-0']);
        exercise($missing,'filter rules','Missing or conflicting owned UniFi');
        exercise($rules+['duplicate'=>$rules['synthetic-uuid-0']],'filter rules','Duplicate filter rules identity');
        $extra=$rules; $extra['spoof']=$rules['synthetic-uuid-0']; $extra['spoof']['description']='Home automation: UNIFI arbitrary allow';
        exercise($extra,'filter rules','arbitrary allow (UUID spoof)');
        foreach (['phase'=>'pending','seed_id'=>'other-seed','version'=>2] as $field=>$value) {
            fixture($path,array_replace($record,[$field=>$value]));
            exercise($rules,'filter rules','Complete or reconcile');
        }
        foreach (['vmid'=>111,'name'=>'other','vlan'=>20,'address'=>'10.77.10.21/24','gateway'=>'10.77.10.253','recovery_address'=>'10.77.10.251','domain'=>'other.home.arpa','tunnel_address'=>'10.77.99.3'] as $field=>$value) {
            $drift=$record; $drift['input'][$field]=$value; fixture($path,$drift);
            exercise($rules,'filter rules','conflicts');
        }
        fixture($path,array_replace($record,['backup'=>$directory.'/missing.xml']));
        exercise($rules,'filter rules','Missing original UniFi policy backup');
        fixture($path,$record); chmod($path,0644); clearstatcache();
        exercise($rules,'filter rules','Unprotected lab artifact'); chmod($path,0600); clearstatcache();
        rename($path,$path.'.real'); symlink($path.'.real',$path);
        exercise($rules,'filter rules','Symlink lab artifact'); unlink($path); rename($path.'.real',$path);
        chmod($backup,0644); clearstatcache(); exercise($rules,'filter rules','Unprotected lab artifact'); chmod($backup,0600); clearstatcache();
        // Existing UUID-owned workflows continue to retain their exact entries.
        $combined=$rules;
        foreach (['wireguard','dev','bmc'] as $name) {
            $values=['description'=>'Synthetic '.$name,'enabled'=>'1']; $uuid='synthetic-'.$name;
            $combined[$uuid]=$values;
            $other=$wg; $other['objects']=['filter rules'=>[['uuid'=>$uuid,'values'=>$values]]];
            fixture($name === 'wireguard' ? $directory.'/ansible-wireguard/state.json' : $directory.'/ansible-lab/'.$name.'.json',$other);
        }
        exercise($combined);
        echo 'Service ownership regression checks passed: '.$cases."\n";
    } finally {
        foreach (glob($directory.'/*') as $child) {
            foreach (glob($child.'/*') as $file) { unlink($file); }
            rmdir($child);
        }
        rmdir($directory);
    }
}
