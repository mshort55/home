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
