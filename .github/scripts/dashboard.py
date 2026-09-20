"""Build a self-contained SVG from public repositories and GitHub profile activity."""
import collections
import datetime as dt
import html
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def api(endpoint, payload=None):
    command = ['gh', 'api', endpoint]
    if payload is not None:
        command += ['--input', '-']
    data = json.loads(subprocess.check_output(command, input=json.dumps(payload).encode() if payload is not None else None))
    if isinstance(data, dict) and data.get('errors'):
        raise RuntimeError('GitHub query failed: ' + json.dumps(data['errors']))
    return data


def collect(owner):
    profile = api('users/' + owner)
    repos = []
    page = 1
    while True:
        batch = api(f'users/{owner}/repos?type=owner&per_page=100&page={page}')
        repos.extend(r for r in batch if not r['private'])
        if len(batch) < 100:
            break
        page += 1
    languages = collections.Counter()
    for repo in repos:
        if not repo['fork']:
            languages.update(api(f'repos/{repo["full_name"]}/languages'))
    query = '''query($login:String!) { user(login:$login) { contributionsCollection {
      totalCommitContributions
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    } } }'''
    activity = api('graphql', {'query': query, 'variables': {'login': owner}})['data']['user']['contributionsCollection']
    days = [d for w in activity['contributionCalendar']['weeks'] for d in w['contributionDays']][-28:]
    return {
        'owner': profile['login'], 'repos': repos, 'languages': languages,
        'contributions': activity['contributionCalendar']['totalContributions'],
        'commits': activity['totalCommitContributions'], 'days': days,
        'updated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    }


def render(data):
    parts = ['''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="650" viewBox="0 0 900 650" role="img" aria-labelledby="title desc">
<title id="title">GitHub system dashboard</title>
<desc id="desc">Repository totals, contribution activity, language usage and recently pushed public repositories. Updated daily from GitHub.</desc>
<defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#14212d" stroke-width="0.5"/></pattern></defs>
<rect x="0.5" y="0.5" width="899" height="649" rx="18" fill="#080e16" stroke="#263543"/>
<rect x="1" y="1" width="898" height="648" rx="18" fill="url(#grid)"/>
<path d="M25 20H75 M25 20V31 M875 20H825 M875 20V31" fill="none" stroke="#58d5b0" stroke-width="2"/>
''']

    def text(x, y, value, size=12, color='#93a8b9', weight='400', anchor='start', mono=True):
        family = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' if mono else 'Arial, Helvetica, sans-serif'
        parts.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-family="{family}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(str(value))}</text>')

    def rect(x, y, w, h, fill='#0d1722', stroke='#233343', radius=9):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>')

    def trim(value, maximum):
        return value if len(value) <= maximum else value[:maximum-1] + '…'

    owner = data['owner']
    text(26, 48, 'GITHUB / SYSTEM DASHBOARD', 12, '#58d5b0', '600')
    text(26, 81, owner, 27, '#e6f1f7', '700')
    text(874, 48, 'PROFILE TELEMETRY', 11, '#93a8b9', anchor='end')
    text(874, 76, 'SNAPSHOT  /  DAILY REFRESH', 10, '#58d5b0', anchor='end')
    metrics = [
        ('PUBLIC REPOS', len(data['repos']), 'owned repositories'),
        ('STARS RECEIVED', sum(r['stargazers_count'] for r in data['repos']), 'across public repos'),
        ('CONTRIBUTIONS', data['contributions'], 'past 12 months'),
        ('COMMIT CONTRIB.', data['commits'], 'past 12 months'),
    ]
    for index, (label, value, detail) in enumerate(metrics):
        x = 26 + index*215
        rect(x, 103, 203, 99)
        parts.append(f'<path d="M{x+15} 119H{x+35}" stroke="#58d5b0" stroke-width="2"/>')
        text(x+15, 139, label, 10)
        text(x+15, 172, f'{value:,}', 30, '#edf7fa', '600')
        text(x+15, 191, detail, 9, '#8497a8')

    rect(26, 216, 512, 211)
    rect(552, 216, 322, 211)
    text(43, 241, '01 / ACTIVITY SIGNAL', 11, '#58d5b0', '600')
    text(521, 241, '28 DAYS', 10, anchor='end')
    days = data['days']
    total = sum(d['contributionCount'] for d in days)
    text(43, 267, f'{total} contributions', 16, '#e6f1f7', '600', mono=False)
    text(521, 266, f'{sum(d["contributionCount"] > 0 for d in days)} active days', 10, anchor='end')
    peak = max(1, max((d['contributionCount'] for d in days), default=0))
    for y, value in [(289, peak), (334, peak/2), (379, 0)]:
        parts.append(f'<path d="M67 {y}H518" stroke="#22313e" stroke-dasharray="3 5"/>')
        text(57, y+3, f'{value:g}', 9, anchor='end')
    for index, day in enumerate(days):
        h = max(2, day['contributionCount']/peak*90)
        x = 72 + index*16
        color = '#58d5b0' if day['contributionCount'] else '#2a3b4a'
        parts.append(f'<rect x="{x}" y="{379-h:.2f}" width="10" height="{h:.2f}" rx="2" fill="{color}"><title>{day["date"]}: {day["contributionCount"]} contributions</title></rect>')
    if days:
        text(70, 403, days[0]['date'][5:], 10)
        text(516, 403, days[-1]['date'][5:], 10, anchor='end')

    text(569, 241, '02 / LANGUAGE MIX', 11, '#58d5b0', '600')
    text(569, 263, 'Public source repos · by code bytes', 10, mono=False)
    languages = data['languages']
    items = languages.most_common(3)
    if len(languages) > 3:
        items.append(('Other', sum(languages.values())-sum(v for _, v in items)))
    colors = ['#58d5b0', '#64b5f6', '#bb9af7', '#f2c879']
    all_bytes = sum(languages.values())
    if not items:
        text(569, 310, 'No language data yet', 12)
    for index, (language, count) in enumerate(items):
        y = 285 + index*33
        pct = count/all_bytes*100
        text(569, y, trim(language, 23), 11, '#dce8ef')
        text(855, y, f'{pct:.1f}%', 11, colors[index], anchor='end')
        rect(569, y+8, 286, 5, '#21303e', 'none', 2)
        rect(569, y+8, max(1, 286*pct/100), 5, colors[index], 'none', 2)

    rect(26, 441, 848, 158)
    text(43, 466, '03 / REPOSITORY INDEX', 11, '#58d5b0', '600')
    text(856, 466, 'RECENT PUSHES', 10, anchor='end')
    text(43, 489, 'REPOSITORY', 9)
    text(532, 489, 'LANGUAGE', 9)
    text(690, 489, 'STARS', 9, anchor='end')
    text(856, 489, 'PUSHED (UTC)', 9, anchor='end')
    for index, repo in enumerate(sorted(data['repos'], key=lambda r:r['pushed_at'] or '', reverse=True)[:3]):
        y = 516 + index*29
        parts.append(f'<path d="M43 {y-18}H856" stroke="#21303e"/>')
        text(43, y, trim(repo['name'], 46), 12, '#dce8ef')
        text(532, y, trim(repo['language'] or '—', 16), 10)
        text(690, y, repo['stargazers_count'], 11, '#58d5b0', anchor='end')
        text(856, y, (repo['pushed_at'] or '—')[:10], 10, anchor='end')
    if not data['repos']:
        text(43, 528, 'No public repositories yet', 12)
    text(26, 625, 'SOURCE / GITHUB API', 9, '#7f94a6')
    text(874, 625, 'UPDATED / '+data['updated'], 9, '#7f94a6', anchor='end')
    parts.append('</svg>\n')
    svg = '\n'.join(parts)
    ET.fromstring(svg)
    return svg


if __name__ == '__main__':
    owner = os.environ.get('PROFILE_OWNER') or os.environ['GITHUB_REPOSITORY_OWNER']
    data = collect(owner)
    output = Path('assets/github-dashboard.svg')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data))
    print(f'Dashboard generated for {owner}: {len(data["repos"])} public repos, {data["contributions"]} contributions.')
