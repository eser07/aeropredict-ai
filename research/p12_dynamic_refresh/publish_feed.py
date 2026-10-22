"""Package a successful run for the isolated data branch, never source code.

GitHub Actions performs its normal fast-forward commit/push separately. No
credentials, network, shell, or Git write in this program. Weekly first
observations are append-only; hourly latest is a replaceable pointer.
"""
import argparse, json, shutil
from pathlib import Path
from refresh import validate_snapshot, replace_json

def prepare(output,feed):
    output=Path(output);feed=Path(feed);feed.mkdir(parents=True,exist_ok=True)
    s=json.loads((output/'latest.json').read_text(encoding='utf-8'))
    previous=json.loads((feed/'latest.json').read_text(encoding='utf-8')) if (feed/'latest.json').exists() else None
    validate_snapshot(s,previous)
    replace_json(feed/'latest.json',s)
    replace_json(feed/'status.json',{'state':'complete','at_utc':s['observed_at_utc'],'pool_count':s['pool_count'],'block':s['context']['block_number']})
    for j,total in enumerate(s['totals'][:4]):
        target=feed/'weekly'/total['end_utc'][:10]/'first_observation.json'
        if not target.exists():
            replace_json(target,{'context':s['context'],'token_metadata':s['token_metadata'],'prices':s['prices'],'totals':total,'pools':[{'index':p['index'],'address':p['address'],'fees_usd':p['fees'][j],'bribes_usd':p['bribes'][j],'rewards':{k:[{'token_address':t['token_address'],'raw':t['raw'][j]} for t in p['rewards'][k]['tokens']] for k in ['fees','bribes']}} for p in s['pools']]})
    (feed/'README.md').write_text('# AeroPredict provider observations\n\nHourly data only. Source code is on grass-main. Amounts are read at one finalized Base block, not independent historical boundary snapshots. USD uses collection-time prices; missing prices are unknown. Latest data has no new GenLayer attestation. Weekly first observations are immutable. No wallet or transaction is involved.\n',encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--feed',required=True,type=Path);a=p.parse_args();prepare(a.output,a.feed)
