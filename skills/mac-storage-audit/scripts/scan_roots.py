#!/usr/bin/env python3
"""Bounded sequential macOS allocated-size scans; writes evidence only."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import stat
import subprocess
import time


def scan(roots, output, depth=2, timeout=60):
    output = Path(output).expanduser().resolve()
    for root in roots:
        resolved = Path(root).expanduser().resolve()
        if output == resolved or resolved in output.parents:
            raise ValueError('Evidence directory must be outside every scanned root; partition roots to exclude evidence')
    output.mkdir(parents=True, exist_ok=False)
    results, seen_files = [], set()
    for index, root in enumerate(roots):
        root = os.path.abspath(os.path.expanduser(root))
        start = time.monotonic()
        item = dict(path=root, parent=str(Path(root).parent),
                    started=dt.datetime.now(dt.timezone.utc).isoformat(),
                    allocated_kib=None, status='unknown', command=None,
                    label=Path(root).name, timeout_seconds=timeout,
                    exit_status=None, timed_out=False)
        try:
            metadata = os.lstat(root)
            if stat.S_ISLNK(metadata.st_mode):
                item['status'] = 'skipped_symlink'
            elif stat.S_ISREG(metadata.st_mode):
                identity = (metadata.st_dev, metadata.st_ino)
                item.update(status='complete', measurement='lstat_blocks',
                            allocated_kib=metadata.st_blocks / 2,
                            logical_bytes=metadata.st_size)
                if identity in seen_files:
                    item.update(status='duplicate_hardlink', allocated_kib=None)
                seen_files.add(identity)
            elif stat.S_ISDIR(metadata.st_mode):
                out, err = output / f'{index:04d}.stdout', output / f'{index:04d}.stderr'
                command = ['/usr/bin/du', '-k', '-x', '-d', str(depth), root]
                item.update(command=command, stdout=str(out), stderr=str(err), measurement='du_blocks')
                with out.open('wb') as stdout, err.open('wb') as stderr:
                    try:
                        result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
                        item['exit_status'] = result.returncode
                    except subprocess.TimeoutExpired:
                        # subprocess.run kills and reaps the child before raising.
                        item['timed_out'] = True
                rows, unparsed = [], 0
                for line in out.read_text(errors='replace').splitlines():
                    size, separator, path = line.partition('\t')
                    if separator and size.isdigit():
                        rows.append(dict(path=path, parent=str(Path(path).parent), allocated_kib=int(size)))
                        if path == root:
                            item['allocated_kib'] = int(size)
                    else:
                        unparsed += 1
                item.update(rows=rows, unparsed_lines=unparsed)
                item['status'] = ('timed_out' if item['timed_out'] else
                                  'complete' if item['exit_status'] == 0 and not unparsed and item['allocated_kib'] is not None else 'partial')
            else:
                item['status'] = 'skipped_special_file'
        except FileNotFoundError as error:
            item.update(status='missing', error=str(error))
        except PermissionError as error:
            item.update(status='permission_denied', error=str(error))
        except OSError as error:
            item.update(status='error', error=str(error))
        for row in item.get('rows', []):
            row.update(label=Path(row['path']).name, measurement='du_blocks', status=item['status'])
        item.update(ended=dt.datetime.now(dt.timezone.utc).isoformat(), elapsed_seconds=round(time.monotonic()-start, 6))
        results.append(item)
        (output / 'ledger.json').write_text(json.dumps(results, indent=2)+'\n')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots', nargs='+', help='Explicit disjoint roots; caller handles mount aliases and cloud exclusions')
    parser.add_argument('--output', required=True, help='New evidence directory; must not already exist')
    parser.add_argument('--depth', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    if args.depth < 0 or args.timeout <= 0:
        parser.error('depth must be nonnegative and timeout must be positive')
    results = scan(args.roots, args.output, args.depth, args.timeout)
    print(json.dumps({'ledger': str(Path(args.output)/'ledger.json'), 'roots': len(results),
                      'complete': sum(x['status']=='complete' for x in results),
                      'elapsed_seconds': sum(x['elapsed_seconds'] for x in results)}))


if __name__ == '__main__':
    main()
