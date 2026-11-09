# Switch management default gateway

`configure-switch-gateway.yml` invokes `cisco_switch` with the required action `gateway`. It configures only `ip default-gateway` with switch IPv4 routing disabled, allowing replies to routed WireGuard clients. It does not move ports or enable inter-VLAN routing.

Define `switch_management.vlan`, its installed `address` CIDR and `default_gateway`. The gateway must be an ordinary host in the same /24, already responding to a ping sourced from MGMT. The workflow requires an operational SVI, synchronized running/startup configuration, disabled IPv4/IPv6 routing, no static routes and no conflicting gateway.

```bash
ansible-playbook playbooks/configure-switch-gateway.yml --check
ansible-playbook playbooks/configure-switch-gateway.yml
ansible-playbook playbooks/configure-switch-gateway.yml --check
```

Preview reads current state and tests gateway reachability without writes. Apply first collects the normal private switch backup, sets the gateway, verifies it and saves the change. Matching reruns emit no configuration commands; normal runs still collect backups. The named entry requires no variable override.

The bounded gateway ping runs during previews with task-level `check_mode: false`, because `ios_command` otherwise skips commands that do not begin with `show`. The probe always reports unchanged; gateway configuration and saving continue to obey the playbook's check mode. Missing or unsuccessful ping output fails the reachability check before configuration.


## Switch time

`configure-switch-time.yml` uses the same `cisco_switch` role with the explicit
`time` action. It connects to `switch_management.address` on MGMT, derives its NTP
server from `switch_management.default_gateway`, sources NTP from the management
SVI, and verifies the existing UTC timezone without daylight-saving adjustment.
IOS omits default UTC settings from running-config, so timezone verification uses
`show clock detail`. NTP uses the structured `cisco.ios.ios_ntp_global` module.
Existing conflicting NTP or
clock configuration and unrelated unsaved changes stop the action before writes.
Automatic IOS `ntp clock-period` calibration differences are ignored by that guard.
A retry accepts unsaved differences limited to the exact intended time settings
and saves them even if no additional NTP commands are needed. Unrelated unsaved
configuration remains a hard failure. The preview reports `save_required`.

```bash
./just playbook playbooks/configure-switch-time.yml --limit switch01 --check
./just playbook playbooks/configure-switch-time.yml --limit switch01
./just playbook playbooks/configure-switch-time.yml --limit switch01 --check
```

The action backs up running/startup configuration before apply, changes only time
settings, reads them back, and saves them. It then waits up to approximately twenty minutes
for synchronization to the gateway and reports clock/NTP state. Initial IOS
frequency calibration can remain in `FREQ` for about fifteen minutes even with a
valid peer, reach 377 and a small offset. The wait still requires an explicit
`Clock is synchronized` result; successful packet exchange alone does not pass.
See the [NTP clock discipline state machine](https://doc.ntp.org/reflib/brief/flow/flow.pdf).
If initial clock
acquisition takes longer, the saved configuration remains in place; inspect
`show ntp status` and `show ntp associations`, then rerun. Check mode reports current
status without requiring the not-yet-configured NTP service to be synchronized.
A corrected clock will jump forward from its old value, so earlier logs retain
incorrect timestamps. No port/VLAN configuration or reboot is performed.

OPNsense must already serve NTP on MGMT and permit the switch's UDP 123 traffic.
This is allowed by the current MGMT NTP rule. The scoped action is suitable during
the household DHCP hold: it does not replay pre-cutover port declarations.
