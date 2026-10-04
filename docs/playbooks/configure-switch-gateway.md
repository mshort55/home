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
