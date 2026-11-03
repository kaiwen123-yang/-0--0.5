"""Historical VPN launcher disabled by the user's 2026-11-03 instruction."""
from bct_common import TRANSFER, save, now

def main():
    save(TRANSFER/'server_vpn_fallback.json',dict(at_utc=now(),status='disabled_by_user',server_vpn_allowed=False,pc_vpn_allowed=False))
    print('VPN_FALLBACK_DISABLED_BY_USER',flush=True)

if __name__=='__main__':main()
