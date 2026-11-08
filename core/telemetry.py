"""
UNIVA Network - Global Telemetry & Device Monitoring System
============================================================
Tracks active nodes, mobile phones, desktop clients and validators
connected to the UNIVA network in real-time.
"""

import time
import threading
from typing import Dict, List, Any, Optional

class TelemetryManager:
    def __init__(self, timeout_seconds: int = 90):
        self.timeout = timeout_seconds
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.all_time_devices: set = set()
        self.lock = threading.Lock()
        self.start_time = time.time()

    def record_heartbeat(
        self,
        device_id: str,
        ip: str,
        platform: str,
        browser: str = "",
        screen: str = "",
        wallet_address: str = "",
        country: Optional[str] = None,
        city: Optional[str] = None,
        latency_ms: int = 0
    ) -> Dict[str, Any]:
        """Mobil veya bilgisayar cüzdanından gelen heartbeat'i kaydet."""
        now = time.time()
        
        # Cloudflare / Header tabanlı konum çözümleme
        resolved_country = country if country and country != "XX" else "TR"
        resolved_city = city if city and city != "XX" else "İstanbul"
        
        # IP maskeleme (Gizlilik için son okteti gizle: 192.168.1.xxx)
        masked_ip = ip
        if "." in ip:
            parts = ip.split(".")
            if len(parts) == 4:
                masked_ip = f"{parts[0]}.{parts[1]}.{parts[2]}.***"
        elif ":" in ip:
            parts = ip.split(":")
            masked_ip = f"{parts[0]}:{parts[1]}::***"

        with self.lock:
            self.all_time_devices.add(device_id)
            if device_id in self.sessions:
                s = self.sessions[device_id]
                s["last_seen"] = now
                s["latency_ms"] = latency_ms or s.get("latency_ms", 15)
                s["ip"] = masked_ip
                if wallet_address:
                    s["wallet"] = wallet_address
            else:
                self.sessions[device_id] = {
                    "device_id": device_id,
                    "ip": masked_ip,
                    "platform": platform or "Bilinmeyen Cihaz",
                    "browser": browser,
                    "screen": screen,
                    "country": resolved_country,
                    "city": resolved_city,
                    "wallet": wallet_address or "Bağlantılı Cüzdan Yok",
                    "first_seen": now,
                    "last_seen": now,
                    "latency_ms": latency_ms or 15,
                }
            
            # Eski session'ları temizle
            self._cleanup_locked(now)

            return {
                "status": "ok",
                "active_devices": len(self.sessions),
                "total_devices": len(self.all_time_devices),
                "your_device_id": device_id,
                "server_time": now
            }

    def _cleanup_locked(self, now: float):
        dead = [k for k, v in self.sessions.items() if (now - v["last_seen"]) > self.timeout]
        for k in dead:
            del self.sessions[k]

    def get_network_overview(self) -> Dict[str, Any]:
        """Tüm ağın genel telemetri durumunu döndür."""
        now = time.time()
        with self.lock:
            self._cleanup_locked(now)
            active_list = list(self.sessions.values())
            
            # Bölgelere göre dağılım
            regions: Dict[str, int] = {}
            platforms: Dict[str, int] = {}
            for dev in active_list:
                loc_key = f"{dev['country']} - {dev['city']}"
                regions[loc_key] = regions.get(loc_key, 0) + 1
                
                plat = dev.get("platform", "Diğer")
                platforms[plat] = platforms.get(plat, 0) + 1

            uptime_sec = int(now - self.start_time)
            hours, rem = divmod(uptime_sec, 3600)
            minutes, seconds = divmod(rem, 60)
            uptime_str = f"{hours}s {minutes}dk {seconds}sn"

            return {
                "active_device_count": max(1, len(active_list)),
                "total_all_time_devices": max(1, len(self.all_time_devices)),
                "uptime_seconds": uptime_sec,
                "uptime_formatted": uptime_str,
                "regions": regions,
                "platforms": platforms,
                "devices": sorted(
                    active_list,
                    key=lambda x: x["last_seen"],
                    reverse=True
                )[:50],  # En son görülen 50 cihaz
                "server_status": "ONLINE 🟢",
            }

# Global singleton
telemetry = TelemetryManager()
