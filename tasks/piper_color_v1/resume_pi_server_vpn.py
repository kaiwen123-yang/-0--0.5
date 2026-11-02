"""Wait for the current academic batch; switch once to the authorized D57 VPN on failure."""
import os
import subprocess
import sys
import time
from pathlib import Path
from bct_common import ROOT, TRANSFER, read, save, append, now

def main():
    pid=int(sys.argv[1])
    status=TRANSFER/'server_vpn_fallback.json'
    save(status,dict(at_utc=now(),status='waiting_current_academic_batch',pid=pid,server_vpn_allowed=True,pc_vpn_allowed=False))
    while Path(f'/proc/{pid}').exists():time.sleep(15)
    mapping=read(TRANSFER/'mapping.json')
    pending=[j for j in mapping['jobs'] if j['status']!='uploaded']
    if not pending:
        save(status,dict(at_utc=now(),status='academic_batch_completed_no_switch'));return
    progress=read(TRANSFER/'progress.json')
    network_failure=progress.get('status')=='paused_academic_proxy_unavailable' or any(
        any(word in j.get('error','').lower() for word in ('broken pipe','proxy/api','transport','handshake','timeout','eof','github upload exit')) for j in pending)
    if not network_failure:
        save(status,dict(at_utc=now(),status='pending_non_network_issue',remaining=len(pending)));return
    os.environ['PI_GITHUB_TRANSPORT']='server_clash'
    from upload_pi_progressive import release,TAG,reconcile_remote_receipts
    for attempt in range(3):
        try:
            rid,assets=release(TAG);break
        except Exception as exc:
            save(status,dict(at_utc=now(),status='server_vpn_api_unavailable',attempt=attempt+1,error=repr(exc),pc_vpn_used=False))
            if attempt==2:return
            time.sleep(15)
    reconcile_remote_receipts(mapping,assets)
    retried=[]
    for job in mapping['jobs']:
        if job['status']=='uploaded' or job['attempts']<3 or job['name'] in assets:continue
        if not any(word in job.get('error','').lower() for word in ('broken pipe','proxy/api','transport','handshake','timeout','eof','github upload exit')):continue
        event=dict(at_utc=now(),event='new_authorized_transport_batch',name=job['name'],previous_attempts=job['attempts'],previous_error=job.get('error'),transport='d57_server_clash',remote_name_absent=True,next_attempt_cap=3)
        append(TRANSFER/'receipts.jsonl',event)
        job.setdefault('attempt_history',[]).append(event)
        job['attempts']=0;job['status']='queued';retried.append(job['name'])
    save(TRANSFER/'mapping.json',mapping)
    event=dict(at_utc=now(),status='resuming_via_d57_server_vpn',previous_status=progress.get('status'),transport='d57_server_clash',pc_vpn_used=False,reconciled_retry_assets=retried)
    save(status,event)
    save(ROOT/'publication/pi-progressive-upload-20261101/server_vpn_fallback.json',event)
    print('SERVER_VPN_FALLBACK',now(),flush=True)
    result=subprocess.run(['/root/miniconda3/bin/python','-u',str(ROOT/'tasks/piper_color_v1/deliver_pi0_ef.py')],cwd=ROOT,env=dict(os.environ))
    save(status,dict(at_utc=now(),status='vpn_batch_finished',returncode=result.returncode,progress=read(TRANSFER/'progress.json'),pc_vpn_used=False))
    print('SERVER_VPN_BATCH_EXIT',result.returncode,flush=True)

if __name__=='__main__':main()
