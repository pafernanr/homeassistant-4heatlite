# Proxy Modes

The 4HEAT Lite module's local TCP API is **read-only** — write commands (temperature changes, ON/OFF) are only accepted via cloud polling. The integration includes an embedded HTTP proxy that intercepts the module's cloud traffic and injects local commands, using Home Assistant's native `HomeAssistantView` pattern. No extra processes or ports on the HA side.

## Architecture

```
                    ┌──────────────┐
                    │  Lasian App   │ (cloud_sync mode only)
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Azure Cloud  │ (bypassed in local_only mode)
                    └──────▲───────┘
                           │ forwarded (cloud_sync only)
┌─────────┐  RS485    ┌───┴───────────┐  HTTP     ┌──────────────────────┐
│  Stove  │◄─────────►│ 4HEAT Module  │◄─────────►│  HA (port 8123)      │
│         │  Tiemme   │               │ DNAT:80   │  HomeAssistantView   │
└─────────┘           └───────────────┘           │  proxy endpoints     │
                                                  └──────────────────────┘
```

The module connects to what it thinks is `wifi4heat-linux.azurewebsites.net:80` (Azure cloud). A DNS override on the router resolves this hostname to the router's LAN IP, and a firewall DNAT rule redirects the traffic to Home Assistant.

## Modes

### `local_only` (default)

- Module traffic is intercepted and handled locally by HA.
- Commands from HA are queued and delivered to the module when it polls.
- **No data is forwarded to Azure** — the Lasian/4HEAT mobile app will show the device as offline and will NOT work over mobile data.
- The mobile app still works over WiFi (it connects directly to the module via TCP, bypassing the cloud entirely).

### `cloud_sync`

- Same local interception as `local_only`, plus all module traffic is **forwarded to Azure** in real-time.
- Commands from both HA and the Lasian app are merged — the module receives commands from both sources.
- The mobile app works both on WiFi and mobile data.
- Azure shows the device as online (`IsOnline: true`).

#### Cloud Forwarding Details

In `cloud_sync` mode, the proxy forwards traffic to Azure's real IP (`20.105.232.8`) with a `Host: wifi4heat-linux.azurewebsites.net` header, bypassing the DNS hijack for outbound requests.

| Module Request | Proxy Action |
|----------------|-------------|
| `POST /api/devices/register` | Forward to Azure, receive real DeviceKey |
| `GET /api/devices/commands` | Return local queue + fetch and merge Azure commands |
| `GET /api/Devices/timeAlign` | Forward to Azure for clock sync |
| `POST /api/devices/store` | Parse sensor data locally, forward to Azure |
| `POST /api/devices/cron` | Forward to Azure |

#### DeviceKey

The DeviceKey is a fixed UUID assigned by Azure to each module. It is required in `/store` requests — Azure silently ignores stores with an incorrect key (returns 200 OK but does not update).

During setup, the integration authenticates with the 4HEAT cloud using your account credentials (same as the mobile app) and retrieves the DeviceKey from the device details. Credentials are used once and **not stored** — only the DeviceKey is persisted in the config entry.

## Network Setup (OpenWrt)

The module connects to `wifi4heat-linux.azurewebsites.net` on port 80 (HTTP). To redirect this traffic to HA, you need a DNS override and a firewall DNAT rule on your router. The DNAT target depends on whether HA listens on HTTP or HTTPS.

### Step 1: DNS Override

Resolve the cloud hostname to your router's LAN IP:

```bash
uci add_list dhcp.@dnsmasq[0].address='/wifi4heat-linux.azurewebsites.net/<ROUTER_IP>'
uci commit dhcp
/etc/init.d/dnsmasq restart
```

### Step 2: Firewall DNAT

Choose the scenario that matches your HA setup:

#### Scenario A — HA listens on HTTP (default)

If `http:` in `configuration.yaml` has no `ssl_certificate` configured and no SSL proxy add-on is active, HA accepts plain HTTP on port 8123. DNAT directly to HA:

```bash
uci add firewall redirect
uci set firewall.@redirect[-1].name='4heat-proxy'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].src_ip='<MODULE_IP>'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='<HA_IP>'
uci set firewall.@redirect[-1].dest_port='8123'
uci set firewall.@redirect[-1].proto='tcp'
uci set firewall.@redirect[-1].target='DNAT'
uci commit firewall
/etc/init.d/firewall restart
```

#### Scenario B — HA listens on HTTPS

If HA uses TLS (e.g., via `ssl_certificate`, the Let's Encrypt add-on, or the NGINX SSL proxy add-on), the module cannot connect directly — it speaks plain HTTP only. Use [stunnel](https://www.stunnel.org/) on the router as a TLS wrapper:

```bash
# Install stunnel
apk add stunnel   # OpenWrt 25.x+
# opkg install stunnel  # older OpenWrt

# Configure stunnel as a TLS client
cat > /etc/stunnel/4heat.conf << 'EOF'
pid = /var/run/stunnel-4heat.pid
[4heat-proxy]
client = yes
accept = 8180
connect = <HA_IP>:8123
verifyChain = no
EOF

# Enable and start
/etc/init.d/stunnel enable
/etc/init.d/stunnel start
```

stunnel accepts plain HTTP on port 8180 and wraps it in TLS before forwarding to HA:8123. Then DNAT to stunnel instead of HA directly:

```bash
uci add firewall redirect
uci set firewall.@redirect[-1].name='4heat-proxy'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].src_ip='<MODULE_IP>'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='<ROUTER_IP>'
uci set firewall.@redirect[-1].dest_port='8180'
uci set firewall.@redirect[-1].proto='tcp'
uci set firewall.@redirect[-1].target='DNAT'
uci commit firewall
/etc/init.d/firewall restart
```

Replace `<MODULE_IP>` with your module's IP, `<ROUTER_IP>` with your router's LAN IP, and `<HA_IP>` with your Home Assistant server's IP.

> **Note**: LAN-to-LAN DNAT (hairpin NAT) may require an additional masquerade rule on some OpenWrt configurations.

### Multiple Modules

To proxy multiple stoves, add one DNAT rule per module (different `src_ip`, same destination). The proxy routes requests to the correct stove entry using the device ID from the module's requests.

### How to Check if HA Uses HTTP or HTTPS

```bash
# From a machine on the same LAN:
curl -v http://<HA_IP>:8123/ 2>&1 | head -15
```

- If you get an HTML response: HA uses **HTTP** (Scenario A).
- If you get `Empty reply from server` or a TLS error: HA uses **HTTPS** (Scenario B).

## Reverting to Cloud

To restore full cloud connectivity, remove the DNS override and firewall redirect:

```bash
uci del_list dhcp.@dnsmasq[0].address='/wifi4heat-linux.azurewebsites.net/<ROUTER_IP>'
uci commit dhcp
/etc/init.d/dnsmasq restart

# Remove the firewall redirect (find its index with: uci show firewall | grep 4heat)
uci delete firewall.@redirect[N]
uci commit firewall
/etc/init.d/firewall restart
```

The module will reconnect to Azure within ~60 seconds.

## Module Firmware Behavior

The module (ESP32, ESP-IDF firmware) follows a strict request sequence each polling cycle:

1. `POST /api/devices/register` — only on boot, receives DeviceKey
2. `GET /api/devices/commands?id=<ID>&removefromserver=true` — polls every ~60s
3. `GET /api/Devices/timeAlign?deviceKey=<KEY>` — clock sync after each commands poll
4. `POST /api/devices/store` — sends sensor data on value change and periodically (~15 min keepalive)
5. `POST /api/devices/cron` — sends schedule data periodically

**Important**: If any step returns an error (e.g., 404 for timeAlign), the module may stop progressing through the sequence. All proxy endpoints must return valid responses.

The module maintains a single persistent TCP connection (HTTP keep-alive) to the server for all requests.
