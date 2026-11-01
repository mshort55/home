// Shared ownership and model helpers. Legacy record names/UUID salt are stable persisted identities.
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
    // UniFi v1 records own an allocation, not UUIDs. Reconstruct the same bounded
    // policy as its configure/verify adapter, then retain each unique exact match.
    global $seed;
    $unifiPolicy = labCompletedUnifiPolicy(\OPNsense\Core\Config::getInstance()->object(), $seed);
    foreach ($unifiPolicy[$label] ?? [] as $values) {
        $identity = $values[$field];
        requireCondition(isset($existing[$identity]), 'Missing or conflicting owned UniFi ' . $label);
        requireCondition(labSame($existing[$identity]['values'], $values), 'Owned UniFi policy drift; run its controller network workflow');
        $retained[$existing[$identity]['uuid']] = $existing[$identity]['values'];
        unset($existing[$identity]);
    }
    $unmanaged = [];
    foreach ($existing as $identity => $object) { $unmanaged[] = $identity . ' (UUID ' . $object['uuid'] . ')'; }
    requireCondition(count($existing) === 0, 'Unmanaged ' . $label . ' entry requires separate review: ' . implode(', ', $unmanaged));
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


function configureWanPolicy(\SimpleXMLElement $wan, array $input, array &$changes): void
{
    // WAN policy is explicit desired state; omission preserves the existing setting.
    foreach (['wan_block_private'=>'blockpriv', 'wan_block_bogons'=>'blockbogons'] as $option=>$field) {
        if (array_key_exists($option, $input)) {
            requireCondition(is_bool($input[$option]), 'WAN policy settings must be booleans');
            if ($input[$option]) { setValue($wan, $field, '1', $changes); }
            else { removeValue($wan, $field, $changes); }
        }
    }

}
