import requests
import xml.etree.ElementTree as ET
from pathlib import Path

# --------------------------
# Your Commander connection
# --------------------------
COMMANDER_IP = "192.168.45.95"
COMMANDER_USER = "BW"
COMMANDER_PASS = "Welcome4"
BASE = f"https://{COMMANDER_IP}"
VERIFY_SSL = False  # Commander commonly uses self-signed certs

# Quiet SSL warnings if desired
requests.packages.urllib3.disable_warnings(
    requests.packages.urllib3.exceptions.InsecureRequestWarning
)

class CommanderClient:
    def __init__(self, base, user, passwd, verify=False, timeout=60):
        self.base = base.rstrip("/")
        self.user = user
        self.passwd = passwd
        self.verify = verify
        self.timeout = timeout
        self.cookie = None

    # --- Auth ---
    def validate(self):
        url = f"{self.base}/cgi-bin/CGILink"
        params = {"cmd": "validate", "user": self.user, "passwd": self.passwd}
        r = requests.get(url, params=params, verify=self.verify, timeout=self.timeout)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        co = root.find(".//cookie")
        if co is None or not (co.text or "").strip():
            raise RuntimeError("No cookie in validate response")
        self.cookie = co.text.strip()
        return self.cookie

    def release(self):
        if not self.cookie:
            return
        url = f"{self.base}/cgi-bin/CGILink"
        params = {"cmd": "releaseCredential", "cookie": self.cookie}
        try:
            requests.get(url, params=params, verify=self.verify, timeout=self.timeout)
        finally:
            self.cookie = None

    # --- NAXML Maintenance (best for whole pricebook) ---
    def naxml_view(self, dataset):
        """GET NAXML maintenance dataset (e.g., Item)"""
        if not self.cookie: self.validate()
        url = f"{self.base}/cgi-bin/NAXML"
        params = {"cmd": "vMaintenance", "dataset": dataset, "cookie": self.cookie}
        r = requests.get(url, params=params, verify=self.verify, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    def naxml_update(self, dataset, xml_payload):
        """POST NAXML maintenance dataset (e.g., Item)"""
        if not self.cookie: self.validate()
        url = f"{self.base}/cgi-bin/NAXML"
        params = {"cmd": "uMaintenance", "dataset": dataset, "cookie": self.cookie}
        r = requests.post(url, params=params, data=xml_payload,
                          headers={"Content-Type": "application/xml"},
                          verify=self.verify, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    # --- PLU-specific (CGIPLULink) ---
    def vplus_view(self, pluselect_payload_xml):
        """POST vPLUs (payload root must be <PLUSelect> per PLUs.xsd)"""
        if not self.cookie: self.validate()
        url = f"{self.base}/cgi-bin/CGIPLULink"
        params = {"cmd": "vPLUs", "cookie": self.cookie}
        r = requests.post(url, params=params, data=pluselect_payload_xml,
                          headers={"Content-Type": "application/xml"},
                          verify=self.verify, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    def uplus_update(self, plus_payload_xml):
        """POST uPLUs (payload root must be <PLUs> per PLUs.xsd)"""
        if not self.cookie: self.validate()
        url = f"{self.base}/cgi-bin/CGIPLULink"
        params = {"cmd": "uPLUs", "cookie": self.cookie}
        r = requests.post(url, params=params, data=plus_payload_xml,
                          headers={"Content-Type": "application/xml"},
                          verify=self.verify, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    # --- Stage changes to be accepted on POS (optional) ---
    def post_unmanaged_plu_changes(self, plus_payload_xml, schema="verifone"):
        """
        schema='verifone' -> /CGIUplink?cmd=umanagedcfg&subcmd=plu (payload <PLUs>)
        schema='naxml'    -> /NAXML?cmd=umanagedcfg&subcmd=Item (payload NAXML Item doc)
        """
        if not self.cookie: self.validate()
        if schema.lower() == "naxml":
            url = f"{self.base}/cgi-bin/NAXML"
            params = {"cmd": "umanagedcfg", "subcmd": "Item", "cookie": self.cookie}
        else:
            url = f"{self.base}/cgi-bin/CGIUplink"
            params = {"cmd": "umanagedcfg", "subcmd": "plu", "cookie": self.cookie}

        r = requests.post(url, params=params, data=plus_payload_xml,
                          headers={"Content-Type": "application/xml"},
                          verify=self.verify, timeout=self.timeout)
        r.raise_for_status()
        return r.text

# --------------------------
# Example usage
# --------------------------
if __name__ == "__main__":
    client = CommanderClient(BASE, COMMANDER_USER, COMMANDER_PASS, verify=VERIFY_SSL)

    try:
        # 1) PULL THE ENTIRE PRICEBOOK via NAXML (one call)
        pricebook_xml = client.naxml_view("Item")  # returns all items (PLUs)
        Path("pricebook_full_naxml.xml").write_text(pricebook_xml, encoding="utf-8")
        print("Saved: pricebook_full_naxml.xml")

        # 2) (Optional) PULL PLUs via vPLUs with a <PLUSelect/> payload
        #    NOTE: You must supply a valid PLUSelect per PLUs.xsd for your site.
        # pluselect_xml = """<PLUSelect xmlns="urn:vfi-sapphire:np.domain.2001-07-01">...</PLUSelect>"""
        # plulist_xml = client.vplus_view(pluselect_xml)
        # Path("pricebook_vplus.xml").write_text(plulist_xml, encoding="utf-8")
        # print("Saved: pricebook_vplus.xml")

        # 3) (Optional) UPDATE ITEM PRICES
        #    You need a valid XML payload that matches your schema:
        #    - For NAXML uMaintenance&dataset=Item -> PBIMaintenance/Item document
        #    - For uPLUs -> PLUs.xsd (root <PLUs>)
        #
        # EXAMPLE placeholder (you must replace with your site's valid schema payload):
        # plus_update_xml = """<PLUs xmlns="urn:vfi-sapphire:np.domain.2001-07-01"> ... </PLUs>"""
        # result = client.uplus_update(plus_update_xml)
        # print("uPLUs response:", result)

        # 4) (Optional) Stage updates for POS acceptance
        # staged_result = client.post_unmanaged_plu_changes(plus_update_xml, schema="verifone")
        # print("umanagedcfg response:", staged_result)

    finally:
        client.release()
