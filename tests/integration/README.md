# Isolated DHCP packet tests

`dnsmasq-packets.py` exercises real DHCP packets inside a Linux Docker container with no external network. It refuses to run unless the explicit test environment flag is present and the container initially has only loopback. It creates its own veth pair. Never run it on a host network or attach the container to household networks.

The synthetic `192.0.2.0/24` fixture was rendered from the enrolled OPNsense 26.7 Dnsmasq template (model 1.0.9), using `opnsense-dhcp.json` and a synthetic `dhcp-server` interface, then whitespace-normalized. Dnsmasq 2.93 matches that firewall. The test disables ICMP address probing only inside this isolated fixture to avoid waiting on every synthetic client.

Build a local test image from the upstream release. The checksum records the downloaded source used for this test; it is not a separate signature verification. Build dependencies and the Debian image are not pinned, so this is a functional test environment, not a reproducible binary build.

```bash
build_dir=$(mktemp -d)
curl --fail --location https://thekelleys.org.uk/dnsmasq/dnsmasq-2.93.tar.xz -o "$build_dir/dnsmasq-2.93.tar.xz"
(cd "$build_dir" && echo '0c00d4e5c97c8306e5fb932b348b34269c9c29a0e7df0e8e82958b407092bc19  dnsmasq-2.93.tar.xz' | sha256sum --check)
cat > "$build_dir/Dockerfile" <<'DOCKERFILE'
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential iproute2 python3 xz-utils && rm -rf /var/lib/apt/lists/*
COPY dnsmasq-2.93.tar.xz /tmp/
RUN echo '0c00d4e5c97c8306e5fb932b348b34269c9c29a0e7df0e8e82958b407092bc19  /tmp/dnsmasq-2.93.tar.xz' | sha256sum --check && tar -xJf /tmp/dnsmasq-2.93.tar.xz -C /tmp && make -C /tmp/dnsmasq-2.93 -j2 && cp /tmp/dnsmasq-2.93/src/dnsmasq /usr/local/sbin/dnsmasq
DOCKERFILE
docker build -t home-dnsmasq-test:2.93 "$build_dir"
docker run --rm --network none --cap-add NET_ADMIN --cap-add NET_RAW \
  -e HOME_DHCP_PACKET_TEST=1 -v "$PWD:/src:ro" home-dnsmasq-test:2.93 \
  python3 /src/tests/integration/dnsmasq-packets.py
```

The suite exhausts all 114 dynamic addresses, validates DHCP options, reserves and renews the printer, and checks that other clients cannot acquire reserved, standby, excluded or gateway addresses. Optional `--config` and `--plan` select another synthetic fixture; temporary transition fixtures belong outside this repository.

This tests Dnsmasq allocation behavior on Linux. It does not prove FreeBSD service startup, OPNsense firewall rules, physical VLAN isolation, client connectivity or post-apply idempotence on the real firewall. Those require the operator's activation and acceptance checks.
