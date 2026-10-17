"""Deploy only complaint automation. Existing web/replay services are untouched."""
import argparse
from datetime import datetime
import getpass
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*cmd):
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true')
    args = parser.parse_args()
    python, user = str(Path(sys.executable).absolute()), getpass.getuser()
    if any(not re.fullmatch(r'[A-Za-z0-9_./-]+', str(p)) for p in [ROOT,python,user,Path.home()]):
        raise SystemExit('Use a checkout and home path without spaces or special characters')
    units = {}
    def service(description, command, once=True):
        return f'''[Unit]
Description={description}
Wants=network-online.target
After=network-online.target
[Service]
User={user}
WorkingDirectory={ROOT}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-{Path.home()}/.config/heatahead/complaints.env
Type={'oneshot' if once else 'simple'}
ExecStart={python} {command}
{'TimeoutStartSec=900' if once else 'Restart=on-failure'}
{'' if once else 'RestartSec=5'}
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
'''
    jobs = [
        ('heatahead-complaint-poll','Poll published NYC HPD heat complaints',
         'realtime/complaint_pipeline.py poll','OnBootSec=45\nOnUnitActiveSec=5min'),
        ('heatahead-complaint-reconcile','Reconcile late published complaints',
         'realtime/complaint_pipeline.py poll --lookback-days 90',
         'OnCalendar=*-*-* 04:20:00 America/New_York'),
        ('heatahead-complaint-tests','Run isolated offline complaint tests',
         '-m unittest discover -s realtime -p test_complaint_pipeline.py -v',
         'OnBootSec=2min\nOnUnitActiveSec=6h'),
        ('heatahead-monitor-tests','Run isolated live monitor integration tests',
         '-m unittest discover -s web/tests -p test_live_monitor.py -v',
         'OnBootSec=3min\nOnUnitActiveSec=6h'),
        ('heatahead-complaint-health','Check collector freshness and API',
         'realtime/complaint_pipeline.py check','OnBootSec=4min\nOnUnitActiveSec=10min'),
    ]
    units['heatahead-complaints.service'] = service('Current complaint read-only API',
        'realtime/complaint_pipeline.py serve',once=False)
    for name, description, command, schedule in jobs:
        units[name+'.service'] = service(description,command)
        units[name+'.timer'] = f'''[Unit]
Description={description}
[Timer]
{schedule}
Persistent=true
RandomizedDelaySec=20
[Install]
WantedBy=timers.target
'''
    folder = ROOT/'data/complaint-automation-units'
    folder.mkdir(parents=True,exist_ok=True)
    for name, content in units.items():
        (folder/name).write_text(content)
    print(f'Generated units: {folder}',flush=True)
    if not args.install:
        print('Review these files, then rerun with --install.')
        return
    import waitress  # noqa: F401
    run(python,'-m','unittest','discover','-s','realtime','-p','test_complaint_pipeline.py','-v')
    print('Initial source pull; this may take several minutes.',flush=True)
    run(python,'realtime/complaint_pipeline.py','poll')
    # A failed initial pull leaves installed system services unchanged.
    backup = folder/('backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir()
    for name in units:
        destination = Path('/etc/systemd/system')/name
        if destination.exists():
            run('sudo','cp','-p',str(destination),str(backup/name))
        run('sudo','install','-m','644',str(folder/name),str(destination))
    run('sudo','systemctl','daemon-reload')
    run('sudo','systemctl','enable','heatahead-complaints.service')
    run('sudo','systemctl','restart','heatahead-complaints.service')
    for name, *_ in jobs:
        run('sudo','systemctl','enable','--now',name+'.timer')
    run('sudo','systemctl','start','heatahead-complaint-tests.service')
    print('Installed. Web/replay services, model files, Vercel and firewall unchanged.',flush=True)
    print('Verify: sudo systemctl start heatahead-complaint-health.service')


if __name__ == '__main__':
    main()
