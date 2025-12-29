#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from datetime import datetime
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

# ================================
# CONFIG — adjust if needed
# ================================
COMMANDER_IP   = "192.168.45.95"   # Commander IP seen in your last run
COMMANDER_USER = "BW"
COMMANDER_PASS = "Welcome4"        # Your current Commander password
VERIFY_SSL     = False             # Commander typically uses self-signed certs

DATA_DIR   = r"C:\BirdiesData\promotions"
TIMEOUT_S  = 30

# ================================
# LOGGING
# ================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("promos")

# Silence insecure-cert warnings if VERIFY_SSL=False
requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

BASE = f"https://{COMMANDER_IP}"
CGI  = f"{BASE}/cgi-bin/CGILink"
NAX  = f"{BASE}/cgi-bin/NAXML"

# ================================
# Commander credential helpers
# ================================
def get_cookie() -> str:
    """GET a Commander credential cookie."""
    url = f"{CGI}?cmd=validate&user={COMMANDER_USER}&passwd={COMMANDER_PASS}"
    r = requests.get(url, verify=VERIFY_SSL, timeout=TIMEOUT_S)
    r.raise_for_status()
    # Parse <cookie>value</cookie> from XML
    try:
        root = ET.fromstring(r.text)
        cookie_el = root.find(".//cookie")
        if cookie_el is None or not cookie_el.text:
            raise RuntimeError("No <cookie> element in validate response")
        cookie = cookie_el.text.strip()
        log.info("Got Commander cookie")
        return cookie
    except Exception as e:
        raise RuntimeError(f"Failed to parse cookie: {e}")

def release_cookie(cookie: str) -> None:
    """Release Commander credential cookie."""
    try:
        url = f"{CGI}?cmd=releaseCredential&cookie={cookie}"
        r = requests.get(url, verify=VERIFY_SSL, timeout=TIMEOUT_S)
        if r.status_code == 200:
            log.info("Cookie released")
        else:
            log.warning(f"releaseCredential returned HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"Error releasing cookie: {e}")

# ================================
# Fetch helpers
# ================================
def fetch_naxml_maintenance(cookie: str, dataset: str) -> str:
    """
    Pull a NAXML Maintenance dataset (e.g., MixMatch / Combo / ItemList).
    Example endpoint per Verifone URL Reference:
      /cgi-bin/NAXML?cmd=vMaintenance&dataset=MixMatch&cookie=...
    """
    url = f"{NAX}?cmd=vMaintenance&dataset={dataset}&cookie={cookie}"
    r = requests.get(url, verify=VERIFY_SSL, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.text

def save_text(content: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    log.info(f"Saved: {out_path}")

def try_count(elem: ET.Element, name_fragments):
    """
    Best-effort counter for elements whose tag endswith/contains any given fragments.
    NAXML schemas vary by version; we keep this generic.
    """
    count = 0
    for e in elem.iter():
        tag = e.tag.split("}")[-1]  # strip namespace if present
        for frag in name_fragments:
            if tag.lower().endswith(frag.lower()) or frag.lower() in tag.lower():
                count += 1
                break
    return count

# ================================
# Main
# ================================
def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(DATA_DIR) / ts

    log.info("=== Pulling current POS promotions (NAXML Maintenance) ===")
    log.info(f"Commander: {COMMANDER_IP}")

    cookie = get_cookie()
    try:
        # 1) MixMatch definitions
        mixmatch_xml = fetch_naxml_maintenance(cookie, "MixMatch")
        save_text(mixmatch_xml, out_dir / f"MixMatch_{ts}.xml")

        # 2) Combo definitions
        combo_xml = fetch_naxml_maintenance(cookie, "Combo")
        save_text(combo_xml, out_dir / f"Combo_{ts}.xml")

        # 3) ItemList (to resolve groups referenced by MixMatch/Combo)
        itemlist_xml = fetch_naxml_maintenance(cookie, "ItemList")
        save_text(itemlist_xml, out_dir / f"ItemList_{ts}.xml")

        # Quick, best-effort summary
        try:
            mm_root = ET.fromstring(mixmatch_xml)
            cb_root = ET.fromstring(combo_xml)
            il_root = ET.fromstring(itemlist_xml)

            mm_count = try_count(mm_root, ["MixMatch", "MixMatchRecord", "MMEntry"])
            cb_count = try_count(cb_root, ["Combo", "ComboRecord"])
            il_count = try_count(il_root, ["ItemList", "ItemListRecord"])

            log.info("--- Summary (best effort) ---")
            log.info(f"MixMatch records (≈): {mm_count}")
            log.info(f"Combo records    (≈): {cb_count}")
            log.info(f"ItemList records (≈): {il_count}")
            log.info("XML saved; inspect definitions to see items, triggers, and prices.")
        except Exception as e:
            log.warning(f"Could not parse quick summary (schema varies): {e}")

    finally:
        release_cookie(cookie)

if __name__ == "__main__":
    main()
