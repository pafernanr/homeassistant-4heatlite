"""UDP discovery for 4HEAT Lite WiFi modules."""

import json
import logging
import socket

_LOGGER = logging.getLogger(__name__)

UDP_SEND_PORT = 6666
UDP_RECV_PORT = 5555
UDP_TIMEOUT = 3.0


def _udp_scan(command: str, timeout: float, match_id: str | None = None) -> list[dict]:
    """Send a CF4 UDP broadcast and collect responses."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    results: list[dict] = []
    seen: set[str] = set()
    try:
        sock.bind(("", UDP_RECV_PORT))
        sock.sendto(command.encode(), ("255.255.255.255", UDP_SEND_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                resp = json.loads(data.decode())
                if not isinstance(resp, list) or len(resp) < 5 or resp[0] != "CF4":
                    continue
                device_id = str(resp[2])
                ip = str(resp[4])
                if device_id in seen:
                    continue
                seen.add(device_id)
                if match_id and device_id != match_id:
                    continue
                results.append({"device_id": device_id, "ip": ip})
                if match_id:
                    break
            except socket.timeout:
                break
            except (json.JSONDecodeError, IndexError, UnicodeDecodeError):
                continue
    except OSError as exc:
        _LOGGER.debug("UDP discovery failed: %s", exc)
    finally:
        sock.close()
    return results


def discover_modules(timeout: float = UDP_TIMEOUT) -> list[dict]:
    """Broadcast CF4 and return all responding modules."""
    return _udp_scan('["CF4","0"]', timeout)


def discover_module_by_id(device_id: str, timeout: float = UDP_TIMEOUT) -> str | None:
    """Find a specific module by device_id. Returns its IP or None."""
    results = _udp_scan(f'["CF4","1","{device_id}"]', timeout, match_id=device_id)
    return results[0]["ip"] if results else None
