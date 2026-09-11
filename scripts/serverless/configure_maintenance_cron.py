"""Install/update DATAEZ-only Supabase schedules; secrets are read from ignored config.

No schedules are installed until the protected deployment's maintenance endpoint
passes authentication and health checks. No secret values are printed.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

from dotenv import dotenv_values
import httpx

ROOT=Path(__file__).resolve().parents[2]
REF='whbygnzoaehvlddltwlb'
PREDICATES={
    'index':"""EXISTS(SELECT 1 FROM public.search_index_jobs WHERE status IN ('pending','retry','processing')
        AND next_attempt_at<=clock_timestamp() AND (status<>'processing' OR lease_until<=clock_timestamp()))""",
    'metrics':"""EXISTS(SELECT 1 FROM public.dashboard_widgets w JOIN public.projects p ON p.id=w.project_id AND p.user_id=w.user_id
        WHERE w.next_refresh_at<=clock_timestamp() AND w.refresh_interval_seconds>0 AND w.widget_data ? 'metric_definition' AND p.deleted_at IS NULL)""",
    'cleanup':"""(EXISTS(SELECT 1 FROM public.upload_sessions WHERE expires_at<clock_timestamp()-interval '10 minutes')
        OR EXISTS(SELECT 1 FROM public.import_batches WHERE status NOT IN ('committed','expired') AND expires_at<=clock_timestamp()))"""
}


def run_sql(query):
    temp=ROOT/'.local-test/supabase'/f'cron-{uuid4().hex}.sql'
    temp.parent.mkdir(parents=True,exist_ok=True)
    temp.write_text(query,encoding='utf-8')
    try:
        result=subprocess.run([shutil.which('supabase'),'db','query','--linked','--profile','supabase','--file',str(temp),'--output','json'],
                              cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
        if result.returncode:
            detail=result.stderr+result.stdout
            for value in dotenv_values(ROOT/'.env.supabase.local').values():
                if value and len(value)>8:detail=detail.replace(value,'[redacted]')
            raise RuntimeError('Supabase schedule SQL failed: '+detail[-1800:])
        return result.stdout
    finally:temp.unlink(missing_ok=True)


def dispatch_sql(kind):
    assert kind in PREDICATES
    return f"""SELECT net.http_post(
        url := (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='dataez_maintenance_url') || '/api/internal/maintenance/{kind}',
        headers := jsonb_build_object('Content-Type','application/json',
            'Authorization','Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='dataez_maintenance_secret'),
            'x-vercel-protection-bypass',(SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='dataez_maintenance_bypass')),
        body := '{{}}'::jsonb, timeout_milliseconds := 150000)
        WHERE {PREDICATES[kind]}
        AND NOT EXISTS(SELECT 1 FROM public.maintenance_runs WHERE kind='{kind}' AND
            (lease_until>clock_timestamp() OR last_finished_at>clock_timestamp()-interval '10 seconds'));"""


def main(deployment, pause=False):
    assert (ROOT/'supabase/.temp/project-ref').read_text().strip()==REF
    config=dotenv_values(ROOT/'.env.supabase.local')
    assert config['SUPABASE_URL']==f'https://{REF}.supabase.co'
    if pause:
        run_sql("SELECT cron.alter_job(jobid,active := false) FROM cron.job WHERE jobname IN ('dataez-index','dataez-metrics','dataez-cleanup','dataez-cron-history');")
        print('DATAEZ maintenance schedules paused');return
    assert deployment == 'https://dataez-api.vercel.app' or re.fullmatch(r'https://dataez-[a-z0-9]+-gnb1202-navercoms-projects\.vercel\.app',deployment)
    secret=config['MAINTENANCE_SECRET']; bypass=config['MAINTENANCE_VERCEL_BYPASS']
    headers={'Authorization':'Bearer '+secret,'x-vercel-protection-bypass':bypass}
    response=httpx.get(deployment+'/api/internal/maintenance/status',headers=headers,timeout=30,follow_redirects=False)
    assert response.status_code==200 and isinstance(response.json().get('tasks'),list), 'Runner status check failed'
    assert httpx.get(deployment+'/api/internal/maintenance/status',headers={'x-vercel-protection-bypass':bypass},timeout=30).status_code==401
    def literal(value):return "'"+value.replace("'","''")+"'"
    query="""CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog;
CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions;
"""
    for name,value in [('dataez_maintenance_url',deployment),('dataez_maintenance_secret',secret),('dataez_maintenance_bypass',bypass)]:
        query+=f"""DO $vault$ DECLARE existing uuid; BEGIN
            SELECT id INTO existing FROM vault.secrets WHERE name={literal(name)};
            IF existing IS NULL THEN PERFORM vault.create_secret({literal(value)},{literal(name)});
            ELSE PERFORM vault.update_secret(existing,{literal(value)},{literal(name)}); END IF;
            END $vault$;\n"""
    for kind in PREDICATES:
        schedule='*/10 * * * *' if kind=='cleanup' else '* * * * *'
        query+=f'SELECT cron.schedule({literal("dataez-"+kind)},{literal(schedule)},{literal(dispatch_sql(kind))});\n'
        query+=f"SELECT cron.alter_job(jobid,active := true) FROM cron.job WHERE jobname={literal('dataez-'+kind)};\n"
    history="DELETE FROM cron.job_run_details WHERE jobid IN (SELECT jobid FROM cron.job WHERE jobname IN ('dataez-index','dataez-metrics','dataez-cleanup','dataez-cron-history')) AND start_time<now()-interval '7 days';"
    query+=f"SELECT cron.schedule('dataez-cron-history','17 3 * * *',{literal(history)});\n"
    run_sql(query)
    print('DATAEZ schedules installed: index/metrics every minute, cleanup every ten minutes; no-work dispatch is skipped')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment');parser.add_argument('--pause',action='store_true')
    args=parser.parse_args()
    try:main(args.deployment,args.pause)
    except Exception as error:
        print('Schedule configuration failed:',type(error).__name__,str(error) if isinstance(error,RuntimeError) else '');raise SystemExit(1)
