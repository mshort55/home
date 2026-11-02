<?php
declare(strict_types=1);
eval(file_get_contents(dirname(__DIR__,2).'/scripts/opnsense-dhcp-library.php'));
$input=json_decode(file_get_contents(dirname(__DIR__).'/fixtures/opnsense-dhcp.json'),true,512,JSON_THROW_ON_ERROR);
$rendered=file_get_contents(dirname(__DIR__).'/fixtures/dnsmasq.conf');
$cases=0;
function check(bool $ok): void { global $cases; if (!$ok) { throw new RuntimeException('DHCP regression failed'); } $cases++; }
function rejects(callable $call): void { global $cases; try { $call(); } catch (RuntimeException $error) { $cases++; return; } throw new RuntimeException('Expected DHCP refusal'); }
$current=['enable'=>'0','hosts'=>[],'dhcp_ranges'=>[]];
dhcpOwnership($current,null,'seed'); check(true);
rejects(fn()=>dhcpOwnership(['enable'=>'1'],null,'seed'));
foreach (['hosts','domainoverrides','dhcp_tags','dhcp_ranges','dhcp_options','dhcp_boot'] as $key) {
    rejects(fn()=>dhcpOwnership(array_replace($current,[$key=>['foreign'=>[]]]),null,'seed'));
}
$record=['version'=>1,'seed_id'=>'seed','phase'=>'complete','model_sha256'=>dhcpHash($current)];
dhcpOwnership($current,$record,'seed'); check(true);
rejects(fn()=>dhcpOwnership($current,$record,'other'));
rejects(fn()=>dhcpOwnership(['enable'=>'1'],$record,'seed'));
rejects(fn()=>dhcpOwnership($current,array_replace($record,['phase'=>'unknown']),'seed'));
$pending=array_replace($record,['phase'=>'pending','previous_sha256'=>dhcpHash(['enable'=>'1'])]);
dhcpOwnership(['enable'=>'1'],$pending,'seed'); check(true);
dhcpOwnership($current,$pending,'seed'); check(true);
check(dhcpHash(['b'=>['y'=>'2','x'=>'1'],'a'=>'0','dns_port'=>'53']) === dhcpHash(['a'=>'0','b'=>['x'=>'1','y'=>'2'],'dns_port'=>'0']));
dhcpCheckRendered($rendered,$input,'dhcp-server'); check(true);
foreach (['port=0'=>'port=53','interface=dhcp-server'=>'interface=eth0','192.0.2.134'=>'192.0.2.248','id:*,02:00:00:00:00:01'=>'id:*,02:00:00:00:00:02','dhcp-lease-max=115'=>'dhcp-lease-max=200','tag:dhcp-server,6,192.0.2.254'=>'tag:dhcp-server,6,8.8.8.8'] as $from=>$to) {
    rejects(fn()=>dhcpCheckRendered(str_replace($from,$to,$rendered),$input,'dhcp-server'));
}
foreach (['enable-ra','enable-tftp','dhcp-range=192.0.2.135,192.0.2.248,3600','dhcp-option-force=6,8.8.8.8','dhcp-hostsfile=/tmp/foreign','conf-file=/tmp/foreign','dhcp-relay=192.0.2.1','no-dhcp-interface=dhcp-server'] as $extra) {
    rejects(fn()=>dhcpCheckRendered($rendered."\n".$extra,$input,'dhcp-server'));
}
$future=(string)(time()+3600);
dhcpCheckLeases([$future.' 02:00:00:00:00:01 192.0.2.116 printer *', $future.' 02:00:00:00:00:02 192.0.2.20 client *'],$input); check(true);
foreach ([$future,'0'] as $expiry) {
    rejects(fn()=>dhcpCheckLeases([$expiry.' 02:00:00:00:00:02 192.0.2.116 client *'],$input));
    rejects(fn()=>dhcpCheckLeases([$expiry.' 02:00:00:00:00:02 192.0.2.135 client *'],$input));
}
dhcpCheckLeases(['1 02:00:00:00:00:02 192.0.2.135 expired *'],$input); check(true);
$explicit=$input;
$explicit['settings']['ranges']=$input['allocation']['primary']['ranges'];
check(dhcpIntentHash($explicit)===dhcpIntentHash($input));
$explicit['model']['dhcp_ranges'][array_key_first($explicit['model']['dhcp_ranges'])]['end_addr']='192.0.2.109';
check(dhcpIntentHash($explicit)!==dhcpIntentHash($input));
echo 'DHCP ownership/runtime checks passed: '.$cases."\n";
