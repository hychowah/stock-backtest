"""Summarize unfinished operations, operation times, slow requests and failures in the development logs.

Run from the project folder: python3 -m tools.ops.log_summary [--days N] [folder]
The default folder is data/logs. Reading never changes or removes a log.
Stage shares can overlap, so one operation's shares need not add up to 100%.
An unfinished operation is still running, or its process stopped first.
"""
import argparse
from datetime import datetime, timedelta, timezone
import statistics

from backtest.runtime import diagnostics


def duration(seconds):
    return f'{seconds:.2f}s' if seconds<10 else f'{seconds:.1f}s'


def percentile(values, share):
    ordered=sorted(values)
    return ordered[min(len(ordered)-1,int(share*len(ordered)))]


def group(record):
    """Name an operation by the settings that change its cost."""
    parts=[record['event']]
    for key in ('mode','action'):
        if record.get(key):parts.append(str(record[key]))
    if record.get('strategy'):parts.append('strategy')
    if record.get('pool') and record['event']=='backtest.run':parts.append(str(record['pool']))
    return ' '.join(parts)


def population(record):
    """Time only like with like: a refusal or an already-current check is its own row."""
    return group(record)+' '+str(record['outcome'])


def stages(records, top):
    """Each stage's share of the summed operation seconds, largest first."""
    total=sum(record['seconds'] for record in records) or 1
    sums={}
    for record in records:
        for name,seconds in record.get('stages',{}).items():sums[name]=sums.get(name,0)+seconds
    ranked=sorted(sums.items(),key=lambda item:-item[1])[:top]
    return ', '.join(f'{name} {seconds/total:.0%}' for name,seconds in ranked)


def unfinished(events):
    """The latest progress line of each operation that has no end line.

    A process, its server start and the operation number identify an
    operation: a later server can reuse a process ID and its log file.
    """
    latest={};starts={}
    for record in events:
        pid=record.get('pid')
        if record['event']=='server.starting':
            starts[pid]=starts.get(pid,0)+1;continue
        key=(pid,starts.get(pid,0),record.get('op'))
        if record.get('state') in ('running','step'):latest[key]=record
        elif 'outcome' in record:latest.pop(key,None)
    lines=[]
    for (pid,_,_),record in sorted(latest.items(),key=lambda item:item[1]['time']):
        parts=[f'{record["time"]}  {record["event"]}  pid {pid}  {duration(record["seconds"])} in']
        if record.get('state')=='step':parts.append(f'step {record["step"]} ended after {duration(record["step_seconds"])}')
        elif record.get('last_step'):parts.append(f'after step {record["last_step"]} ({duration(record["since_step_seconds"])} ago)')
        if record.get('stage'):parts.append(f'in {record["stage"]}')
        if record.get('within'):parts.append('within '+' > '.join(record['within']))
        lines.append('  '.join(parts))
    return lines


def summarize(events, recent=8):
    lines=[]
    running=unfinished(events)
    if running:lines+=['Unfinished operations, latest progress line']+running+['']
    operations={}
    for record in events:
        if isinstance(record.get('seconds'),(int,float)) and 'outcome' in record:
            operations.setdefault(population(record),[]).append(record)
    if not operations:lines.append('No timed operation has finished yet.')
    else:lines.append(f'{"Operation and outcome":<46}{"runs":>5}{"median":>9}{"p90":>9}{"max":>9}  main stages')
    for name,records in sorted(operations.items()):
        seconds=[record['seconds'] for record in records]
        lines.append(f'{name:<46}{len(records):>5}{duration(statistics.median(seconds)):>9}{duration(percentile(seconds,.9)):>9}{duration(max(seconds)):>9}  {stages(records,3)}')
    runs=sorted((record for record in events if record['event']=='backtest.run' and 'outcome' in record),key=lambda record:record['time'])[-recent:]
    if runs:
        lines+=['',f'Latest {len(runs)} backtest runs']
        for record in reversed(runs):
            shape=' '.join(f'{key}={record[key]}' for key in ('periods','trials') if key in record)
            top=sorted(record.get('stages',{}).items(),key=lambda item:-item[1])[:3]
            lines.append(f'{record["time"]}  {group(record):<36}{record["outcome"]:<10}{duration(record["seconds"]):>9}  {shape}  '
                         +', '.join(f'{name} {duration(seconds)}' for name,seconds in top))
    slow={}
    for record in events:
        if record['event']=='http.slow':slow.setdefault(f'{record.get("method")} {record.get("route")}',[]).append(record['seconds'])
    if slow:
        lines+=['','Slow requests (1 s or more)']
        for name,seconds in sorted(slow.items(),key=lambda item:-max(item[1])):
            lines.append(f'{name:<52}{len(seconds):>5}  median {duration(statistics.median(seconds))}  max {duration(max(seconds))}')
    failures={}
    for record in events:
        if record['level']=='ERROR':
            kind=(record.get('errors') or [{}])[0].get('type','unknown')
            failures.setdefault((record['event'],kind),[]).append(record['time'])
    if failures:
        lines+=['','Failures (traces are in the log files)']
        for (name,kind),times in sorted(failures.items()):
            lines.append(f'{name:<36}{kind:<24}{len(times):>5}  last {max(times)}')
    return lines


def main(arguments=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder',nargs='?',default=diagnostics.DIRECTORY)
    parser.add_argument('--days',type=int,help='Only events from the last N days')
    args=parser.parse_args(arguments)
    events=list(diagnostics.records(args.folder))
    if args.days is not None:
        cutoff=(datetime.now(timezone.utc)-timedelta(days=args.days)).strftime('%Y-%m-%dT%H:%M:%S')
        events=[record for record in events if record['time']>=cutoff]
    if not events:
        print(f'No logged events in {diagnostics.relative_path(args.folder)}.');return
    print(f'{len(events)} events from {min(r["time"] for r in events)} to {max(r["time"] for r in events)} in {diagnostics.relative_path(args.folder)}')
    print('\n'.join(summarize(events)))


if __name__=='__main__':main()
