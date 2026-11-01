# Validate permanent HOME DHCP allocation

Final desired addresses belong in `all.vars.home_dhcp` in inventory. The public
example declares two equal dynamic pools, an exclusive printer reservation,
excluded addresses and known static addresses. Dnsmasq is the selected primary
DHCP service; Unbound remains the DNS service. Fortinet is manual cold standby.

Validate and render the permanent allocation without contacting devices:

```bash
.venv/bin/python scripts/validate-home-dhcp.py \
  --inventory inventory.private.yml --output .cache/home-dhcp/allocation.json
```

Use `.venv-macos/bin/python` on macOS. Expected primary and standby capacities
are 114 each. Validation rejects overlapping pools, reserved/static/gateway
collisions, invalid ranges and duplicate reservations. The output is mode 0600.
It declares and validates allocation only; it does not configure a DHCP service.

Legacy ranges, lease holds, transition readiness and cutover sequencing are not
part of this input or workflow. They belong in the external operator workspace.
Keep ordinary desired-state applies independent of that workspace.
